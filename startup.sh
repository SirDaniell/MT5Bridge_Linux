#!/bin/bash
# ==============================================================================
# CRITICAL STABILITY WARNING - DO NOT MODIFY WITHOUT BACKUP
# ==============================================================================
# This script handles the delicate initialization of Wine and MT5.
# 
# Key behaviors to preserve:
# 1. Proper Xvfb/Display handling (uses host display if available)
# 2. Robust Wine prefix initialization with timeouts
# 3. Winetricks with interactive fallback for GUI
# 4. Correct Python environment setup in Wine
# 
# CHANGES HERE CAN CAUSE "IPC TIMEOUT" OR "FILE NOT FOUND" ERRORS.
# ==============================================================================
set -e

echo "🚀 Starting MT5 Bridge initialization..."
echo "================================================"

# Fix Wine prefix ownership if needed
if [ "$(stat -c '%U' /home/wineuser/.wine 2>/dev/null || echo 'none')" != "wineuser" ]; then
    echo "🔧 Fixing Wine prefix ownership..."
    sudo chown -R wineuser:wineuser /home/wineuser/.wine 2>/dev/null || true
fi

export WINEPREFIX=/home/wineuser/.wine
export WINEARCH=win64
export WINEDEBUG=-all
export WINESERVER_TIMEOUT=300

# Set XDG_RUNTIME_DIR to avoid errors
export XDG_RUNTIME_DIR=/tmp/runtime-wineuser
if [ ! -d "$XDG_RUNTIME_DIR" ]; then
    mkdir -p "$XDG_RUNTIME_DIR"
    chmod 700 "$XDG_RUNTIME_DIR"
fi

# Intelligent Display configuration
USE_XVFB=0
if [ -n "$DISPLAY" ]; then
    echo "🖥️  Host Display set: $DISPLAY"
    echo "🔎 Verifying X11 connection..."
    
    # Try to verify X connection using xset (if available) or python
    if command -v xset &> /dev/null; then
        if timeout 3 xset q &>/dev/null; then
             echo "✅ Host Display connection verified"
        else
             echo "❌ Host Display connection failed (xset). Falling back to Xvfb..."
             USE_XVFB=1
        fi
    else
        # Fallback python check if xset missing
        if python3 -c "import ctypes; l=ctypes.cdll.LoadLibrary('libX11.so.6'); d=l.XOpenDisplay(None); exit(0 if d else 1)" 2>/dev/null; then
             echo "✅ Host Display connection verified (via Python)"
        else
             echo "❌ Host Display connection failed (via Python). Falling back to Xvfb..."
             USE_XVFB=1
        fi
    fi
else
    echo "ℹ️  No DISPLAY set"
    USE_XVFB=1
fi

if [ "$USE_XVFB" -eq 1 ]; then
    echo "🖥️  Starting Xvfb (Virtual Display)..."
    export DISPLAY=:1
    
    # Cleanup any stale locks
    rm -f /tmp/.X1-lock
    
    Xvfb :1 -screen 0 1024x768x16 &
    XVFB_PID=$!
    echo "✅ Xvfb started on :1 (PID: $XVFB_PID)"
    
    # Wait for Xvfb to be ready
    sleep 2
fi

echo "Wine Prefix: $WINEPREFIX"
echo "Display: $DISPLAY"
echo "================================================"

# Cleanup function
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    wineserver -k 2>/dev/null || true
    echo "✅ Cleanup complete"
}
trap cleanup EXIT INT TERM

# Kill any existing wine processes
echo "🧹 Killing any existing Wine processes..."
wineserver -k 2>/dev/null || true
sudo killall -9 wineserver wine wine64 2>/dev/null || true
sleep 2

# Initialize Wine prefix if needed
if [ ! -d "$WINEPREFIX/drive_c/windows/system32" ]; then
    echo "🔧 Initializing Wine prefix (first run, may take 2-3 minutes)..."
    
    # Initialize wine with minimal output
    WINEDEBUG=-all wineboot --init 2>&1 | grep -v "fixme:" | head -n 10 &
    WINEBOOT_PID=$!
    
    # Wait for wineboot with timeout
    echo "⏳ Waiting for wineboot to complete..."
    timeout 180 bash -c "while kill -0 $WINEBOOT_PID 2>/dev/null; do sleep 2; done" || {
        echo "⚠️  Wineboot timeout, killing process..."
        kill -9 $WINEBOOT_PID 2>/dev/null || true
    }
    
    # Force wineserver wait with aggressive timeout
    timeout 60 wineserver -w || {
        echo "⚠️  Wineserver wait timed out, force killing..."
        wineserver -k9
        sleep 3
    }
    
    echo "✅ Wine prefix initialized"
