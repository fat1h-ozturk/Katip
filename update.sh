#!/usr/bin/env bash
# ==============================================================================
# Katip: One-Click Linux Update Script
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "======================================================"
echo "🔄 Katip Güncelleme Aracı (Linux & macOS)"
echo "======================================================"

if ! command -v git &> /dev/null; then
    echo "❌ Hata: git komutu bulunamadı. Lütfen git kurun."
    exit 1
fi

echo "📦 En son sürüm GitHub'dan çekiliyor (git pull)..."
git pull

if [ -f ".venv/bin/activate" ]; then
    echo "📦 Bağımlılıklar güncelleniyor..."
    .venv/bin/pip install -r requirements.txt -q
    .venv/bin/pip install -e . --no-deps -q
    chmod +x bin/katip update.sh install.sh install.command update.command 2>/dev/null || true
    .venv/bin/python -m katip --install
else
    echo "📦 Sanal ortam bulunamadı, tam kurulum çalıştırılıyor..."
    bash install.sh
    exit 0
fi

echo "======================================================"
echo "🎉 Güncelleme Başarıyla Tamamlandı!"
echo "======================================================"
