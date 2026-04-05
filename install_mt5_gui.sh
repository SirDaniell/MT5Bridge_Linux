#!/bin/bash
# Save this as install_mt5_gui.sh and run it inside the container
# This will launch the MT5 installer with GUI on your host display

set -e

export WINEPREFIX=/home/wineuser/.wine
export WINEARCH=win64
export WINEDEBUG=-all

echo "🔧 MT5 Manual Installation Script"
echo "================================================"

# Check display
if [ -z "$DISPLAY" ]; then
    echo "❌ No DISPLAY variable set!"
    echo "   Please set DISPLAY before running:"
    echo "   export DISPLAY=:0"
    exit 1
fi

echo "🖥️  Display: $DISPLAY"

# Download installer if not exists
INSTALLER_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
INSTALLER_PATH="/tmp/mt5setup.exe"

if [ ! -f "$INSTALLER_PATH" ]; then
    echo "📥 Downloading MT5 installer..."
    wget --timeout=60 --tries=3 "$INSTALLER_URL" -O "$INSTALLER_PATH"
    echo "✅ Download complete"
else
    echo "✅ Installer already downloaded"
fi

echo ""
echo "🚀 Launching MT5 Installer..."
echo "================================================"
echo "⚠️  IMPORTANT:"
echo "   - The installer window will appear on display $DISPLAY"
echo "   - Complete the installation normally"
echo "   - Accept the default installation path"
echo "   - The installer may take 2-5 minutes"
echo "================================================"
echo ""

# Launch installer
wine "$INSTALLER_PATH"

echo ""
echo "✅ Installer closed"

# Verify installation
MT5_PATH="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_PATH" ]; then
    echo "✅ MT5 Terminal installed successfully!"
    echo "   Location: $MT5_PATH"
else
    echo "⚠️  MT5 Terminal not found at expected location"
    echo "   Expected: $MT5_PATH"
    echo "   Please check if installation completed successfully"
fi

# Cleanup
rm -f "$INSTALLER_PATH"
echo "✅ Cleanup complete"