else
    echo "✅ Wine prefix already exists"
fi

# Test Wine
echo "🧪 Testing Wine..."
wine --version || {
    echo "❌ Wine not available"
    exit 1
}
echo "✅ Wine is working"

# Function to install winetricks component with aggressive timeout handling
install_component() {
    local component=$1
    echo ""
    echo "📦 Installing $component..."
    
    # Kill any hanging processes first
    wineserver -k 2>/dev/null || true
    sleep 1
    
    # Run winetricks with timeout
    if ! timeout 180 bash -c "WINEDEBUG=-all winetricks -q $component 2>&1 | grep -v 'fixme:' | tail -n 5"; then
        echo "⚠️  $component silent installation failed or timed out."
        
        # Check if we have a display to show UI
        if [ -n "$DISPLAY" ]; then
            echo "🖥️  Display detected ($DISPLAY). Attempting interactive installation..."
            
            # Notify user if zenity is available
            if command -v zenity &> /dev/null; then
                zenity --info --text="Silent installation of $component failed.\n\nPlease complete the installation manually in the window that appears." --title="MT5 Bridge Setup" --timeout=10 &
            fi
            
            # Try interactive installation
            wineserver -k 2>/dev/null || true
            sleep 1
            winetricks $component || {
                echo "❌ Interactive installation of $component failed."
                return 1
            }
        else
            echo "❌ No display available for interactive fallback."
            return 1
        fi
    fi
    
    # Force wineserver cleanup
    timeout 30 wineserver -w || wineserver -k9
    sleep 2
    
    echo "✅ $component installation complete"
}

# Install Windows components (only essential ones to save time)
echo ""
echo "🍷 Installing Windows components..."
echo "================================================"

# Core fonts (essential for MT5)
install_component "corefonts"

# Visual C++ runtime (essential for MT5 and Python packages)
install_component "vcrun2015"

echo "✅ All Windows components installed"
echo "================================================"

# Final aggressive cleanup
echo "🧹 Final Wine cleanup..."
wineserver -k9 2>/dev/null || true
sudo killall -9 wineserver wine wine64 2>/dev/null || true
sleep 3

# Setup Python in Wine if not exists
if [ ! -f "$WINEPREFIX/drive_c/Python310/python.exe" ]; then
    echo ""
    echo "📦 Setting up Python in Wine..."
    echo "================================================"
    
    # Extract Python
    mkdir -p "$WINEPREFIX/drive_c/Python310"
    unzip -q /app/python.zip -d "$WINEPREFIX/drive_c/Python310"
    
    # Verify extraction
    if [ ! -f "$WINEPREFIX/drive_c/Python310/python.exe" ]; then
        echo "❌ Python extraction failed"
        exit 1
    fi
    echo "✅ Python extracted"
    
    # Configure Python to enable site-packages
    if [ -f "$WINEPREFIX/drive_c/Python310/python310._pth" ]; then
        sed -i 's/#import site/import site/' "$WINEPREFIX/drive_c/Python310/python310._pth"
        echo "✅ Python site-packages enabled"
    fi
    
    # Install pip
    echo "📦 Installing pip..."
    cp /app/get-pip.py "$WINEPREFIX/drive_c/Python310/"
    
    WINEDEBUG=-all wine "$WINEPREFIX/drive_c/Python310/python.exe" "$WINEPREFIX/drive_c/Python310/get-pip.py" --no-warn-script-location 2>&1 | grep -v "fixme:" | tail -n 3
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    echo "✅ pip installed"
    
    # Install Python packages one by one
    echo "📦 Installing numpy..."
    WINEDEBUG=-all wine "$WINEPREFIX/drive_c/Python310/python.exe" -m pip install --no-warn-script-location "numpy==1.24.3" 2>&1 | grep -v "fixme:" | tail -n 3
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    echo "✅ numpy installed"

    echo "📦 Installing requests..."
    WINEDEBUG=-all wine "$WINEPREFIX/drive_c/Python310/python.exe" -m pip install --no-warn-script-location "requests"
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    echo "✅ requests installed"
    
    echo "📦 Installing MetaTrader5..."
    WINEDEBUG=-all wine "$WINEPREFIX/drive_c/Python310/python.exe" -m pip install --no-warn-script-location "MetaTrader5" 2>&1 | grep -v "fixme:" | tail -n 3
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    echo "✅ MetaTrader5 installed"
    
    echo "📦 Installing Flask and waitress..."
    WINEDEBUG=-all wine "$WINEPREFIX/drive_c/Python310/python.exe" -m pip install --no-warn-script-location Flask waitress 2>&1 | grep -v "fixme:" | tail -n 3
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    echo "✅ Flask and waitress installed"
    
    echo "================================================"
    echo "✅ Python setup complete"
