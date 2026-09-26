@echo off
REM ==============================================================================
REM Katip: One-Click Windows Update Script
REM Pulls latest changes from Git, updates dependencies, and refreshes shortcut.
REM ==============================================================================

cd /d "%~dp0"

echo ======================================================
echo Katip Windows Guncelleme Araci
echo ======================================================

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [HATA] Git bulunamadi! Guncellemeleri alabilmek icin Git for Windows kurulu olmalidir.
    echo https://git-scm.com/ adresinden Git yukleyebilirsiniz.
    pause
    exit /b 1
)

echo [BILGI] En son surum GitHub'dan cekiliyor (git pull)...
git pull
if %errorlevel% neq 0 (
    echo [UYARI] Git pull sirasinda bir cakisma veya hata olustu.
    pause
    exit /b 1
)

if exist ".venv\Scripts\activate.bat" (
    echo [BILGI] Bagimliliklar guncelleniyor...
    call .venv\Scripts\activate.bat
    call python -m pip install -r requirements.txt
    call python -m pip install -e . --no-deps
    call python -m katip --install
) else (
    echo [BILGI] Sanal ortam bulunamadi, tam kurulum calistiriliyor...
    call install.bat
    exit /b 0
)

echo ======================================================
echo Guncelleme Basariyla Tamamlandi!
echo Uygulamayi Baslat Menusunden acabilirsiniz.
echo ======================================================
pause
