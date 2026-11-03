"""Narrow filesystem broker. No model-controlled paths, source writes, or shell tools.

This is an application boundary, not a sandbox against a compromised Python process.
Windows reads additionally pin and validate the final file handle, refusing links.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path


class SafetyError(ValueError):
    pass


MAX_FILE_BYTES = 20 * 1024 * 1024


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )  # FILE_ATTRIBUTE_REPARSE_POINT includes Windows junctions.


def checked_path(path: Path, *, must_exist: bool = True) -> Path:
    path = Path(os.path.abspath(path))
    if str(path).startswith(("\\\\", "//")):
        raise SafetyError("Only local directories are supported; network shares and device paths are refused.")
    for node in reversed((path, *path.parents)):
        if node.exists() or node.is_symlink():
            if _is_link(node):
                raise SafetyError("Paths must not traverse symbolic links, junctions, or other reparse points.")
        elif must_exist:
            raise SafetyError("The specified file or directory does not exist.")
    return path


def checked_root(path: Path) -> Path:
    path = checked_path(path)
    if not path.is_dir():
        raise SafetyError("Select a source folder.")
    if path == Path(path.anchor):
        raise SafetyError("Select a project source folder rather than an entire drive.")
    return path


def source_path(root: Path, relative: str) -> Path:
    fragment = Path(relative)
    if not relative or fragment.is_absolute() or fragment.drive or ":" in relative:
        raise SafetyError("Absolute paths and device paths are refused.")
    if ".." in relative.replace("\\", "/").split("/"):
        raise SafetyError("Paths outside the authorized root are refused.")
    path = checked_path(root / fragment)
    if not path.is_relative_to(root) or not path.is_file():
        raise SafetyError("The file is outside the authorized source folder.")
    return path


def _windows_read(path: Path, root: Path, limit: int) -> bytes:
    """Open without write/delete sharing; check the actual handle, then read it."""
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    final_name = kernel.GetFinalPathNameByHandleW
    final_name.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_name.restype = wintypes.DWORD
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    handle = create(str(path), 0x80000000, 0x1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise SafetyError("Cannot open the file read-only; it may be locked or inaccessible.")
    transferred = False
    try:
        buf = ctypes.create_unicode_buffer(32768)
        length = final_name(handle, buf, len(buf), 0)
        if not length or length >= len(buf):
            raise SafetyError("Cannot verify the actual file location.")
        actual = buf.value
        if actual.startswith("\\\\?\\"):
            actual = actual[4:]
        if Path(actual) != path or not Path(actual).is_relative_to(root):
            raise SafetyError("The actual file location does not match the authorized path.")
        checked_path(path)
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDONLY | os.O_BINARY)
        transferred = True
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SafetyError("Only regular files are accepted; hard links are refused.")
            data = stream.read(limit + 1)
    finally:
        if not transferred:
            close(handle)
    return data


def read_source(root: Path, relative: str, limit: int = MAX_FILE_BYTES) -> bytes:
    root = checked_root(root)
    path = source_path(root, relative)
    if path.stat().st_size > limit:
        raise SafetyError("The file exceeds the per-file size limit.")
    if os.name == "nt":
        data = _windows_read(path, root, limit)
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise SafetyError("Only regular files are accepted; hard links are refused.")
            data = stream.read(limit + 1)
    if len(data) > limit:
        raise SafetyError("The file exceeds the per-file size limit.")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ReportStore:
    """Output path comes only from application configuration, never from the model."""

    def __init__(self, output: Path, source_root: Path | None):
        self.source_root = checked_root(source_root) if source_root is not None else None
        self.output = checked_path(output, must_exist=False)
        self._validate()

    def _validate(self) -> None:
        if self.source_root is not None:
            checked_path(self.source_root)
        checked_path(self.output, must_exist=False)
        if self.source_root is not None and (self.output.is_relative_to(self.source_root)
                or self.source_root.is_relative_to(self.output)):
            raise SafetyError("Source and output folders must be separate and must not contain each other.")

    def create(self, text: str, *, kind: str = "report", suffix: str = ".md") -> Path:
        if kind not in {"report", "audit"} or suffix not in {".md", ".json"}:
            raise SafetyError("Unsupported output type.")
        if len(text.encode("utf-8")) > 2 * 1024 * 1024:
            raise SafetyError("Output exceeds the size limit.")
        self._validate()
        self.output.mkdir(parents=True, exist_ok=True)
        self._validate()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self.output / f"{kind}-{stamp}-{uuid.uuid4().hex}.{suffix.lstrip('.')}"
        # Exclusive creation: never truncate or overwrite an existing file.
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        return path

    def audit(self, event: str, *, evidence_ids: tuple[str, ...] = (),
              tool_names: tuple[str, ...] = (), packet_hash: str = "") -> Path:
        if event not in {"local_report", "cloud_report", "cloud_failed", "cancelled"}:
            raise SafetyError("Unsupported audit event.")
        if any(not __import__("re").fullmatch(r"S\d{3}-C\d{4}", x) for x in evidence_ids):
            raise SafetyError("Unsupported evidence identifier.")
        allowed = {"list_evidence", "read_evidence", "search_evidence", "table_summary", "plot_data"}
        if any(name not in allowed for name in tool_names):
            raise SafetyError("Unsupported audit tool.")
        if packet_hash and (len(packet_hash) != 64 or any(c not in "0123456789abcdef" for c in packet_hash)):
            raise SafetyError("Invalid packet digest.")
        payload = {"at": datetime.now(timezone.utc).isoformat(), "event": event,
                   "evidence_ids": evidence_ids, "tools": tool_names,
                   "packet_sha256": packet_hash}
        return self.create(json.dumps(payload, ensure_ascii=False, indent=2), kind="audit", suffix=".json")

    def create_chart(self, png: bytes) -> Path:
        if not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) > 20 * 1024 * 1024:
            raise SafetyError("The chart must be a size-limited PNG file.")
        self._validate()
        self.output.mkdir(parents=True, exist_ok=True)
        self._validate()
        path = self.output / f"chart-{uuid.uuid4().hex}.png"
        with path.open("xb") as stream:
            stream.write(png)
        return path

    def create_analysis(self, payload: bytes) -> Path:
        """Only internally generated result archives, exclusive new names."""
        if not isinstance(payload, bytes) or not payload.startswith(b"PK\x03\x04") or len(payload)>50*1024*1024:
            raise SafetyError("The analysis package must be a size-limited ZIP file.")
        self._validate()
        self.output.mkdir(parents=True, exist_ok=True)
        self._validate()
        path=self.output/f"analysis-{uuid.uuid4().hex}.zip"
        with path.open("xb") as stream:
            stream.write(payload)
        return path
