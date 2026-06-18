#!/bin/bash
# ==============================================================================
# CRITICAL STABILITY WARNING - DO NOT MODIFY WITHOUT BACKUP
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
    
    # Try to verify X connection using python (more reliable than xset)
    if python3 -c "import ctypes; l=ctypes.cdll.LoadLibrary('libX11.so.6'); d=l.XOpenDisplay(None); exit(0 if d else 1)" 2>/dev/null; then
         echo "✅ Host Display connection verified"
    else
         echo "⚠️  Host Display connection failed. Falling back to Xvfb..."
         echo "    To use host display, run: xhost +local:docker"
         USE_XVFB=1
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

# Test Wine Functionality — retry up to 3 times, wineserver needs a moment after being killed
echo "🧪 Testing Wine functionality..."
WINE_TEST_OK=0
for attempt in 1 2 3; do
    if wine cmd /c ver &> /dev/null; then
        WINE_TEST_OK=1
        break
    fi
    echo "   ⚠️  Wine test attempt $attempt/3 failed, waiting 3s..."
    sleep 3
done

if [ "$WINE_TEST_OK" -eq 0 ]; then
    echo "❌ Wine is broken or prefix is corrupted (failed 3 attempts)."
    echo "🧹 Wiping corrupted prefix..."

    wineserver -k9 2>/dev/null || true
    sudo killall -9 wineserver wine wine64 2>/dev/null || true
    rm -rf "$WINEPREFIX"

    if [ -d "$WINEPREFIX" ]; then
        echo "❌ Failed to delete prefix. Check permissions."
        exit 1
    fi
    echo "✅ Prefix wiped. Please restart container."
    exit 1
fi

wine --version || {
    echo "❌ Wine binary not found"
    exit 1
}
echo "✅ Wine is working"

# Function to install winetricks component
install_component() {
    local component=$1
    echo ""
    echo "📦 Installing $component..."
    
    wineserver -k 2>/dev/null || true
    sleep 1
    
    if ! timeout 180 bash -c "WINEDEBUG=-all winetricks -q $component 2>&1 | grep -v 'fixme:' | tail -n 5"; then
        echo "⚠️  $component installation timed out or failed"
        
        if [ -n "$DISPLAY" ] && [ "$USE_XVFB" -eq 0 ]; then
            echo "🖥️  Attempting interactive installation..."
            wineserver -k 2>/dev/null || true
            sleep 1
            winetricks $component || {
                echo "❌ Interactive installation failed"
                return 1
            }
        fi
    fi
    
    timeout 30 wineserver -w || wineserver -k9
    sleep 2
    
    echo "✅ $component installation complete"
}

# Install Windows components
echo ""
echo "🍷 Installing Windows components..."
echo "================================================"

install_component "corefonts"
install_component "vcrun2015"

echo "✅ All Windows components installed"
echo "================================================"

# Final cleanup
echo "🧹 Final Wine cleanup..."
wineserver -k9 2>/dev/null || true
sudo killall -9 wineserver wine wine64 2>/dev/null || true
sleep 3

# Setup Python in Wine
PYTHON_DIR="$WINEPREFIX/drive_c/Python310"

if [ ! -f "$PYTHON_DIR/python.exe" ]; then
    echo ""
    echo "📦 Setting up Python in Wine..."
    echo "================================================"
    
    # Extract Python
    mkdir -p "$PYTHON_DIR"
    unzip -q /app/python.zip -d "$PYTHON_DIR"
    
    if [ ! -f "$PYTHON_DIR/python.exe" ]; then
        echo "❌ Python extraction failed"
        exit 1
    fi
    echo "✅ Python extracted"
    
    # Enable site-packages
    if [ -f "$PYTHON_DIR/python310._pth" ]; then
        sed -i 's/#import site/import site/' "$PYTHON_DIR/python310._pth"
        echo "✅ Python site-packages enabled"
    fi
fi

# ALWAYS check and install pip if missing (THIS IS THE FIX!)
echo "📦 Checking pip installation..."
if [ ! -f "$PYTHON_DIR/Scripts/pip.exe" ]; then
    echo "   Installing pip..."
    cp /app/get-pip.py "$PYTHON_DIR/"
    
    WINEDEBUG=-all wine "$PYTHON_DIR/python.exe" "$PYTHON_DIR/get-pip.py" --no-warn-script-location 2>&1 | tail -n 5
    timeout 45 wineserver -w || wineserver -k9
    sleep 2
    
    if [ ! -f "$PYTHON_DIR/Scripts/pip.exe" ]; then
        echo "❌ CRITICAL: Pip installation failed!"
        exit 1
    fi
    echo "✅ Pip installed"
