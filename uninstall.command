#!/bin/bash
# ==============================================================================
# Katip: Double-Click Uninstaller for macOS Finder
# ==============================================================================

cd "$(dirname "$0")"
chmod +x uninstall.sh 2>/dev/null || true
./uninstall.sh

echo ""
echo "Pencereyi kapatmak icin Enter'a basin..."
read -r
