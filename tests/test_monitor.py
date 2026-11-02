import os

import pytest
from PIL import Image

from bioagent.monitor import FolderMonitor, image_preview
from bioagent.safety import SafetyError, digest


def create_image(path, color="red"):
    Image.new("RGB", (120, 80), color).save(path)


def test_monitor_baselines_existing_files_and_announces_stable_new_images(tmp_path):
    create_image(tmp_path / "existing.png")
    monitor = FolderMonitor(tmp_path)
    files, changes = monitor.poll()
    assert len(files) == 1 and not changes
    assert not monitor.poll()[1]
    create_image(tmp_path / "new.png", "blue")
    assert not monitor.poll()[1]  # First observation might still be a partial file.
    assert [f.name for f in monitor.poll()[1]] == ["new.png"]
    assert not monitor.poll()[1]


def test_partial_or_modified_image_requires_two_unchanged_polls(tmp_path):
    path = tmp_path / "frame.png"
    create_image(path)
    monitor = FolderMonitor(tmp_path)
    monitor.poll()
    stamp = path.stat().st_mtime_ns
    os.utime(path, ns=(stamp + 10000, stamp + 10000))
    assert not monitor.poll()[1]
    assert len(monitor.poll()[1]) == 1
    assert not monitor.poll()[1]


def test_readonly_preview_and_exif_safe_thumbnail_do_not_rewrite_original(tmp_path):
    path = tmp_path / "frame.png"
    create_image(path)
    before, mtime = digest(path.read_bytes()), path.stat().st_mtime_ns
    preview, info = image_preview(tmp_path, "frame.png", (60, 60))
    assert preview.size == (60, 40)
    assert info["width"] == 120 and info["height"] == 80
    assert digest(path.read_bytes()) == before
    assert path.stat().st_mtime_ns == mtime
    with pytest.raises(SafetyError):
        image_preview(tmp_path, "../secret.png")


def test_monitor_rejects_hardlinks_and_unsupported_files(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    create_image(tmp_path / "outside.png")
    os.link(tmp_path / "outside.png", root / "linked.png")
    (root / "not_image.py").write_text("dangerous code")
    assert FolderMonitor(root).poll()[0] == ()
