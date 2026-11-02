@echo off
rem Launch with a console so tracebacks stay visible while developing.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app %*
) else (
    python -m app %*
)
