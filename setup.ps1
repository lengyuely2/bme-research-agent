$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --allow-existing .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
    uv pip install --python .venv\Scripts\python.exe -e '.[dev]' pyinstaller
} else {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
    & .venv\Scripts\python.exe -m pip install -e '.[dev]' pyinstaller
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Double-click start.bat.'