else
    echo "✅ Python already installed in Wine"
fi

# Test Python
echo ""
echo "🧪 Testing Wine Python..."
wine "$WINEPREFIX/drive_c/Python310/python.exe" --version

# Test MT5 import
echo "🧪 Testing MetaTrader5 import..."
wine "$WINEPREFIX/drive_c/Python310/python.exe" -c "import MetaTrader5 as mt5; print('✅ MT5 imported successfully')" 2>&1 | grep -v "fixme:"

echo ""
echo "================================================"
echo "✅ All initialization complete!"
echo "================================================"

# Install MT5 Terminal
MT5_PATH="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_PATH" ]; then
    echo ""
    echo "📥 MT5 Terminal not found. Installing..."
    echo "================================================"
    
    # Download MT5 installer
    INSTALLER_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    INSTALLER_PATH="/tmp/mt5setup.exe"
    
    echo "  Downloading MT5 installer..."
    if wget --timeout=60 --tries=3 "$INSTALLER_URL" -O "$INSTALLER_PATH" > /dev/null 2>&1; then
        echo "  ✅ Download complete"
        
        # Check if we have a display for GUI installation
        if [ -n "$DISPLAY" ]; then
            echo "  🖥️  Display available: $DISPLAY"
            echo "  🚀 Launching MT5 installer..."
            echo ""
            echo "  ⚠️  IMPORTANT: MT5 installer window will appear on your display"
            echo "     Please complete the installation manually"
            echo "     The installer will close automatically when done"
            echo ""
            
            # Run installer (will show on host display)
            wine "$INSTALLER_PATH" &
            INSTALLER_PID=$!
            
            # Wait for installer to complete (user closes it)
            echo "  ⏳ Waiting for installation to complete..."
            wait $INSTALLER_PID 2>/dev/null || true
            
            # Give it a moment for files to be written
            sleep 5
            
            # Cleanup
            rm -f "$INSTALLER_PATH"
            
            # Verify installation
            if [ -f "$MT5_PATH" ]; then
                echo "  ✅ MT5 terminal installed successfully!"
                echo "     Location: $MT5_PATH"
            else
                echo "  ⚠️  MT5 terminal not found after installation"
                echo "     Expected at: $MT5_PATH"
                echo "     You can install it later via POST /install endpoint"
            fi
        else
            echo "  ❌ No DISPLAY available for GUI installation"
            echo "     Please set DISPLAY environment variable or run:"
            echo "     xhost +local:docker"
            echo "     Then restart the container"
            rm -f "$INSTALLER_PATH"
        fi
    else
        echo "  ❌ Failed to download MT5 installer"
        echo "     You can install it later via POST /install endpoint"
    fi
    
    echo "================================================"
else
    echo "✅ MT5 Terminal already installed at: $MT5_PATH"
fi

# Create common.ini to disable wizards and enable AutoTrading
CONFIG_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/config"
mkdir -p "$CONFIG_DIR"
echo "⚙️ Forcing common.ini configuration..."
cat <<EOF > "$CONFIG_DIR/common.ini"
[Common]
NewsEnable=0
Certificates=0
[Charts]
MaxBars=100000
PrintColor=1
SaveDeleted=0
[Experts]
AllowDllImport=1
Enabled=1
Account=1
Profile=1
EOF

echo "🌉 Starting MT5 Bridge server..."
cd /app

# Run with waitress for production
# Run with waitress for production
exec wine "$WINEPREFIX/drive_c/Python310/python.exe" -m waitress \
    --host=0.0.0.0 \
    --port=5000 \
    --threads=4 \
    --channel-timeout=120 \
    mt5_bridge:app
