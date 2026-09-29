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

if exist ".venv\Scripts\python.exe" (
    echo [BILGI] Bagimliliklar guncelleniyor...
    .venv\Scripts\python.exe -m pip install -e .
    if errorlevel 1 (
        echo [HATA] Bagimliliklar guncellenemedi.
        pause
        exit /b 1
    )
    .venv\Scripts\python.exe -m katip --install
    if errorlevel 1 (
        echo [HATA] Uygulama kisayollari yenilenemedi.
        pause
        exit /b 1
    )
) else (
    echo [BILGI] Sanal ortam bulunamadi, tam kurulum calistiriliyor...
    call install.bat
    if errorlevel 1 exit /b 1
    exit /b 0
)

echo ======================================================
echo Guncelleme Basariyla Tamamlandi!
echo Uygulamayi Baslat Menusunden acabilirsiniz.
echo ======================================================
pause
