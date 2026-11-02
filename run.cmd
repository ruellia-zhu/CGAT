@echo off
rem Launch Comparative Genomics Analysis without a console window.
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    ".venv\Scripts\pythonw.exe" -m app %*
) else (
    pythonw -m app %*
)
