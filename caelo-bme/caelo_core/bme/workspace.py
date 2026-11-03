"""BME stdio MCP bridge. No shell, delete, overwrite, network, or arbitrary paths."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import uuid

from .engine.safety import SafetyError, checked_root, checked_path, read_source, source_path, ReportStore
from .engine.analysis import Dataset
from .engine.workflow import profile, default_plan, review, render, export_zip, detect_spikes
from .engine.monitor import FolderMonitor, image_preview
from .engine.library import decode

HERE = Path(__file__).resolve().parent
MAX_MESSAGE = 1_000_000


def tool(name, description, properties=None, required=(), *, read_only=True):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties or {},
                            "required": list(required), "additionalProperties": False},
            "annotations": {"readOnlyHint": read_only, "destructiveHint": False,
                            "openWorldHint": False}}


STRING = {"type": "string", "minLength": 1, "maxLength": 500}
FILE = {"type": "string", "minLength": 1, "maxLength": 500,
        "description": "Relative path under the source directory, or samples/name for synthetic demos."}
TOOLS = [
    tool("workspace_info", "Inspect the authorized read-only source, separate output folder, and tool limits."),
    tool("list_sources", "List regular files at the source root or in synthetic samples, without recursive reading.",
         {"area": {"type": "string", "enum": ["source", "samples"]}}),
    tool("read_document", "Read bounded TXT/MD/PDF text from the authorized source. Text enters the model context. PDF citations use physical pages.",
         {"file": FILE, "page": {"type": "integer", "minimum": 1}}, ("file",)),
    tool("paper_page", "Render one authorized physical PDF page for the model. The image enters the model context.",
         {"file": FILE, "page": {"type": "integer", "minimum": 1}}, ("file", "page")),
    tool("inspect_table", "Inspect a CSV/TSV/XLSX or Spark kinetics table locally. Return aggregates and a proposed mapping, without raw rows.",
         {"file": FILE, "sheet": STRING}, ("file",)),
    tool("spike_candidates", "Flag exploratory spikes within individual well kinetics. Do not delete data or apply exclusions.",
         {"dataset_id": STRING, "threshold": {"type": "number", "minimum": 3, "maximum": 10}}, ("dataset_id",)),
    tool("review_chart", "Review aggregate statistics and exclusion reasons without saving. Verify groups, independent replicates, and exclusion evidence with the user.",
         {"dataset_id": STRING, "plan": {"type": "object",
             "description": "Use the returned suggested_plan keys; x/y/group/replicate/error and optional range/exclude_rows/exclude_reason."}},
         ("dataset_id", "plan")),
    tool("export_chart", "Export a reviewed analysis to new PNG and ZIP files, including SVG, source hash, and filtering audit.",
         {"review_id": STRING}, ("review_id",), read_only=False),
    tool("save_draft", "Save a new report or code draft without overwriting or execution. Do not include credentials or patient identifiers.",
         {"text": {"type": "string", "maxLength": 200000},
          "extension": {"type": "string", "enum": ["md", "txt", "py", "m", "ijm", "R"]}},
         ("text", "extension"), read_only=False),
    tool("start_image_monitor", "Watch new images in a source-relative subfolder. Record local metadata without uploading images.",
         {"folder": {"type": "string", "maxLength": 500}}, read_only=False),
    tool("image_monitor_events", "Get stable new-image metadata events without reading image contents."),
    tool("view_image", "View a selected source/sample image. The thumbnail enters model context and is not suitable for raw-pixel quantification.",
         {"file": FILE}, ("file",)),
]


class BMEWorkspace:
    def __init__(self, source: Path, output: Path, samples: Path = HERE / "samples"):
        self.source = checked_root(source)
        self.samples = checked_root(samples)
        self.output = checked_path(output, must_exist=False)
        ReportStore(self.output, self.source)
        ReportStore(self.output, self.samples)
        self.datasets = {}
        self.reviews = {}
        self.monitor = None
        self.events = []
        self.monitor_stop = threading.Event()
        self.event_lock = threading.Lock()

    def locate(self, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 500:
            raise SafetyError("Invalid file name.")
        value = value.replace("\\", "/")
        root, relative = (self.samples, value[8:]) if value.startswith("samples/") else (self.source, value)
        return root, relative, source_path(root, relative)

    def store(self):
        ReportStore(self.output, self.samples)
        return ReportStore(self.output, self.source)

    def audit(self, name, args, *, result_paths=()):
        # Never retain content, user prompts, API keys, raw rows, or document text.
        entry = {"tool": name, "argument_names": sorted(args),
                 "result_names": [Path(p).name for p in result_paths]}
        self.store().create(json.dumps(entry, ensure_ascii=False), kind="audit", suffix=".json")

    def new_file(self, payload: bytes, extension: str):
        if extension not in {"md", "txt", "py", "m", "ijm", "R", "svg"} or len(payload) > 2_000_000:
            raise SafetyError("Invalid output type or size.")
        self.store()
        self.output.mkdir(parents=True, exist_ok=True)
        self.store()
        path = self.output / f"draft-{uuid.uuid4().hex}.{extension}"
        with path.open("xb") as stream:
            stream.write(payload)
        return path

    def call(self, name, args):
        spec = next((t for t in TOOLS if t["name"] == name), None)
        if spec is None or not isinstance(args, dict):
            raise SafetyError("Unknown tool.")
        schema = spec["inputSchema"]
        if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
            raise SafetyError("Tool arguments do not match the schema.")
        for key, value in args.items():
            field = schema["properties"][key]
            valid = {"string": lambda: isinstance(value, str), "object": lambda: isinstance(value, dict),
                     "integer": lambda: type(value) is int, "number": lambda: type(value) in (int, float)}
            if not valid[field["type"]]() or ("enum" in field and value not in field["enum"]):
                raise SafetyError("Invalid tool argument type.")
            if isinstance(value, str) and not field.get("minLength", 0) <= len(value) <= field.get("maxLength", 500):
                raise SafetyError("Text exceeds the length limit.")
            if type(value) in (int, float) and not field.get("minimum", -1e99) <= value <= field.get("maximum", 1e99):
                raise SafetyError("Numeric argument is outside the allowed range.")
        result = getattr(self, name)(**args)
        # Avoid unbounded audit-file growth from the UI's metadata polling.
        if name not in {"workspace_info", "list_sources", "image_monitor_events"} or result.get("events"):
            self.audit(name, args)
        return result

    def workspace_info(self):
        return {"source_read_only": str(self.source), "output": str(self.output),
                "samples": "samples/kinetics_demo.csv, samples/biosensor_demo.csv, samples/paper_demo.pdf",
                "limits": "No shell, delete, overwrite or external software control. This is an application boundary, not an OS sandbox.",
                "cloud": "Approved tool text/images enter the selected OpenAI model context. Caelo BME stores local session history."}

    def list_sources(self, area="source"):
        root = self.samples if area == "samples" else self.source
        result = []
        checked_root(root)
        for count, item in enumerate(root.iterdir()):
            if count >= 500:
                break
            if item.name.startswith("."):
                continue
            try:
                actual = source_path(root, item.name)
                if actual.stat().st_nlink != 1:
                    continue
                result.append({"file": ("samples/" if area == "samples" else "") + item.name,
                               "bytes": actual.stat().st_size})
            except (SafetyError, OSError):
                continue
        return {"files": result, "limit": 500}

    def read_document(self, file, page=1):
        root, relative, path = self.locate(file)
        raw = read_source(root, relative)
        if path.suffix.lower() == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if len(reader.pages) > 500 or not 1 <= page <= len(reader.pages):
                raise SafetyError("Invalid page number or document page limit exceeded.")
            text = reader.pages[page-1].extract_text() or ""
            return {"citation": f"[{path.name}-P{page:03}]", "pages": len(reader.pages),
                    "text": text[:14000], "truncated": len(text) > 14000,
                    "source_sha256": hashlib.sha256(raw).hexdigest()}
        if path.suffix.lower() not in {".txt", ".md", ".py", ".m", ".ijm", ".r"}:
            raise SafetyError("This tool supports text, code, and PDF. Use inspect_table for tables.")
        text = decode(raw)
        return {"source": path.name, "text": text[:14000], "truncated": len(text) > 14000,
                "source_sha256": hashlib.sha256(raw).hexdigest()}

    def paper_page(self, file, page):
        root, relative, path = self.locate(file)
        if path.suffix.lower() != ".pdf":
            raise SafetyError("Select a PDF file.")
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(read_source(root, relative)) as doc:
            if not 1 <= page <= len(doc) <= 500:
                raise SafetyError("Invalid page number or document page limit exceeded.")
            pdfpage = doc[page-1]
            try:
                scale = min(1.5, 1600 / max(pdfpage.get_size()))
                bitmap = pdfpage.render(scale=scale)
                try:
                    out = io.BytesIO()
                    bitmap.to_pil().save(out, format="PNG")
                finally:
                    bitmap.close()
            finally:
                pdfpage.close()
        return {"_image": out.getvalue(), "citation": f"[{path.name}-P{page:03}]"}

    def inspect_table(self, file, sheet=None):
        root, relative, path = self.locate(file)
        data = Dataset.from_bytes(root, relative, read_source(root, relative), sheet)
        identifier = uuid.uuid4().hex
        self.datasets[identifier] = data
        while len(self.datasets) > 4:
            del self.datasets[next(iter(self.datasets))]
        return {"dataset_id": identifier, "source_sha256": data.sha256,
                "profile": profile(data), "suggested_plan": default_plan(data), "warnings": data.warnings,
                "note": "Suggested mappings need user review. No raw rows returned. No points excluded."}

    def dataset(self, identifier):
        if identifier not in self.datasets:
            raise SafetyError("The dataset snapshot has expired. Run inspect_table again.")
        return self.datasets[identifier]

    def spike_candidates(self, dataset_id, threshold=3.5):
        data = self.dataset(dataset_id)
        return detect_spikes(data, {**default_plan(data), "spike_threshold": threshold})

    def review_chart(self, dataset_id, plan):
        reviewed = review(self.dataset(dataset_id), plan)
        identifier = uuid.uuid4().hex
        self.reviews[identifier] = reviewed
        while len(self.reviews) > 4:
            del self.reviews[next(iter(self.reviews))]
        public = reviewed.public()
        public.pop("preview", None)
        return {"review_id": identifier, **public,
                "next": "Explain the grouping/replicate and exclusion decisions to the user before export_chart."}

    def export_chart(self, review_id):
        if review_id not in self.reviews:
            raise SafetyError("The statistical review has expired. Run review_chart again.")
        reviewed = self.reviews[review_id]
        result = render(reviewed)
        baseline = None
        if reviewed.plan["exclude_rows"]:
            options = {**reviewed.plan, "exclude_rows": "", "exclude_reason": ""}
            baseline = render(review(reviewed.data, options))
        store = self.store()
        png = store.create_chart(result.chart.png)
        package = store.create_analysis(export_zip(result, baseline))
        return {"png": str(png), "result_zip": str(package), "note": result.chart.note,
                "source_sha256": reviewed.data.sha256, "svg": "Included in the ZIP", "original_modified": False}

    def save_draft(self, text, extension):
        path = self.new_file(text.encode("utf-8"), extension)
        return {"path": str(path), "executed": False, "original_modified": False}

    def start_image_monitor(self, folder=""):
        if self.monitor is not None:
            raise SafetyError("A watch is already active. Stop it before starting another.")
        if folder:
            # source_path is intentionally file-only. Validate directory separately.
            fragment = Path(folder)
            if fragment.is_absolute() or fragment.drive or ":" in folder or ".." in folder.replace("\\", "/").split("/"):
                raise SafetyError("The watch folder must be relative to the authorized source.")
            root = checked_root(self.source / fragment)
            if not root.is_relative_to(self.source):
                raise SafetyError("The watch folder is outside the authorized source.")
        else:
            root = self.source
        self.monitor = FolderMonitor(root)
        existing, _ = self.monitor.poll()
        self.monitor_stop = threading.Event()
        stop_event, monitor = self.monitor_stop, self.monitor
        def poll():
            while not stop_event.wait(2):
                try:
                    _, changes = monitor.poll()
                    with self.event_lock:
                        self.events.extend({"name": x.name, "bytes": x.size, "mtime_ns": x.mtime_ns} for x in changes)
                        self.events[:] = self.events[-200:]
                except (SafetyError, OSError):
                    pass
        self.monitor_thread = threading.Thread(target=poll, daemon=True)
        self.monitor_thread.start()
        return {"running": True, "baseline_files": len(existing), "poll_seconds": 2,
                "note": "Only new stable-image metadata is recorded. Ask image_monitor_events to read events; no autonomous model calls."}

    def image_monitor_events(self):
        with self.event_lock:
            events = list(self.events)
            self.events.clear()
        return {"running": self.monitor is not None, "events": events}

    def stop_monitor(self):
        self.monitor_stop.set()
        thread = getattr(self, "monitor_thread", None)
        if thread is not None:
            thread.join(timeout=5)
        self.monitor = None

    def view_image(self, file):
        root, relative, _ = self.locate(file)
        image, info = image_preview(root, relative, (1600, 1200))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return {"_image": output.getvalue(), **info}
