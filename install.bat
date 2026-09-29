@echo off
chcp 65001 >nul 2>&1
REM ==============================================================================
REM Katip: One-Click Windows Setup & Start Menu Registration Script
REM ==============================================================================

cd /d "%~dp0"

echo ======================================================
echo Katip Windows Kurulum Sihirbazi
echo ======================================================

REM 1. En uygun Python surumunu tespit et (PyAudio ve ses kutuphaneleri icin 3.10-3.13 tercih edilir)
set "PY_CMD="

py -3.13 --version >nul 2>&1
if not errorlevel 1 set "PY_CMD=py -3.13"

if not defined PY_CMD (
    py -3.12 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.12"
)

if not defined PY_CMD (
    py -3.11 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.11"
)

if not defined PY_CMD (
    py -3.10 --version >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.10"
)

if not defined PY_CMD (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [HATA] Python bulunamadi! Lutfen Python 3.10 veya ustunu yukleyin ve PATH'e ekleyin.
    pause
    exit /b 1
)

%PY_CMD% -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python 3.10 veya ustu gereklidir.
    pause
    exit /b 1
)

echo [BILGI] Kullanilan Python: %PY_CMD%

if not exist ".venv" (
    echo [BILGI] Sanal ortam .venv olusturuluyor...
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [HATA] Sanal ortam olusturulamadi!
        pause
        exit /b 1
    )
)

echo [BILGI] Bagimliliklar yukleniyor...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (
    echo [HATA] Bagimliliklar yuklenirken bir sorun olustu.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 (
    echo [HATA] Paket gelistirme modunda yuklenemedi.
    pause
    exit /b 1
)

echo [BILGI] Baslat Menusune ve Masaustune kisayol ekleniyor...
.venv\Scripts\python.exe -m katip --install
if errorlevel 1 (
    echo [HATA] Uygulama kisayollari olusturulamadi.
    pause
    exit /b 1
)

echo ======================================================
echo Kurulum Tamamlandi!
echo Baslat Menusunden veya Masaustundeki "Katip" simgesinden uygulamayi acabilirsiniz.
echo ======================================================
pause
