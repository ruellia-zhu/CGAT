@echo off
rem Build the standalone Windows folder with PyInstaller.
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m PyInstaller "build\circos_studio.spec" --noconfirm --distpath dist --workpath build\work
) else (
    python -m PyInstaller "build\circos_studio.spec" --noconfirm --distpath dist --workpath build\work
)
if errorlevel 1 exit /b 1
echo.
echo Built: dist\
