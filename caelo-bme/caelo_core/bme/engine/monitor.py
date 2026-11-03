"""Read-only image folder polling. No uploads, deletion, or image rewriting."""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from .safety import SafetyError, checked_root, read_source, source_path

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@dataclass(frozen=True)
class ImageFile:
    name: str
    size: int
    mtime_ns: int

    @property
    def signature(self):
        return self.size, self.mtime_ns


class FolderMonitor:
    def __init__(self, root: Path):
        self.root = checked_root(root)
        self.previous: dict[str, tuple] = {}
        self.seen: dict[str, tuple] = {}
        self.initialized = False

    def poll(self) -> tuple[tuple[ImageFile, ...], tuple[ImageFile, ...]]:
        checked_root(self.root)
        found = []
        with os.scandir(self.root) as entries:
            for count, entry in enumerate(entries):
                if count >= 5000:
                    raise SafetyError("The image directory exceeds 5,000 entries. Select a smaller monitoring folder.")
                path = Path(entry.name)
                if path.suffix.lower() not in IMAGE_TYPES or entry.name.startswith("."):
                    continue
                try:
                    actual = source_path(self.root, entry.name)
                    info = actual.stat()
                    if 0 < info.st_size <= 20 * 1024 * 1024 and info.st_nlink == 1:
                        found.append(ImageFile(entry.name, info.st_size, info.st_mtime_ns))
                except (OSError, SafetyError):
                    continue
        found.sort(key=lambda item: (-item.mtime_ns, item.name))
        # Require unchanged size/mtime for two polls, so partially written images are not opened.
        stable = tuple(item for item in found if self.previous.get(item.name) == item.signature)
        changes = tuple(item for item in stable if self.seen.get(item.name) != item.signature)
        if not self.initialized:
            # Existing images form the baseline; a newly detected folder starts without notifications.
            self.seen = {item.name: item.signature for item in found}
            changes = ()
            self.initialized = True
        for item in stable:
            self.seen[item.name] = item.signature
        self.previous = {item.name: item.signature for item in found}
        self.seen = {name: sig for name, sig in self.seen.items() if name in self.previous}
        return tuple(found), changes


def image_preview(root: Path, name: str, bounds: tuple[int, int] = (1100, 700)):
    from PIL import Image, ImageOps
    import warnings

    if Path(name).suffix.lower() not in IMAGE_TYPES:
        raise SafetyError("Unsupported image type.")
    raw = read_source(root, name)
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(raw)) as source:
            if source.width * source.height > 20_000_000:
                raise SafetyError("The image exceeds 20 megapixels and was not loaded.")
            info = {"width": source.width, "height": source.height, "mode": source.mode,
                    "frames": getattr(source, "n_frames", 1)}
            source.seek(0)
            preview = ImageOps.exif_transpose(source).convert("RGB")
            preview.thumbnail(bounds)
            return preview.copy(), info
