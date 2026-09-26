@echo off
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
.venv\Scripts\python.exe -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [BILGI] PyInstaller yukleniyor...
    .venv\Scripts\python.exe -m pip install pyinstaller
    if errorlevel 1 (
        echo [HATA] PyInstaller yuklenemedi!
        pause
        exit /b 1
    )
)

echo [BILGI] Standalone Katip.exe derleniyor (Bu islem 1-2 dakika surebilir)...
.venv\Scripts\pyinstaller.exe katip.spec --clean --noconfirm
if errorlevel 1 (
    echo [HATA] Derleme basarisiz oldu!
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
