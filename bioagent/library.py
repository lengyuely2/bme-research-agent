"""Local parsing, bilingual lexical retrieval, and deterministic descriptive statistics."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import statistics
import threading
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .safety import SafetyError, checked_root, digest, read_source

SUPPORTED = {".pdf", ".txt", ".md", ".csv", ".tsv"}
MAX_FILES = 300
MAX_TOTAL_BYTES = 100 * 1024 * 1024
MAX_CHUNKS = 4000
MAX_DOCUMENT_CHARS = 240_000


def tokens(text: str) -> list[str]:
    text = text.lower()
    result = re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return result


def decode(data: bytes) -> str:
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("不是可识别的文本文件。")
    encodings = ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("无法识别文本编码，请另存为 UTF-8。")


@dataclass(frozen=True)
class Evidence:
    id: str
    source: str
    location: str
    text: str
    sha256: str
    table: bool = False

    def payload(self) -> dict:
        return {"id": self.id, "source": self.source, "location": self.location,
                "text": self.text, "source_sha256": self.sha256, "table": self.table}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    sha256: str
    size: int
    chunks: int


@dataclass(frozen=True)
class Match:
    evidence: Evidence
    score: float


class Cancelled(Exception):
    pass


def check_cancel(cancel: threading.Event | None) -> None:
    if cancel and cancel.is_set():
        raise Cancelled("已取消，未发起后续操作。")


def table_summary(text: str, delimiter: str = ",") -> str:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if not header or len(header) > 64 or any(len(x) > 128 for x in header):
        raise ValueError("表格需要标题行，最多 64 列，列名最多 128 字符。")
    if len(set(header)) != len(header) or any(not x.strip() for x in header):
        raise ValueError("表格列名不能为空或重复。")
    values: list[list[float]] = [[] for _ in header]
    missing, invalid = [0] * len(header), [0] * len(header)
    count = 0
    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            continue
        count += 1
        if count > 10_000:
            raise ValueError("表格超过 10,000 行，本版不进行截断统计。")
        if len(row) != len(header) or any(len(cell) > 4096 for cell in row):
            raise ValueError("表格行的列数不一致或单元格过长。")
        for i, cell in enumerate(row):
            cell = cell.strip()
            if not cell:
                missing[i] += 1
                continue
            try:
                number = float(cell)
                if not math.isfinite(number) or abs(number) > 1e100:
                    raise ValueError()
                values[i].append(number)
            except ValueError:
                invalid[i] += 1
    columns = []
    for i, name in enumerate(header):
        item = {"column": name, "numeric_n": len(values[i]),
                "missing_n": missing[i], "non_numeric_or_invalid_n": invalid[i]}
        if values[i]:
            nums = values[i]
            item.update(min=min(nums), max=max(nums), mean=statistics.mean(nums),
                        median=statistics.median(nums),
                        sample_sd=statistics.stdev(nums) if len(nums) > 1 else None)
        columns.append(item)
    return json.dumps({"kind": "local_descriptive_statistics", "rows": count,
                       "columns": columns,
                       "method": "仅对有限数值计算；空值、非数值和无效值分别计数；标准差为样本标准差。"
                                 "数字编码的 ID 或分组列可能没有统计意义，需人工判断。"
                                 "未进行分组比较、显著性检验或因果推断。未包含原始数据行。"},
                      ensure_ascii=False, indent=2, allow_nan=False)


def extract(data: bytes, suffix: str, cancel: threading.Event | None = None) -> list[tuple[str, str, bool]]:
    if suffix in {".csv", ".tsv"}:
        return [("描述性统计（全部数据行）", table_summary(decode(data), "\t" if suffix == ".tsv" else ","), True)]
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("本版不读取加密 PDF。")
        if len(reader.pages) > 300:
            raise ValueError("PDF 超过 300 页，请选取相关章节另存副本。")
        pages = []
        total = 0
        for i, page in enumerate(reader.pages, 1):
            check_cancel(cancel)
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_DOCUMENT_CHARS:
                raise ValueError("PDF 可提取文本超过限制，请选取相关章节另存副本。")
            if text.strip():
                pages.append((f"第 {i} 页", text, False))
        if not pages:
            raise ValueError("PDF 没有可提取文本；扫描件需先在本地 OCR。")
        return pages
    text = decode(data)
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ValueError("文本超过 240,000 字符，请拆分为多个资料文件。")
    return [("文本", text, False)]


def chunk_text(text: str, size: int = 1600, overlap: int = 160):
    for start in range(0, len(text), size - overlap):
        part = text[start:start + size].strip()
        if part:
            yield start, part
        if start + size >= len(text):
            break


class Library:
    def __init__(self, root: Path, sources: tuple[Source, ...], evidence: tuple[Evidence, ...], warnings: tuple[str, ...]):
        self.root, self.sources, self.evidence, self.warnings = root, sources, evidence, warnings
        self._counters = tuple(Counter(tokens(e.source + " " + e.text)) for e in evidence)
        self._df = Counter(t for counter in self._counters for t in counter)
        self._avg = sum(sum(c.values()) for c in self._counters) / max(1, len(evidence))

    @classmethod
    def load(cls, root: Path, cancel: threading.Event | None = None) -> Library:
        root = checked_root(root)
        sources, evidence, warnings = [], [], []
        total_bytes, candidates = 0, 0
        for directory, dirs, files in os.walk(root, followlinks=False):
            check_cancel(cancel)
            safe_dirs = []
            for name in sorted(dirs):
                child = Path(directory) / name
                if name.startswith(".") or name in {"node_modules", "__pycache__", "output"}:
                    continue
                from .safety import _is_link
                if _is_link(child):
                    warnings.append(f"跳过链接目录：{child.relative_to(root)}")
                else:
                    safe_dirs.append(name)
            dirs[:] = safe_dirs
            for name in sorted(files):
                check_cancel(cancel)
                suffix = Path(name).suffix.lower()
                if name.startswith(".") or suffix not in SUPPORTED:
                    continue
                candidates += 1
                if candidates > MAX_FILES:
                    warnings.append(f"达到 {MAX_FILES} 个候选文件上限，未继续读取。")
                    return cls(root, tuple(sources), tuple(evidence), tuple(warnings))
                relative = str((Path(directory) / name).relative_to(root))
                try:
                    remaining = MAX_TOTAL_BYTES - total_bytes
                    if remaining <= 0:
                        warnings.append("达到 100 MiB 总读取上限，未继续读取。")
                        return cls(root, tuple(sources), tuple(evidence), tuple(warnings))
                    data = read_source(root, relative, min(20 * 1024 * 1024, remaining))
                    total_bytes += len(data)
                    pages = extract(data, suffix, cancel)
                    sid = f"S{len(sources) + 1:03d}"
                    sha = digest(data)
                    parts = []
                    for location, text, is_table in pages:
                        # A whole statistical table is one evidence item, never a partial JSON fragment.
                        chunks = [(0, text)] if is_table else chunk_text(text)
                        for offset, part in chunks:
                            if len(evidence) + len(parts) >= MAX_CHUNKS:
                                raise ValueError("超过 4,000 个片段上限，该文件未加入索引。")
                            eid = f"{sid}-C{len(parts) + 1:04d}"
                            loc = location if is_table else f"{location} · 字符 {offset + 1}–{offset + len(part)}"
                            parts.append(Evidence(eid, relative, loc, part, sha, is_table))
                    if not parts:
                        raise ValueError("文件为空，没有可索引内容。")
                    evidence.extend(parts)
                    sources.append(Source(sid, relative, sha, len(data), len(parts)))
                except Cancelled:
                    raise
                except (ValueError, OSError, ImportError) as exc:
                    # Do not persist parser exception strings or document content.
                    reason = str(exc) if isinstance(exc, (ValueError, SafetyError)) else "无法读取或解析该文件。"
                    warnings.append(f"{relative}：{reason[:180]}")
                except Exception:
                    warnings.append(f"{relative}：文件解析失败，已跳过。")
        return cls(root, tuple(sources), tuple(evidence), tuple(warnings))

    def search(self, query: str, limit: int = 12) -> tuple[Match, ...]:
        terms = set(tokens(query))
        if not terms:
            return ()
        matches = []
        for item, counter in zip(self.evidence, self._counters):
            length = sum(counter.values())
            score = 0.0
            for term in terms:
                freq = counter.get(term, 0)
                if freq:
                    idf = math.log(1 + (len(self.evidence) - self._df[term] + .5) / (self._df[term] + .5))
                    score += idf * freq * 2.2 / (freq + 1.2 * (.25 + .75 * length / max(1, self._avg)))
            if score > 0:
                matches.append(Match(item, score))
        return tuple(sorted(matches, key=lambda m: (-m.score, m.evidence.id))[:limit])
