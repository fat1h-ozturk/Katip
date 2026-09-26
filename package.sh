#!/usr/bin/env bash
# ==============================================================================
# Katip: One-Click Standalone Binary Builder (PyInstaller)
# Builds a self-contained executable for Linux / macOS.
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "======================================================"
echo "📦 Katip Standalone Binary Oluşturucu"
echo "======================================================"

if [ ! -f ".venv/bin/python" ]; then
    echo "❌ Hata: .venv bulunamadı! Lütfen önce ./install.sh çalıştırın."
    exit 1
fi

echo "🔍 PyInstaller kontrol ediliyor..."
if ! .venv/bin/pip show pyinstaller &>/dev/null; then
    echo "📦 PyInstaller yükleniyor..."
    .venv/bin/pip install pyinstaller
fi

echo "🔨 Standalone ikili dosya derleniyor..."
.venv/bin/pyinstaller katip.spec --clean --noconfirm

echo "======================================================"
echo "🎉 Derleme Başarıyla Tamamlandı!"
echo "Çıktı: dist/Katip"
echo "======================================================"
