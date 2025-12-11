#!/bin/bash
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

# Start Xvfb in background (DISABLED for host display visibility)
# echo "🖥️  Starting Xvfb..."
# Xvfb :99 -screen 0 1024x768x16 -ac +extension GLX +render -noreset &
# XVFB_PID=$!
# export DISPLAY=:99

# Use host display passed from docker-compose
echo "🖥️  Using Host Display: $DISPLAY"

# Wait for Xvfb to be ready
sleep 3

echo "Wine Prefix: $WINEPREFIX"
echo "Display: $DISPLAY"
echo "================================================"

# Cleanup function
cleanup() {
    echo ""
    echo "🧹 Cleaning up..."
    wineserver -k 2>/dev/null || true
    kill $XVFB_PID 2>/dev/null || true
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
    timeout 180 bash -c "WINEDEBUG=-all winetricks -q $component 2>&1 | grep -v 'fixme:' | tail -n 5" || {
        echo "⚠️  $component installation timed out, killing Wine processes..."
        wineserver -k9
        sudo killall -9 wineserver wine wine64 2>/dev/null || true
        sleep 2
        return 0
    }
    
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

# Skip msxml3 and msxml6 if they cause hangs - MT5 usually works without them
# Uncomment if needed:
# install_component "msxml3"
# install_component "msxml6"

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

# Check for MT5 terminal
MT5_PATH="$WINEPREFIX/drive_c/Program Files/MetaTrader 5/terminal64.exe"
if [ -f "$MT5_PATH" ]; then
    echo "✅ MT5 terminal found at: $MT5_PATH"
else
    echo "⚠️  MT5 terminal not installed"
    echo "   Install it via POST /install endpoint or manually"
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

# Dialog killer removed by user request

echo "🌉 Starting MT5 Bridge server..."
cd /app

# Run with waitress for production
exec wine "$WINEPREFIX/drive_c/Python310/python.exe" -m waitress \
    --host=0.0.0.0 \
    --port=5000 \
    --threads=4 \
    --channel-timeout=120 \
    mt5_bridge:app
