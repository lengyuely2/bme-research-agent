@echo off
cd /d "%~dp0"
if exist "dist\v0.5.1\BMEWorkbench\BMEWorkbench.exe" (
    start "" "dist\v0.5.1\BMEWorkbench\BMEWorkbench.exe"
) else (
    if exist ".runtime\electron\electron.exe" (
        start "" ".runtime\electron\electron.exe" desktop
    ) else (
        echo Please run setup.ps1 and build.ps1 first.
        pause
    )
)
