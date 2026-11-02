import json
import os
from pathlib import Path

import pytest

from bioagent.safety import ReportStore, SafetyError, checked_root, read_source


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "资料"
    root.mkdir()
    (root / "original.txt").write_text("IL6 原始资料", encoding="utf-8")
    return root


def test_read_is_byte_exact_and_does_not_modify_original(source):
    path = source / "original.txt"
    before = path.stat()
    assert read_source(source, "original.txt") == path.read_bytes()
    after = path.stat()
    assert (before.st_mtime_ns, before.st_size) == (after.st_mtime_ns, after.st_size)


@pytest.mark.parametrize("relative", ["../secret.txt", "sub/../../secret.txt", "..\\secret.txt",
                                      "C:\\Windows\\win.ini", "/etc/passwd", "original.txt:secret", ""])
def test_rejects_traversal_absolute_paths_and_streams(source, relative):
    with pytest.raises((SafetyError, OSError)):
        read_source(source, relative)


def test_limit_enforced(source):
    with pytest.raises(SafetyError):
        read_source(source, "original.txt", 3)


def test_rejects_hardlink(source, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    os.link(outside, source / "hardlink.txt")
    with pytest.raises(SafetyError):
        read_source(source, "hardlink.txt")


def test_rejects_symlink_or_junction(source, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    link = source / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("Cannot create links")
        import ctypes
        from ctypes import wintypes
        # Create a junction using the native filesystem helper, with fixed test paths.
        import subprocess
        result = subprocess.run(["powershell", "-NoProfile", "-Command",
            "New-Item -ItemType Junction -Path $env:BIO_TEST_LINK -Target $env:BIO_TEST_TARGET | Out-Null"],
            env={**os.environ, "BIO_TEST_LINK": str(link), "BIO_TEST_TARGET": str(outside)}, capture_output=True)
        if result.returncode:
            pytest.skip("Cannot create test junction")
    with pytest.raises(SafetyError):
        read_source(source, "linked/secret.txt")


@pytest.mark.parametrize("location", ["same", "child", "parent"])
def test_output_must_be_disjoint(source, location):
    output = {"same": source, "child": source / "reports", "parent": source.parent}[location]
    with pytest.raises(SafetyError):
        ReportStore(output, source)


def test_exclusive_reports_and_metadata_only_audit(source, tmp_path):
    store = ReportStore(tmp_path / "reports", source)
    first = store.create("report one")
    second = store.create("report two")
    assert first != second
    assert first.read_text(encoding="utf-8") == "report one"
    audit = store.audit("local_report", evidence_ids=("S001-C0001",), packet_hash="a" * 64)
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert set(payload) == {"at", "event", "evidence_ids", "tools", "packet_sha256"}
    assert str(source) not in audit.read_text(encoding="utf-8")
    with pytest.raises(SafetyError):
        store.audit("cloud_report", tool_names=("delete_file",))


def test_rejects_drive_root():
    with pytest.raises(SafetyError):
        checked_root(Path(Path.cwd().anchor))
