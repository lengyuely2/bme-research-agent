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
        raise ValueError("Not a recognized text file.")
    encodings = ["utf-16"] if data.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "gb18030"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("Unrecognized text encoding. Save a UTF-8 copy.")


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
        raise Cancelled("Cancelled; no further operation was started.")


def table_summary(text: str, delimiter: str = ",") -> str:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader, None)
    if not header or len(header) > 64 or any(len(x) > 128 for x in header):
        raise ValueError("A header is required: up to 64 columns and 128 characters per name.")
    if len(set(header)) != len(header) or any(not x.strip() for x in header):
        raise ValueError("Table headers must be non-empty and unique.")
    values: list[list[float]] = [[] for _ in header]
    missing, invalid = [0] * len(header), [0] * len(header)
    count = 0
    for row in reader:
        if not row or all(not cell.strip() for cell in row):
            continue
        count += 1
        if count > 10_000:
            raise ValueError("The table exceeds 10,000 records. No truncated statistics were produced.")
        if len(row) != len(header) or any(len(cell) > 4096 for cell in row):
            raise ValueError("Inconsistent column counts or an oversized cell.")
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
                       "method": "Finite numbers only; missing and invalid values are counted separately. SD is sample SD. "
                                 "Numeric IDs or group codes may have no statistical meaning; review manually. "
                                 "No group comparisons, significance tests, causal inference, or raw data rows are included."},
                      ensure_ascii=False, indent=2, allow_nan=False)


def extract(data: bytes, suffix: str, cancel: threading.Event | None = None) -> list[tuple[str, str, bool]]:
    if suffix in {".csv", ".tsv"}:
        return [("Descriptive statistics (all data records)", table_summary(decode(data), "\t" if suffix == ".tsv" else ","), True)]
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported in this build.")
        if len(reader.pages) > 300:
            raise ValueError("The PDF exceeds 300 pages. Save the relevant sections separately.")
        pages = []
        total = 0
        for i, page in enumerate(reader.pages, 1):
            check_cancel(cancel)
            text = page.extract_text() or ""
            total += len(text)
            if total > MAX_DOCUMENT_CHARS:
                raise ValueError("Extracted PDF text exceeds the limit. Save the relevant sections separately.")
            if text.strip():
                pages.append((f"Page {i}", text, False))
        if not pages:
            raise ValueError("The PDF has no extractable text. Scans require local OCR first.")
        return pages
    text = decode(data)
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ValueError("Text exceeds 240,000 characters. Split it into smaller source files.")
    return [("Text", text, False)]


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
                    warnings.append(f"Skipped linked directory: {child.relative_to(root)}")
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
                    warnings.append(f"Reached {MAX_FILES} candidate files; no further files were read.")
                    return cls(root, tuple(sources), tuple(evidence), tuple(warnings))
                relative = str((Path(directory) / name).relative_to(root))
                try:
                    remaining = MAX_TOTAL_BYTES - total_bytes
                    if remaining <= 0:
                        warnings.append("The 100 MiB total read limit was reached. Reading stopped.")
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
                                raise ValueError("The 4,000-chunk limit was exceeded; the file was not indexed.")
                            eid = f"{sid}-C{len(parts) + 1:04d}"
                            loc = location if is_table else f"{location} · characters {offset + 1}–{offset + len(part)}"
                            parts.append(Evidence(eid, relative, loc, part, sha, is_table))
                    if not parts:
                        raise ValueError("The file is empty and has no indexable content.")
                    evidence.extend(parts)
                    sources.append(Source(sid, relative, sha, len(data), len(parts)))
                except Cancelled:
                    raise
                except (ValueError, OSError, ImportError) as exc:
                    # Do not persist parser exception strings or document content.
                    reason = str(exc) if isinstance(exc, (ValueError, SafetyError)) else "Cannot read or parse this file."
                    warnings.append(f"{relative}：{reason[:180]}")
                except Exception:
                    warnings.append(f"{relative}: file parsing failed; skipped.")
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
