"""Download a pinned Electron release and verify its upstream SHA-256 before extraction."""

import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

VERSION = "45.2.1"
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
TARGET = RUNTIME / "electron"
META = RUNTIME / "electron-version.json"
if (TARGET / "electron.exe").is_file() and META.is_file():
    if json.loads(META.read_text(encoding="utf-8")).get("version") == VERSION:
        print(f"Electron {VERSION} already prepared.")
        raise SystemExit(0)

RUNTIME.mkdir(parents=True, exist_ok=True)
name = f"electron-v{VERSION}-win32-x64.zip"
base = f"https://github.com/electron/electron/releases/download/v{VERSION}/"
with urlopen(base + "SHASUMS256.txt", timeout=60) as response:
    sums = response.read(2_000_000).decode("utf-8")
expected = next((line.split()[0] for line in sums.splitlines()
                 if line.split()[-1].lstrip("*") == name), None)
if not expected:
    raise SystemExit("Release checksum is missing.")
archive = RUNTIME / name
digest = hashlib.sha256()
with urlopen(base + name, timeout=60) as response, archive.open("wb") as output:
    while block := response.read(1024 * 1024):
        digest.update(block)
        output.write(block)
if digest.hexdigest() != expected:
    raise SystemExit("Runtime checksum mismatch; archive was not extracted.")
with ZipFile(archive) as bundle:
    for item in bundle.infolist():
        if not (TARGET / item.filename).resolve().is_relative_to(TARGET.resolve()):
            raise SystemExit("Archive path escaped the runtime directory.")
    bundle.extractall(TARGET)
META.write_text(json.dumps({"version": VERSION}), encoding="utf-8")
print(f"Electron {VERSION} verified and prepared.")
