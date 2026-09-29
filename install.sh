#!/usr/bin/env bash
# ==============================================================================
# Katip: One-Click Linux Setup & Application Menu Registration Script
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "======================================================"
echo "🎙️  Katip Kurulum Sihirbazı"
echo "======================================================"

# 1. Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "❌ Hata: python3 bulunamadı. Lütfen Python 3.10 veya üstünü yükleyin."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "❌ Hata: Python 3.10 veya üstü gerekli."
    exit 1
fi
echo "✓ Python $PYTHON_VERSION algılandı."

# 2. Setup Virtual Environment
if [ ! -d ".venv" ]; then
    echo "📦 Sanal ortam (.venv) oluşturuluyor (--system-site-packages)..."
    python3 -m venv --system-site-packages .venv
else
    echo "✓ Sanal ortam (.venv) mevcut."
fi

# 3. Install Python Dependencies
echo "📦 Bağımlılıklar yükleniyor/güncelleniyor..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q

# 4. Make launcher and lifecycle scripts executable
chmod +x bin/katip update.sh install.sh uninstall.sh install.command update.command uninstall.command 2>/dev/null || true

# 5. Register with Desktop Environment & Application Menu / Spotlight
echo "🚀 Başlat Menüsü / Uygulama Arama entegrasyonu yapılıyor..."
.venv/bin/python -m katip --install

echo "======================================================"
echo "🎉 Kurulum Başarıyla Tamamlandı!"
echo ""
echo "📌 Kullanım Seçenekleri:"
echo "  1. Başlat Menüsü / KRunner: 'Katip' veya 'Dikte' yazarak açabilirsiniz."
echo "  2. Terminalden çalıştırmak için: ./bin/katip"
echo "  3. Kaydı başlatmak / durdurmak için kısayol: Ctrl+Alt+Space"
echo "======================================================"
