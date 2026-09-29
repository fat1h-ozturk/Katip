@echo off
setlocal
chcp 65001 >nul 2>&1
REM ==============================================================================
REM Katip: One-Click Standalone Executable Builder (PyInstaller)
REM Produces a self-contained Katip.exe that runs on any Windows machine
REM without requiring Python or external dependencies installed.
REM ==============================================================================

cd /d "%~dp0"

echo ======================================================
echo Katip Standalone EXE Olusturucu
echo ======================================================

if not exist ".venv\Scripts\python.exe" (
    echo [HATA] .venv ortami bulunamadi! Lutfen once install.bat calistirin.
    pause
    exit /b 1
)

echo [BILGI] PyInstaller kontrol ediliyor...
.venv\Scripts\python.exe -c "import PyInstaller; assert PyInstaller.__version__ == '6.20.0'" >nul 2>&1
if errorlevel 1 (
    echo [BILGI] PyInstaller 6.20.0 yukleniyor...
    .venv\Scripts\python.exe -m pip install pyinstaller==6.20.0
    if errorlevel 1 (
        echo [HATA] PyInstaller yuklenemedi!
        pause
        exit /b 1
    )
)

for /f "delims=" %%I in ('.venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)"') do set "PY_BASE=%%I"
if not defined PY_BASE (
    echo [HATA] Python kurulum yolu belirlenemedi!
    pause
    exit /b 1
)

REM ASVS 15.2.4: PyInstaller baska araclarin DLL dosyalarini PATH uzerinden toplamasin.
set "PATH=%~dp0.venv\Scripts;%~dp0.venv;%PY_BASE%;%SystemRoot%\System32;%SystemRoot%"

echo [BILGI] Standalone Katip.exe derleniyor (Bu islem 1-2 dakika surebilir)...
.venv\Scripts\python.exe -m PyInstaller katip.spec --clean --noconfirm
if errorlevel 1 (
    echo [HATA] Derleme basarisiz oldu!
    pause
    exit /b 1
)

%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -Command "$ErrorActionPreference = 'Stop'; $p = Start-Process -FilePath (Resolve-Path 'dist\Katip.exe').Path -ArgumentList '--version' -PassThru -WindowStyle Hidden; if (-not $p.WaitForExit(30000)) { taskkill.exe /PID $p.Id /T /F; exit 1 }; $p.Refresh(); exit $p.ExitCode"
if errorlevel 1 (
    echo [HATA] Derlenen EXE baslatma kontrolunu gecemedi!
    pause
    exit /b 1
)

echo ======================================================
echo Derleme Basariyla Tamamlandi!
echo Cikti: dist\Katip.exe
echo ======================================================
echo Bu .exe dosyasini herhangi bir Windows bilgisayara kopyalayip
echo Python yuklemeden dogrudan calistirabilirsiniz.
echo ======================================================
pause
