$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$desktopPath = Join-Path $PSScriptRoot 'dist\v0.5.1\BMEWorkbench\BMEWorkbench.exe'
if (Test-Path -LiteralPath $desktopPath) {
    Start-Process -FilePath $desktopPath -WindowStyle Normal
    exit 0
}
$runtimePath = Join-Path $PSScriptRoot '.runtime\electron\electron.exe'
if (Test-Path -LiteralPath $runtimePath) {
    & $runtimePath (Join-Path $PSScriptRoot 'desktop')
    exit $LASTEXITCODE
}
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Host 'Please run setup.ps1 first.'
    exit 1
}
Write-Host 'Please run build.ps1 to prepare the dark desktop app.'
