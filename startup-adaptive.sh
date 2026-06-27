#!/bin/bash
# startup-adaptive.sh
# Main entrypoint that chooses the correct startup method

set -e

echo "🚀 Starting MT5 Bridge (Adaptive Mode)..."
echo "================================================"

# Run detection
source /app/detect-platform.sh

# Route to appropriate startup script
if [ "$INSTALL_STRATEGY" = "wine" ]; then
    echo "🍷 Launching Wine startup..."
    exec /app/wine-startup.sh
elif [ "$INSTALL_STRATEGY" = "native" ]; then
    echo "🐧 Launching Native startup..."
    # For native, we just run python directly
    # Assuming requirements are met or mounted
    
    echo "Checking for native dependencies..."
    if ! python3 -c "import MetaTrader5" 2>/dev/null; then
        echo "⚠️  MetaTrader5 package not found. Attempting install..."
        pip3 install MetaTrader5 uvicorn[standard] pydantic requests numpy || echo "❌ Install failed"
    fi
    
    echo "Starting Bridge..."
    exec python3 -m uvicorn mt5_bridge:app --host 0.0.0.0 --port 5000 --workers 1 --loop asyncio
else
    echo "❌ Unknown strategy: $INSTALL_STRATEGY"
    exit 1
fi
