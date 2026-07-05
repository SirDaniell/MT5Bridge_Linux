#!/bin/bash
# ==============================================================================
# MT5 Bridge Quick Start Script
# ==============================================================================
# One-command setup and start for MT5 Bridge
# This script automatically configures X11 and starts the bridge

set -e

echo "🚀 MT5 Bridge Quick Start"
echo "================================"
echo ""

# Check prerequisites
echo "Checking prerequisites..."
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed!"
    echo "   Install: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed!"
    echo "   Install: https://docs.docker.com/compose/install/"
    exit 1
fi

echo "✅ Docker and Docker Compose found"
echo ""

# Configure X11 access
echo "🖥️  Configuring X11 for GUI support..."
if command -v xhost &> /dev/null; then
    xhost +local:docker 2>/dev/null && echo "✅ X11 access configured" || {
        echo "⚠️  Failed to configure X11"
        echo "   You may need to run manually: xhost +local:docker"
    }
else
    echo "⚠️  xhost not found"
    echo "   Install: sudo apt-get install x11-xserver-utils"
    echo "   The MT5 installer GUI may not work without this!"
fi

# Check DISPLAY
echo ""
echo "Environment check:"
echo "   DISPLAY: ${DISPLAY:-not set}"
if [ -z "$DISPLAY" ]; then
    echo "   ⚠️  DISPLAY not set. Setting to :0"
    export DISPLAY=:0
fi
echo ""

# Build and start
echo "🏗️  Building and starting MT5 Bridge..."
echo "   (This may take a few minutes on first run)"
echo ""

docker-compose up --build -d

echo ""
echo "✅ MT5 Bridge is starting!"
echo ""
echo "================================================"
echo "📖 What Happens Next"
echo "================================================"
echo ""
echo "1️⃣  Wine environment is being initialized"
echo "2️⃣  MT5 installer window will appear on your screen"
echo "3️⃣  Complete the MT5 installation manually"
echo "4️⃣  Bridge will start automatically after installation"
echo "5️⃣  API will be available at http://localhost:8217"
echo ""
echo "================================================"
echo "🌐 API Endpoints"
echo "================================================"
echo ""
echo "   Health Check:    http://localhost:8217/test"
echo "   API Docs:        http://localhost:8217/docs"
echo "   OpenAPI Spec:    http://localhost:8217/openapi.json"
echo ""
echo "================================================"
echo "🔍 Useful Commands"
echo "================================================"
echo ""
echo "   View logs:       docker-compose logs -f"
echo "   Stop bridge:     docker-compose down"
echo "   Restart:         docker-compose restart"
echo "   Status:          docker-compose ps"
echo "   Clean rebuild:   ./rebuild.sh clean"
echo ""
echo "================================================"
echo "📜 Following logs (Ctrl+C to exit)..."
echo "================================================"
echo ""

sleep 3
docker-compose logs -f
