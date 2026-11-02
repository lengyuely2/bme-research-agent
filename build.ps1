$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .venv\Scripts\python.exe tools\fetch_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed.' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --console --onedir --distpath dist/service --name BMEBackend --add-data 'samples;samples' --collect-submodules pypdf --collect-all pypdfium2 --collect-all pypdfium2_raw --collect-data matplotlib backend_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Backend build failed.' }
& .venv\Scripts\python.exe tools\package_desktop.py
if ($LASTEXITCODE -ne 0) { throw 'Desktop packaging failed.' }
Write-Host 'Built: dist\v0.5.1\BMEWorkbench\BMEWorkbench.exe'
