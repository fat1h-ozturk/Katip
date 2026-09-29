#!/bin/bash
# ==============================================================================
# Katip: Double-Click Installer for macOS Finder
# ==============================================================================

cd "$(dirname "$0")"
chmod +x install.sh update.sh bin/katip 2>/dev/null || true
./install.sh
status=$?

echo ""
echo "Pencereyi kapatmak icin Enter'a basin..."
read -r
exit "$status"
