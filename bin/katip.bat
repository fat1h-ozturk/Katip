@echo off
rem Launcher script for Katip on Windows

setlocal
set "DIR=%~dp0.."

if "%~1"=="" (
    if exist "%DIR%\.venv\Scripts\katip-gui.exe" (
        start "" /d "%DIR%" "%DIR%\.venv\Scripts\katip-gui.exe"
        exit 0
    )
    if exist "%DIR%\.venv\Scripts\pythonw.exe" (
        start "" /d "%DIR%" "%DIR%\.venv\Scripts\pythonw.exe" -m katip
        exit 0
    )
)

if exist "%DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%DIR%\.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

"%PYTHON%" -m katip %*
endlocal