else
    echo "✅ Pip already installed"
fi

# Install/verify Python packages
echo ""
echo "📦 Verifying Python dependencies..."
echo "================================================"

# Function to check and install package
install_if_missing() {
    local package=$1
    local import_name=${2:-$package}
    
    if ! wine "$PYTHON_DIR/python.exe" -c "import ${import_name}" 2>/dev/null; then
        echo "   Installing ${package}..."
        WINEDEBUG=-all wine "$PYTHON_DIR/python.exe" -m pip install --no-warn-script-location "${package}" 2>&1 | tail -n 3
        timeout 45 wineserver -w || wineserver -k9
        sleep 2
        echo "   ✅ ${package} installed"
    else
        echo "   ✅ ${package} ready"
    fi
}

install_if_missing "numpy==1.24.3" "numpy"
install_if_missing "requests" "requests"
install_if_missing "MetaTrader5" "MetaTrader5"
install_if_missing "Flask" "flask"
install_if_missing "waitress" "waitress"

echo "================================================"
echo "✅ All Python packages verified"

# Test imports
echo ""
echo "🧪 Testing Python environment..."
wine "$PYTHON_DIR/python.exe" --version
wine "$PYTHON_DIR/python.exe" -c "import MetaTrader5 as mt5; print('✅ MT5 import successful')" 2>&1 | grep -v "fixme:"
wine "$PYTHON_DIR/python.exe" -c "import waitress; print('✅ Waitress import successful')" 2>&1 | grep -v "fixme:"

echo ""
echo "================================================"
echo "✅ All initialization complete!"
echo "================================================"

# MT5 Terminal Installation
MT5_PATH="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ ! -f "$MT5_PATH" ]; then
    echo ""
    echo "📥 MT5 Terminal not found. Downloading installer..."
    echo "================================================"
    
    INSTALLER_URL="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
    INSTALLER_PATH="/tmp/mt5setup.exe"
    
    if wget --timeout=60 --tries=3 "$INSTALLER_URL" -O "$INSTALLER_PATH" > /dev/null 2>&1; then
        echo "✅ Download complete"
        
        if [ "$USE_XVFB" -eq 0 ]; then
            echo ""
            echo "🖥️  GUI INSTALLATION MODE"
            echo "================================================"
            echo "⚠️  The MT5 installer will appear on your display: $DISPLAY"
            echo "    Please complete the installation manually."
            echo "    The container will wait for you to finish."
            echo "================================================"
            echo ""
            
            # Launch installer and wait
            wine "$INSTALLER_PATH" &
            INSTALLER_PID=$!
            
            echo "⏳ Waiting for installer to finish (PID: $INSTALLER_PID)..."
            wait $INSTALLER_PID 2>/dev/null || true
            echo "⏹️  MT5 Installer window closed."
            sleep 5
            
            if [ -f "$MT5_PATH" ]; then
                echo "✅ MT5 installed successfully!"
            else
                echo "⚠️  MT5 not found after GUI closure."
                echo "📥 Attempting silent installation as fallback..."
                wine "$INSTALLER_PATH" /quiet &
                SILENT_PID=$!
                
                # Wait for silent install with timeout
                timeout 120 bash -c "while [ ! -f '$MT5_PATH' ] && kill -0 $SILENT_PID 2>/dev/null; do sleep 5; done"
                
                if [ -f "$MT5_PATH" ]; then
                    echo "✅ MT5 installed successfully in silent mode!"
                else
                    echo "⚠️  Silent installation failed or timed out."
                    echo "    You can try again later via: POST /install"
                fi
            fi
        else
            echo "ℹ️  Running in headless mode (Xvfb)"
            echo "   To install MT5 with GUI, restart with:"
            echo "   1. xhost +local:docker (on host)"
            echo "   2. Set DISPLAY=:0 in docker-compose.yml"
            echo ""
            echo "   Or install later via: POST /install"
        fi
        
        rm -f "$INSTALLER_PATH"
    else
        echo "⚠️  Download failed. Install later via /install endpoint"
    fi
    
    echo "================================================"
else
    echo "✅ MT5 Terminal already installed"
fi

# Create MT5 config
CONFIG_DIR="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/config"
mkdir -p "$CONFIG_DIR"
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

echo ""
echo "🌉 Starting MT5 Bridge server..."
cd /app

exec wine "$PYTHON_DIR/python.exe" -m waitress \
    --host=0.0.0.0 \
    --port=5000 \
    --threads=32 \
    --connection-limit=200 \
    --channel-timeout=120 \
    mt5_bridge:app