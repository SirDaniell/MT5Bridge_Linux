#!/bin/bash
# wine-startup.sh
# Handles Wine initialization and MT5 setup

set -e

echo "🍷 Wine Startup Sequence"
echo "================================================"

# Ensure we run as wineuser
if [ "$(id -u)" = "0" ]; then
    echo "🔧 Running as root. Fixing permissions and switching user..."
    
    # Fix Wine prefix permissions
    if [ -d "/home/wineuser/.wine" ]; then
        echo "  Fixing /home/wineuser/.wine ownership..."
        chown -R wineuser:wineuser /home/wineuser/.wine
    fi
    
    # Fix runtime directory permissions
    mkdir -p /tmp/runtime-wineuser
    chown -R wineuser:wineuser /tmp/runtime-wineuser
    chmod 700 /tmp/runtime-wineuser
    
    # Switch to wineuser and re-run this script
    echo "🔄 Switching to wineuser..."
    exec runuser -u wineuser -- "$0" "$@"
fi

# Fix permissions if needed (common issue with Docker volumes)
# (This block is now redundant for root, but kept for safety if started as user)
if [ -d "/tmp/runtime-wineuser" ]; then
    if [ "$(stat -c '%U' /tmp/runtime-wineuser)" != "wineuser" ]; then
        echo "🔧 Fixing runtime directory permissions (via sudo)..."
        sudo chown -R wineuser:wineuser /tmp/runtime-wineuser
    fi
fi

export XDG_RUNTIME_DIR=/tmp/runtime-wineuser
if [ ! -d "$XDG_RUNTIME_DIR" ]; then
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
fi

# Display Setup
if [ -z "$DISPLAY" ]; then
    echo "🖥️  No DISPLAY set. Starting Xvfb (Headless Mode)..."
    Xvfb :99 -screen 0 1024x768x16 -ac +extension GLX +render -noreset &
    export DISPLAY=:99
    echo "  Display set to :99"
else
    echo "🖥️  Using Host Display: $DISPLAY"
    # Check X11 access
    if ! xset q &>/dev/null; then
        echo "⚠️  Warning: Cannot connect to X server. GUI may not work."
        echo "  Try running 'xhost +local:docker' on host."
    fi
fi

# Wine Initialization
if [ ! -d "$WINEPREFIX/drive_c/windows" ]; then
    echo "🔧 Initializing Wine Prefix..."
    wineboot --init > /dev/null 2>&1 &
    WINEBOOT_PID=$!
    wait $WINEBOOT_PID
    echo "✅ Wine initialized"
fi

# Install Windows components (essential for MT5)
echo "🍷 Installing Windows components..."
COMPONENTS_MARKER="$WINEPREFIX/.components_installed"

if [ ! -f "$COMPONENTS_MARKER" ]; then
    echo "  Installing corefonts (required for MT5)..."
    winetricks -q corefonts > /dev/null 2>&1 || echo "  ⚠️ corefonts installation had warnings (may be OK)"
    
    echo "  Installing vcrun2015 (Visual C++ Runtime)..."
    winetricks -q vcrun2015 > /dev/null 2>&1 || echo "  ⚠️ vcrun2015 installation had warnings (may be OK)"
    
    # Mark as installed
    touch "$COMPONENTS_MARKER"
    echo "✅ Windows components installed"
else
    echo "✅ Windows components already installed"
fi

# Python Setup in Wine
PYTHON_DIR="$WINEPREFIX/drive_c/Python310"
if [ ! -f "$PYTHON_DIR/python.exe" ]; then
    echo "📦 Setting up Python in Wine..."
    mkdir -p "$PYTHON_DIR"
    unzip -q /app/python-windows.zip -d "$PYTHON_DIR"
    
    # Enable site-packages
    sed -i 's/#import site/import site/' "$PYTHON_DIR/python310._pth"
    
    # Install pip
    cp /app/get-pip.py "$PYTHON_DIR/"
    wine "$PYTHON_DIR/python.exe" "$PYTHON_DIR/get-pip.py" --no-warn-script-location > /dev/null 2>&1
    
    echo "✅ Python setup complete"
fi

# Ensure Python packages are installed (check and install if missing)
echo "📦 Verifying Python packages..."
if ! wine "$PYTHON_DIR/python.exe" -c "import requests" 2>/dev/null; then
    echo "  Installing missing packages..."
    wine "$PYTHON_DIR/python.exe" -m pip install --no-warn-script-location MetaTrader5 Flask waitress requests numpy > /dev/null 2>&1
    echo "✅ Packages installed"
else
    echo "✅ Packages already installed"
fi

# MT5 Terminal Installation
MT5_EXE="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_EXE" ]; then
    echo "📥 MT5 Terminal not found. Installing automatically..."
    
    # Download MT5 installer
    INSTALLER_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    INSTALLER_PATH="$WINEPREFIX/drive_c/temp/mt5setup.exe"
    
    mkdir -p "$(dirname "$INSTALLER_PATH")"
    
    echo "  Downloading MT5 installer..."
    if wget --timeout=60 --tries=3 "$INSTALLER_URL" -O "$INSTALLER_PATH" > /dev/null 2>&1; then
        echo "  ✅ Download complete"
        
        echo "  Installing MT5 terminal (this may take 2-3 minutes)..."
        # Run installer in silent mode
        wine "$INSTALLER_PATH" /auto > /dev/null 2>&1 &
        INSTALL_PID=$!
        
        # Wait for installation with timeout
        timeout 180 bash -c "while kill -0 $INSTALL_PID 2>/dev/null; do sleep 2; done" || {
            echo "  ⚠️ Installation timeout, killing process..."
            kill -9 $INSTALL_PID 2>/dev/null || true
        }
        
        # Wait a bit more for files to be written
        sleep 10
        
        # Check if installed
        if [ -f "$MT5_EXE" ]; then
            echo "  ✅ MT5 terminal installed successfully"
            rm -f "$INSTALLER_PATH"
        else
            echo "  ⚠️ MT5 installation may have failed"
            echo "     Terminal not found at: $MT5_EXE"
            echo "     You can install it later via /install endpoint"
        fi
    else
        echo "  ❌ Failed to download MT5 installer"
        echo "     You can install it later via /install endpoint"
    fi
else
    echo "✅ MT5 Terminal already installed at: $MT5_EXE"
fi

# Start Bridge
echo "🌉 Starting Bridge Server..."
cd /app
exec wine "$PYTHON_DIR/python.exe" -m waitress --host=0.0.0.0 --port=5000 mt5_bridge:app
