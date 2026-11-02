"""Immutable, bounded attachments selected by the user. Original files are never changed."""

from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .analysis import Dataset
from .library import Evidence, chunk_text, decode, table_summary, tokens, check_cancel
from .safety import SafetyError, checked_root, read_source, digest

SUPPORTED = {".pdf", ".txt", ".md", ".csv", ".tsv", ".xlsx", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
MAX_SELECTED = 4
MAX_SELECTED_MEDIA = 24 * 1024 * 1024
MAX_RESIDENT = 12
MAX_RESIDENT_BYTES = 60 * 1024 * 1024


def image_bytes(raw: bytes, maximum=2048):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(raw)) as image:
        if image.width * image.height > 20_000_000 or min(image.size) < 1:
            raise SafetyError("图片超过 2,000 万像素限制。")
        frames, original = getattr(image, "n_frames", 1), image.size
        image.seek(0)
        image = ImageOps.exif_transpose(image)
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, "white")
        image = Image.alpha_composite(background, rgba).convert("RGB")
        image.thumbnail((maximum, maximum))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue(), original, image.size, frames


def data_url(png: bytes):
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


@dataclass(frozen=True)
class Attachment:
    id: str
    source_id: str
    root: Path
    name: str
    raw: bytes
    sha256: str
    kind: str
    evidence: tuple[Evidence, ...]
    pages: int = 1
    image: bytes = b""
    notes: tuple[str, ...] = ()
    sheets: tuple[str, ...] = ()
    sheet: str = ""
    dataset: Dataset | None = None

    @classmethod
    def load(cls, path: Path, identifier: str, source_id: str, cancel=None):
        root = checked_root(path.parent)
        if path.suffix.lower() not in SUPPORTED:
            raise SafetyError("附件支持 PDF、TXT、MD、CSV、TSV、XLSX 和常见图片。")
        raw = read_source(root, path.name)
        return cls.parse(root, path.name, raw, identifier, source_id, cancel=cancel)

    @classmethod
    def parse(cls, root, name, raw, identifier, source_id, sheet=None, cancel=None):
        check_cancel(cancel)
        suffix, sha = Path(name).suffix.lower(), digest(raw)
        evidence, notes, pages, kind, image, sheets, chosen, dataset = [], [], 1, "text", b"", (), "", None
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw), strict=False)
            if reader.is_encrypted:
                raise SafetyError("本版不读取加密 PDF。")
            pages, kind = len(reader.pages), "pdf"
            if not 1 <= pages <= 100:
                raise SafetyError("单个 PDF 支持 1–100 页，请把相关章节另存为副本。")
            total = 0
            for number, page in enumerate(reader.pages, 1):
                check_cancel(cancel)
                text = (page.extract_text() or "")[:12000]
                if total + len(text) > 240000:
                    notes.append("本地文字索引已达到上限；发送时仍包含完整 PDF。")
                    break
                total += len(text)
                for offset, part in chunk_text(text):
                    evidence.append(Evidence(f"{source_id}-C{len(evidence)+1:04d}", name,
                        f"第 {number} 页 · 字符 {offset+1}–{offset+len(part)}", part, sha))
            if not evidence:
                notes.append("没有可提取文字；可由支持视觉的模型读取扫描页面。")
        elif suffix in {".csv", ".tsv", ".xlsx"}:
            kind = "table"
            if suffix == ".xlsx":
                from .tables import spreadsheet_text
                text, sheets, chosen, extra = spreadsheet_text(raw, sheet)
                notes.extend(extra)
            else:
                text = decode(raw)
            delimiter = "\t" if suffix == ".tsv" else ","
            summary = table_summary(text, delimiter)
            description = (f"工作表：{chosen}\n" if chosen else "") + "\n".join(notes) + "\n" + summary
            evidence.append(Evidence(f"{source_id}-C0001", name,
                f"工作表 {chosen} · 全表统计" if chosen else "全表描述统计", description, sha, True))
            if any(column["numeric_n"] for column in json.loads(summary)["columns"]):
                converted_name = name + (".tsv" if delimiter == "\t" else ".csv")
                parsed = Dataset.from_bytes(root, converted_name, text.encode("utf-8"))
                dataset = replace(parsed, name=name, sha256=sha, summary=description, sheet=chosen, warnings=tuple(notes))
        elif suffix in {".txt", ".md"}:
            text = decode(raw)
            if len(text) > 240000:
                raise SafetyError("文本超过 240,000 字符，请拆分后添加。")
            for offset, part in chunk_text(text):
                evidence.append(Evidence(f"{source_id}-C{len(evidence)+1:04d}", name,
                    f"字符 {offset+1}–{offset+len(part)}", part, sha))
            if not evidence:
                raise SafetyError("文本附件为空。")
        else:
            kind = "image"
            image, original, sent, frames = image_bytes(raw)
            notes.append(f"原图 {original[0]}×{original[1]}；发送视觉副本 {sent[0]}×{sent[1]}，不用于像素级定量。")
            if frames > 1:
                notes.append(f"共 {frames} 帧，仅使用首帧。")
            evidence.append(Evidence(f"{source_id}-C0001", name, "用户附图 · 首帧",
                "用户提供的图片，需结合本次附带的图像内容分析；不能把此元数据当作图像观察。", sha))
        return cls(identifier, source_id, root, name, raw, sha, kind, tuple(evidence), pages,
                   image, tuple(notes), tuple(sheets), chosen, dataset)

    def metadata(self):
        transport = {"pdf":"PDF 全文与页面图像", "image":"图像视觉副本", "table":"当前工作表统计，不含原始数据行", "text":"按问题检索的文字片段"}[self.kind]
        return {"id": self.id, "source_id": self.source_id, "name": self.name, "kind": self.kind,
                "bytes": len(self.raw), "sha256": self.sha256, "pages": self.pages,
                "notes": self.notes, "sheets": self.sheets, "sheet": self.sheet,
                "can_plot": self.dataset is not None, "transmission": transport}

    def manifest(self):
        return {key:value for key,value in self.metadata().items() if key not in {"id", "sheets"}}

    def content(self):
        if self.kind == "pdf":
            return {"type":"input_file", "filename":self.name,
                    "file_data":"data:application/pdf;base64," + base64.b64encode(self.raw).decode("ascii")}
        if self.kind == "image":
            return {"type":"input_image", "image_url":data_url(self.image), "detail":"high"}
        return None

    def select_evidence(self, question: str, limit=4):
        query = set(tokens(question))
        ranked = sorted(enumerate(self.evidence), key=lambda item:(
            -len(query.intersection(tokens(item[1].text))), item[0]))
        return tuple(item for _,item in ranked[:limit])

    def citation_ids(self):
        return {f"{self.source_id}-P{page:03d}" for page in range(1, self.pages+1)} if self.kind == "pdf" else set()

    def preview(self, page=1):
        if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= self.pages:
            raise SafetyError("页码超出附件范围。")
        if self.kind == "pdf":
            import pypdfium2 as pdfium
            document = pdfium.PdfDocument(self.raw)
            try:
                pdf_page = document[page-1]
                try:
                    width, height = pdf_page.get_size()
                    if not 0 < min(width,height) <= max(width,height) < 100000:
                        raise SafetyError("PDF 页面尺寸异常。")
                    bitmap = pdf_page.render(scale=min(2, 1500/max(width,height)))
                    try:
                        output = io.BytesIO()
                        bitmap.to_pil().save(output, format="PNG")
                        image = data_url(output.getvalue())
                    finally:
                        bitmap.close()
                finally:
                    pdf_page.close()
            finally:
                document.close()
            text = "\n\n".join(e.text for e in self.evidence if e.location.startswith(f"第 {page} 页 ·"))
            return {"name":self.name, "page":page, "pages":self.pages, "image":image, "text":text}
        return {"name":self.name, "page":1, "pages":1, "image":data_url(self.image) if self.image else "",
                "text":"\n\n".join(e.text for e in self.evidence)[:50000]}


def validate_selection(items):
    if len(items) > MAX_SELECTED:
        raise SafetyError("每次对话最多关联 4 个附件。")
    media = sum(len(item.raw) if item.kind == "pdf" else len(item.image) for item in items)
    if media > MAX_SELECTED_MEDIA:
        raise SafetyError("本次 PDF 与图片合计超过 24 MiB，请减少附件。")
