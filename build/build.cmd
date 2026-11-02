@echo off
rem Build the one-folder Windows distribution.
rem
rem   dist\<app>\
rem       <app>.exe      PyInstaller entry point
rem       _internal\     Python, PySide6, matplotlib
rem       runtime\       WGDI venv
rem       bin\           blastp, muscle, seqkit, perl, pal2nal, yn00
rem
rem Usage:  build\build.cmd
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
) else (
    set "PY=python"
)

echo [1/3] PyInstaller ...
"%PY%" -m PyInstaller "build\circos_studio.spec" --noconfirm --distpath dist --workpath build\work
if errorlevel 1 goto :fail

"%PY%" "build\assemble.py" %*
if errorlevel 1 goto :fail

echo.
echo Done. See the dist folder.
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
