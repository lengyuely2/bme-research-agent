"""Narrow stdio service for the isolated desktop renderer. No listening network port."""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from .agent import Packet, ResearchAgent, cloud_report, local_report, openai_client, INSTRUCTIONS, tools_for
from .analysis import Dataset, render_chart, CHART_TYPES
from .connection import normalize_key, discover_models, error_details
from .library import Library, Evidence, Cancelled
from .monitor import FolderMonitor, image_preview
from .safety import ReportStore, SafetyError, checked_root
from .billing import UsageLedger
from .attachments import Attachment, MAX_SELECTED, MAX_RESIDENT, MAX_RESIDENT_BYTES, validate_selection


@dataclass(frozen=True)
class Prepared:
    packet: Packet
    connection_version: int
    model: str


def png_data(image) -> str:
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class DesktopService:
    def __init__(self, emit=lambda _: None):
        self.emit = emit
        self.library = None
        self.dataset = None
        self.charts = []
        self.chart_roots: set[Path] = set()
        self.report_roots: set[Path] = set()
        self.monitor = None
        self.monitor_stop = threading.Event()
        self.cancel = threading.Event()
        self.api_key = ""
        self.billing = UsageLedger()
        self.models: tuple[str, ...] = ()
        self.connection_version = 0
        self.prepared: dict[str, Prepared] = {}
        self.report = ""
        self.reports: dict[str, str] = {}
        self.last_error = None
        self.report_packet = None
        self.attachments: dict[str, Attachment] = {}
        self.attachment_counter = 0
        self.report_packets: dict[str, Packet] = {}
        self.workflow_review = None
        self.workflow_runs = {}
        self.workflow_baselines = {}
        self.output = Path.home() / "BMEWorkbenchReports"
        self.sample_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "samples"
        self.operation_lock = threading.Lock()

    def store(self, extra=None):
        roots = [r for r in (self.library.root if self.library else None,
                            self.dataset.root if self.dataset else None,
                            self.monitor.root if self.monitor else None, extra) if r is not None]
        roots.extend(self.chart_roots | self.report_roots)
        roots.extend(item.root for item in self.attachments.values())
        stores = [ReportStore(self.output, root) for root in roots]
        return stores[0] if stores else ReportStore(self.output, None)

    def dispatch(self, operation: str, params: dict):
        allowed = {"status", "connect", "test_model", "load_library", "demo_library", "search",
                   "prepare", "approve", "local_report", "load_data", "demo_data", "plot", "save_chart",
                   "save_report", "set_output", "monitor_start", "monitor_stop", "preview_image", "cancel", "sandbox_config", "diagnostics", "billing", "set_balance",
                   "attach_files", "remove_attachment", "attachment_preview", "attachment_sheet", "attachment_data", "view_source", "demo_attachments",
                   "workflow_profile", "workflow_suggest", "workflow_review", "workflow_render", "workflow_export", "demo_workflow", "workflow_spikes"}
        if operation not in allowed or not isinstance(params, dict):
            raise SafetyError("拒绝未授权的操作。")
        if operation == "cancel":
            self.cancel.set()
            return {"cancelled": True}
        if operation == "monitor_stop":
            self.monitor_stop.set()
            return {"running": False}
        with self.operation_lock:
            self.cancel = threading.Event()
            return getattr(self, "op_" + operation)(params)

    def op_status(self, _):
        return {"version": "0.5.1", "connected": bool(self.models and self.api_key), "models": self.models,
                "output": str(self.output), "chart_types": CHART_TYPES,
                "provider": "https://api.openai.com/v1"}

    def op_diagnostics(self, _):
        from .selfcheck import run_checks
        return {"local_check": run_checks(), "last_error": self.last_error,
                "connection": {"key_loaded": bool(self.api_key), "models_loaded": len(self.models)},
                "note": "不包含密钥、请求正文、论文、资料路径或 SDK 错误原文。自检使用离线模拟响应，不验证账户余额。"}

    def op_billing(self, _):
        return self.billing.snapshot()

    def op_set_balance(self, params):
        if not self.api_key or not self.models:
            raise SafetyError("请先连接 API 账户，再记录该账户的官方余额。")
        return self.billing.confirm_balance(params.get("amount"))

    def op_connect(self, params):
        # Changing a key invalidates all previously approved model IDs and request previews.
        self.api_key, self.models = "", ()
        self.billing = UsageLedger()
        self.connection_version += 1
        self.prepared.clear()
        key = normalize_key(params.get("api_key", ""))
        with openai_client(key) as client:
            models = discover_models(client)
        if not models:
            raise SafetyError("密钥验证成功，但没有找到可选择的文本模型。请检查项目模型权限。")
        self.api_key, self.models = key, models
        return {"connected": True, "models": models, "provider": "OpenAI 官方 API",
                "note": "模型列表已从本账户加载。列表可见不等于 Responses 权限已验证，可再发送一条测试请求。"}

    def require_model(self, model):
        if not self.api_key or not self.models:
            raise SafetyError("请先在设置中填写 API Key 并点击“加载可用模型”。")
        if model not in self.models:
            raise SafetyError("请选择本账户模型列表中的名称；如果账户权限有变化，请重新加载。")

    def op_test_model(self, params):
        model = params.get("model", "")
        self.require_model(model)
        with openai_client(self.api_key) as client:
            self.billing.request_started()
            response = client.responses.create(model=model, input="Reply with OK.", store=False, max_output_tokens=512)
            self.billing.record_usage(getattr(response, "usage", None))
        return {"ok": True, "completed": response.status == "completed",
                "message": "测试请求成功，模型可以接收 Responses 请求。" if response.status == "completed" else
                           "模型已接收请求，但小额度测试未完成输出；正式回答会使用更大的输出预算。"}

    def op_load_library(self, params):
        root = checked_root(Path(params["path"]))
        self.store(root)
        self.library = Library.load(root, self.cancel)
        self.prepared.clear()
        return {"name": root.name, "path": str(root), "files": [s.name for s in self.library.sources],
                "chunks": len(self.library.evidence), "warnings": self.library.warnings}

    def op_demo_library(self, _):
        return self.op_load_library({"path": str(self.sample_dir)})

    def op_search(self, params):
        if not self.library:
            raise SafetyError("请先导入一个资料文件夹。")
        query = params.get("query", "")
        items = self.library.search(query) if query.strip() else ()
        return {"items": [m.evidence.payload() for m in items], "count": len(items)}

    def op_attach_files(self, params):
        paths = params.get("paths")
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_SELECTED or any(not isinstance(p,str) for p in paths):
            raise SafetyError("每次请选择 1–4 个本地附件。")
        items, warnings = [], []
        for value in paths:
            path = Path(value)
            try:
                if len(self.attachments)+len(items) >= MAX_RESIDENT or self.attachment_counter >= 399:
                    raise SafetyError("附件缓存已满，请移除不需要的附件后重试。")
                self.store(path.parent)
                identifier = uuid.uuid4().hex
                item = Attachment.load(path, identifier, f"S{501+self.attachment_counter:03d}", self.cancel)
                if sum(len(a.raw) for a in [*self.attachments.values(),*items,item]) > MAX_RESIDENT_BYTES:
                    raise SafetyError("附件缓存合计超过 60 MiB，请先移除不需要的附件。")
                validate_selection([*items, item])
                self.attachment_counter += 1
                items.append(item)
            except Cancelled:
                raise
            except Exception as exc:
                warnings.append(path.name + "：" + (str(exc) if isinstance(exc,SafetyError) else "文件解析失败，未添加。"))
        self.attachments.update({item.id:item for item in items})
        self.prepared.clear()
        return {"items":[item.metadata() for item in items], "warnings":warnings}

    def attachment(self, identifier):
        if not isinstance(identifier,str) or identifier not in self.attachments:
            raise SafetyError("附件不在当前缓存中，请重新选择文件。")
        return self.attachments[identifier]

    def op_remove_attachment(self, params):
        item = self.attachment(params.get("id"))
        del self.attachments[item.id]
        self.prepared.clear()
        return {"removed":item.id}

    def op_attachment_preview(self, params):
        return self.attachment(params.get("id")).preview(params.get("page",1))

    def op_attachment_sheet(self, params):
        item = self.attachment(params.get("id"))
        if not item.sheets or params.get("sheet") not in item.sheets:
            raise SafetyError("请选择该 Excel 附件中的可见工作表。")
        changed = Attachment.parse(item.root,item.name,item.raw,item.id,item.source_id,params["sheet"],self.cancel)
        self.attachments[item.id] = changed
        self.prepared.clear()
        return changed.metadata()

    def op_attachment_data(self, params):
        item = self.attachment(params.get("id"))
        if item.dataset is None:
            raise SafetyError("附件中没有可用于绘图的数值表格。")
        self.dataset, self.charts = item.dataset, []
        self.workflow_review = None
        return self.dataset_payload()

    def op_demo_attachments(self, _):
        return self.op_attach_files({"paths":[str(self.sample_dir/"paper_demo.pdf"),str(self.sample_dir/"biosensor_demo.csv")]})

    def op_view_source(self, params):
        import re
        packet = self.report_packets.get(params.get("report_id"))
        citation = params.get("citation")
        if packet is None or not isinstance(citation,str):
            raise SafetyError("没有可核对的报告来源。")
        for item in packet.attachments:
            match = re.fullmatch(re.escape(item.source_id)+r"-P(\d{3})",citation)
            if match and item.kind == "pdf":
                return {**item.preview(int(match[1])), "citation":citation}
        evidence = next((e for e in packet.evidence if e.id == citation),None)
        if evidence is None:
            raise SafetyError("该引用不属于这次回答的来源，不能打开。")
        item = next((a for a in packet.attachments if citation.startswith(a.source_id+"-")),None)
        if item and item.kind in {"pdf","image"}:
            page = re.search(r"第 (\d+) 页",evidence.location)
            return {**item.preview(int(page[1]) if page else 1), "citation":citation}
        return {"name":evidence.source, "page":1,"pages":1,"image":"", "text":evidence.text,
                "location":evidence.location,"citation":citation}

    def make_packet(self, params):
        question = params.get("question", "")
        mode = params.get("mode", "auto")
        if mode not in {"auto", "evidence", "chat"}:
            raise SafetyError("不支持的问答模式。")
        evidence = ()
        dataset = None
        identifiers = params.get("attachment_ids",[])
        if not isinstance(identifiers,list) or len(identifiers)>MAX_SELECTED or any(not isinstance(x,str) for x in identifiers) or len(set(identifiers)) != len(identifiers):
            raise SafetyError("附件选择无效，每次最多关联 4 个不同附件。")
        attached = tuple(self.attachment(identifier) for identifier in identifiers)
        validate_selection(attached)
        if mode == "chat" and attached:
            raise SafetyError("自由问答不读取附件。请移除附件，或切换“自动判断 / 结合资料”。")
        if mode != "chat":
            if attached:
                limit = max(1, 8//len(attached))
                evidence = tuple(e for a in attached for e in a.select_evidence(question,limit))[:8]
                dataset = next((a.dataset for a in attached if a.dataset is not None),None)
            if params.get("use_dataset"):
                if not self.dataset:
                    raise SafetyError("请先导入实验数据。")
                dataset = self.dataset
                if not any(a.dataset and a.sha256 == dataset.sha256 for a in attached):
                    evidence = (*evidence[:7],Evidence("S900-C0001", dataset.name, "本地描述统计", dataset.summary, dataset.sha256, True))
            elif self.library and not attached:
                ids = params.get("evidence_ids", [])
                if ids:
                    approved = {e.id: e for e in self.library.evidence}
                    if not isinstance(ids, list) or not all(i in approved for i in ids):
                        raise SafetyError("证据标识不在当前资料库内。")
                    evidence = tuple(approved[i] for i in ids)
                else:
                    evidence = tuple(m.evidence for m in self.library.search(question, 6))
        if not evidence and not attached and mode == "evidence":
            raise SafetyError("没有找到相关证据。请调整检索词、选择证据，或切换自由问答。")
        history = params.get("history", [])
        if not isinstance(history, list) or len(history) > 8:
            raise SafetyError("对话上下文超过限制。")
        turns = []
        for item in history:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"} or not isinstance(item.get("text"), str):
                raise SafetyError("对话上下文格式不正确。")
            turns.append((item["role"], item["text"][:4000]))
        base = Packet(question, evidence, dataset, "evidence" if evidence or attached else "chat", attachments=attached)
        from .agent import MAX_PACKET_CHARS
        while turns and len(base.serialized()) + len(json.dumps(turns, ensure_ascii=False)) + 700 > MAX_PACKET_CHARS:
            turns.pop(0)
        return Packet(question, evidence, dataset, base.mode, tuple(turns),attached)

    def op_prepare(self, params):
        model = params.get("model", "")
        self.require_model(model)
        packet = self.make_packet(params)
        token = uuid.uuid4().hex
        if len(self.prepared) >= 8:
            self.prepared.clear()
        self.prepared[token] = Prepared(packet, self.connection_version, model)
        return {"token": token, "preview": packet.serialized(), "model": model,
                "instructions": INSTRUCTIONS, "tools": tools_for(packet),
                "provider": "https://api.openai.com/v1", "evidence_count": len(packet.evidence)}

    def op_approve(self, params):
        item = self.prepared.pop(params.get("token", ""), None)
        if item is None or item.connection_version != self.connection_version:
            raise SafetyError("预览已经失效，请重新预览当前问题。")
        self.require_model(item.model)
        packet = item.packet
        store = self.store(packet.dataset.root if packet.dataset else None)
        with openai_client(self.api_key) as client:
            result = ResearchAgent(client).run(packet, item.model, self.cancel,
                lambda message: self.emit({"event": "progress", "message": message}),
                lambda delta: self.emit({"event": "text", "delta": delta}),
                on_request=self.billing.request_started, on_usage=self.billing.record_usage)
        self.report_packet = packet
        self.report = cloud_report(packet, result, item.model)
        report_id = uuid.uuid4().hex
        self.reports[report_id] = self.report
        self.report_packets[report_id] = packet
        self.report_roots.update(a.root for a in packet.attachments)
        if packet.evidence and self.library:
            self.report_roots.add(self.library.root)
        if packet.dataset:
            self.report_roots.add(packet.dataset.root)
            self.chart_roots.add(packet.dataset.root)
        self.charts = list(result.charts)
        audit_warning = ""
        try:
            store.audit("cloud_report", evidence_ids=tuple(e.id for e in packet.evidence),
                        tool_names=result.calls, packet_hash=packet.sha256)
        except (OSError, SafetyError):
            audit_warning = "回答已生成，但操作记录未写入，请检查结果目录权限。"
        return {"answer": result.answer, "report": self.report, "report_id": report_id, "citation_issues": result.citation_issues,
                "tools": result.calls, "charts": [self.chart_payload(c) for c in self.charts],
                "tokens": {"input": result.input_tokens, "output": result.output_tokens}, "warning": audit_warning,
                "sources":[{"id":e.id,"source":e.source,"location":e.location} for e in packet.evidence],
                "attachments":[a.metadata() for a in packet.attachments]}

    def op_local_report(self, params):
        packet = self.make_packet({**params, "mode": "evidence"})
        self.report_packet = packet
        if packet.dataset:
            self.report_roots.add(packet.dataset.root)
        self.report = local_report(packet)
        if self.library:
            self.report_roots.add(self.library.root)
        report_id = uuid.uuid4().hex
        self.reports[report_id] = self.report
        self.report_packets[report_id] = packet
        self.report_roots.update(a.root for a in packet.attachments)
        return {"report": self.report, "answer": self.report, "report_id": report_id}

    def op_load_data(self, params):
        path = Path(params["path"])
        self.store(path.parent)
        self.dataset = Dataset.load(path,params.get("sheet"))
        self.charts = []
        return self.dataset_payload()

    def dataset_payload(self):
        self.workflow_review = None
        return {"name": self.dataset.name, "rows": len(self.dataset.rows), "headers": self.dataset.headers,
                "numeric": self.dataset.numeric, "summary": self.dataset.summary,
                "sheet":self.dataset.sheet,"warnings":self.dataset.warnings}

    def op_demo_data(self, _):
        return self.op_load_data({"path": str(self.sample_dir / "EMG_demo.csv")})

    def require_dataset(self):
        if self.dataset is None:
            raise SafetyError("请先导入数据或载入实验演示。")
        return self.dataset

    def op_demo_workflow(self, params):
        if params.get("kind") not in {"time", "group"}:
            raise SafetyError("请选择时间曲线或分组演示。")
        name="kinetics_demo.csv" if params["kind"]=="time" else "biosensor_demo.csv"
        return self.op_load_data({"path":str(self.sample_dir/name)})

    def op_workflow_profile(self, _):
        from .workflow import profile, default_plan
        data=self.require_dataset()
        return {"profile":profile(data),"plan":default_plan(data),"headers":data.headers,
                "preview":[{"record":i+1,"values":[v[:160] for v in row]} for i,row in enumerate(data.rows[:30])],
                "preview_note":"仅本地预览前 30 条记录；单元格超过 160 字会截断。"}

    def op_workflow_suggest(self, params):
        from .workflow import ai_suggest
        data=self.require_dataset()
        model=params.get("model","");self.require_model(model)
        with openai_client(self.api_key) as client:
            return ai_suggest(client,model,data,params.get("goal",""),self.billing,self.cancel)

    def op_workflow_review(self, params):
        from .workflow import review
        reviewed=review(self.require_dataset(),params)
        token=uuid.uuid4().hex
        self.workflow_review=(token,reviewed)
        self.chart_roots.add(reviewed.data.root)
        return {"token":token,**reviewed.public()}

    def op_workflow_spikes(self, params):
        from .workflow import detect_spikes
        return detect_spikes(self.require_dataset(),params)

    def op_workflow_render(self, params):
        from .workflow import render, review
        if not self.workflow_review or params.get("token")!=self.workflow_review[0]:
            raise SafetyError("筛选预览已失效，请重新预览后生成图表。")
        _,reviewed=self.workflow_review
        result=render(reviewed)
        baseline=None
        if reviewed.plan['exclude_rows']:
            options={**reviewed.plan,'exclude_rows':'','exclude_reason':''}
            for key in ('x_min','x_max','y_min','y_max'):
                if options[key] is None:options[key]=''
            baseline=render(review(reviewed.data,options))
        identifier=uuid.uuid4().hex
        self.workflow_runs[identifier]=result
        if baseline is not None:self.workflow_baselines[identifier]=baseline
        while len(self.workflow_runs)>4:
            removed=next(iter(self.workflow_runs));del self.workflow_runs[removed]
            self.workflow_baselines.pop(removed,None)
        self.charts=[baseline.chart,result.chart] if baseline is not None else [result.chart]
        return {"run_id":identifier,**self.chart_payload(result.chart),"summary":reviewed.summary[:150],
                "note":result.chart.note,"source_sha256":reviewed.data.sha256,
                "before":self.chart_payload(baseline.chart) if baseline is not None else None}

    def op_workflow_export(self, params):
        from .workflow import export_zip
        result=self.workflow_runs.get(params.get("run_id"))
        if result is None:
            raise SafetyError("结果不在当前缓存中，请重新生成图表（最多保留最近 4 次）。")
        return {"path":str(self.store(result.review.data.root).create_analysis(export_zip(result,self.workflow_baselines.get(params.get('run_id')))))}

    @staticmethod
    def chart_payload(chart):
        return {"image": "data:image/png;base64," + base64.b64encode(chart.png).decode("ascii"),
                "note": chart.note, "used": chart.used, "excluded": chart.excluded}

    def op_plot(self, params):
        if self.dataset is None:
            raise SafetyError("请先导入 CSV / TSV 数据。")
        chart = render_chart(self.dataset, params["kind"], params["x"], params["y"])
        self.charts = [chart]
        self.chart_roots.add(self.dataset.root)
        return self.chart_payload(chart)

    def op_save_chart(self, params):
        index = params.get("index", 0)
        if not isinstance(index, int) or not 0 <= index < len(self.charts):
            raise SafetyError("请先生成图表。")
        return {"path": str(self.store().create_chart(self.charts[index].png))}

    def op_save_report(self, params):
        report = self.reports.get(params.get("report_id", ""))
        if not report:
            raise SafetyError("还没有可保存的报告。")
        return {"path": str(self.store().create(report))}

    def op_set_output(self, params):
        output = Path(params["path"])
        previous = self.output
        self.output = output
        try:
            self.store()
        except Exception:
            self.output = previous
            raise
        return {"path": str(self.output)}

    def op_sandbox_config(self, params):
        from .sandbox import generate
        source = self.library.root if self.library else (self.dataset.root if self.dataset else
                 self.monitor.root if self.monitor else None)
        if source is None:
            raise SafetyError("请先连接需要以只读方式挂载的资料、数据或图片目录。")
        self.store()
        return {"path": str(generate(Path(params["binary"]), source, self.output,
                                     online=bool(params.get("online", False))))}

    def op_monitor_start(self, params):
        root = checked_root(Path(params["path"]))
        self.store(root)
        self.monitor_stop.set()
        monitor = FolderMonitor(root)
        self.monitor = monitor
        stopped = threading.Event()
        self.monitor_stop = stopped
        files, _ = monitor.poll()
        def poll():
            while not stopped.wait(2):
                try:
                    items, changes = monitor.poll()
                    self.emit({"event": "monitor", "files": [x.name for x in items], "new": [x.name for x in changes]})
                    if changes:
                        image, info = image_preview(root, changes[0].name)
                        self.emit({"event": "image", "name": changes[0].name, "image": png_data(image), "info": info})
                except Exception:
                    self.emit({"event": "monitor_warning", "message": "图片可能仍在写入，或目录无法读取；可以稍后重试。"})
        threading.Thread(target=poll, daemon=True).start()
        return {"path": str(root), "files": [x.name for x in files], "running": True}

    def op_preview_image(self, params):
        if not self.monitor:
            raise SafetyError("请先选择图片监控目录。")
        name = params["name"]
        image, info = image_preview(self.monitor.root, name)
        return {"name": name, "image": png_data(image), "info": info}


def main():
    # Initialize native numerical extensions on the main thread before the stdio reader
    # blocks. Loading NumPy DLLs for the first time inside a worker can deadlock on Windows.
    import numpy
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    import pypdfium2  # Load PDFium's native library before the main thread blocks on stdin.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
        sys.stdin.reconfigure(encoding="utf-8")
    lock = threading.Lock()
    def emit(value):
        with lock:
            sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    service = DesktopService(emit)
    def handle(message):
        identifier = message.get("id")
        try:
            data = service.dispatch(message.get("operation", ""), message.get("params", {}))
            emit({"id": identifier, "ok": True, "data": data})
        except Cancelled:
            emit({"id": identifier, "ok": False, "error": {"kind": "cancelled", "message": "已停止后续操作，已发送的数据不能撤回。"}})
        except Exception as exc:
            details = error_details(exc)
            operation = message.get("operation", "")
            known = {"connect", "test_model", "prepare", "approve", "load_library", "load_data",
                     "plot", "save_chart", "save_report", "monitor_start", "preview_image", "diagnostics"}
            service.last_error = {"operation": operation if operation in known else "local_operation", **details}
            emit({"id": identifier, "ok": False, "error": details})
    for line in sys.stdin:
        if len(line) > 100_000:
            continue
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                continue
        except ValueError:
            continue
        threading.Thread(target=handle, args=(value,), daemon=True).start()
    service.monitor_stop.set()
    service.cancel.set()
    service.api_key = ""


if __name__ == "__main__":
    main()
