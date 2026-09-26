#!/bin/bash
# ==============================================================================
# Katip: Double-Click Updater for macOS Finder
# ==============================================================================

cd "$(dirname "$0")"
chmod +x update.sh bin/katip 2>/dev/null || true
./update.sh

echo ""
echo "Pencereyi kapatmak icin Enter'a basin..."
read -r
