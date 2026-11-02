"""Assemble verified Chromium runtime, local UI, and the separately bundled broker."""

import json
import shutil
from pathlib import Path

root = Path(__file__).resolve().parents[1]
runtime = root / ".runtime" / "electron"
target = root / "dist" / "v0.5.1" / "BMEWorkbench"
backend = root / "dist" / "service" / "BMEBackend"
if not (runtime / "electron.exe").is_file() or not (backend / "BMEBackend.exe").is_file():
    raise SystemExit("Desktop runtime or backend is missing.")
for path in (runtime, target, backend):
    if not path.resolve().is_relative_to(root):
        raise SystemExit("Build path escaped the project.")
target.mkdir(parents=True, exist_ok=True)
shutil.copytree(runtime, target, dirs_exist_ok=True)
original = target / "electron.exe"
renamed = target / "BMEWorkbench.exe"
if not original.resolve().is_relative_to(root) or not renamed.resolve().is_relative_to(root):
    raise SystemExit("Invalid executable target.")
original.replace(renamed)
assets = target / "resources" / "app"
assets.mkdir(parents=True, exist_ok=True)
for name in ("package.json", "main.cjs", "preload.cjs", "index.html", "styles.css", "renderer.js", "workflow.js"):
    shutil.copy2(root / "desktop" / name, assets / name)
shutil.copytree(backend, target / "backend", dirs_exist_ok=True)
manifest = {"version": "0.5.1", "electron": json.loads((root/".runtime/electron-version.json").read_text())["version"],
            "interface": "Chromium, per-monitor DPI", "endpoint": "https://api.openai.com/v1"}
(target / "build-info.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(renamed)
