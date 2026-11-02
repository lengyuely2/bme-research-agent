"""Generate an opt-in Windows Sandbox configuration; never enable OS features."""

from __future__ import annotations

import argparse
import os
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from .safety import ReportStore, SafetyError, checked_path, checked_root


def generate(binary: Path, source: Path, output: Path, *, online: bool = False,
             config_dir: Path | None = None) -> Path:
    binary = checked_path(binary)
    if not binary.is_file() or binary.name not in {"BioResearch.exe", "BMEWorkbench.exe"}:
        raise SafetyError("请选择打包后的 BMEWorkbench.exe。")
    source = checked_root(source)
    store = ReportStore(output, source)
    app_dir, output = binary.parent, store.output
    config_dir = checked_path(config_dir or (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BioResearch" / "SandboxConfigs"),
        must_exist=False)
    roots = [app_dir, source, output, config_dir]
    for i, first in enumerate(roots):
        for second in roots[i + 1:]:
            if first.is_relative_to(second) or second.is_relative_to(first):
                raise SafetyError("程序、资料、结果和沙盒配置目录必须独立，不能互相包含。")
    output.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    for path in roots:
        checked_path(path)
    config = ET.Element("Configuration")
    for key, value in (("vGPU", "Disable"), ("Networking", "Enable" if online else "Disable"),
                       ("ProtectedClient", "Enable"),
                       ("ClipboardRedirection", "Disable"), ("AudioInput", "Disable"),
                       ("VideoInput", "Disable"), ("PrinterRedirection", "Disable"),
                       ("MemoryInMB", "4096")):
        ET.SubElement(config, key).text = value
    folders = ET.SubElement(config, "MappedFolders")
    for host, guest, readonly in ((app_dir, r"C:\BioApp", True),
                                  (source, r"C:\BioData", True),
                                  (output, r"C:\BioReports", False)):
        folder = ET.SubElement(folders, "MappedFolder")
        ET.SubElement(folder, "HostFolder").text = str(host)
        ET.SubElement(folder, "SandboxFolder").text = guest
        ET.SubElement(folder, "ReadOnly").text = "true" if readonly else "false"
    logon = ET.SubElement(config, "LogonCommand")
    # No user-controlled strings enter a command. Only the XML mappings use host paths.
    ET.SubElement(logon, "Command").text = (
        f'"C:\\BioApp\\{binary.name}" --source "C:\\BioData" --output "C:\\BioReports"'
    )
    ET.indent(config, space="  ")
    path = config_dir / f"BioResearch-{'online' if online else 'offline'}-{uuid.uuid4().hex}.wsb"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(ET.tostring(config, encoding="unicode"))
    return path


def main():
    parser = argparse.ArgumentParser(description="生成 Windows Sandbox 配置，默认禁网")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--online", action="store_true")
    args = parser.parse_args()
    print(generate(args.binary, args.source, args.output, online=args.online))


if __name__ == "__main__":
    main()
