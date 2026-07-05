#!/bin/bash
set -e

# ==============================================================================
# MT5 Bridge Rebuild Script
# ==============================================================================
# Simplified rebuild script for MT5 Bridge standalone deployment
# Usage:
#   ./rebuild.sh              - Normal rebuild with cache
#   ./rebuild.sh clean        - Clean rebuild (remove volumes, no cache)
#   ./rebuild.sh --no-cache   - Rebuild without Docker cache

echo "🚀 MT5 Bridge Rebuild"
echo "================================================"

# Configuration
BUILD_ARGS=""
CLEAN_MODE=0

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --no-cache|nocache)
            BUILD_ARGS="--no-cache"
            echo "🔥 CACHE DISABLED: Performing a full, from-scratch build."
            ;;
        clean)
            CLEAN_MODE=1
            BUILD_ARGS="--no-cache"
            echo "🧹 CLEAN MODE: Will remove volumes and rebuild from scratch"
            ;;
    esac
done

# ------------------------------------------------------------------------------
# X11 Setup for GUI
# ------------------------------------------------------------------------------
echo ""
echo "🖥️  Configuring X11 permissions for MT5 GUI installer..."
if command -v xhost >/dev/null 2>&1; then
    xhost +local:docker 2>/dev/null && echo "✅ X11 access configured" || echo "⚠️  Failed to set xhost"
else
    echo "⚠️  xhost not found. Install with: sudo apt-get install x11-xserver-utils"
fi

# Check DISPLAY
echo "   DISPLAY: ${DISPLAY:-not set}"
if [ -z "$DISPLAY" ]; then
    echo "   ⚠️  DISPLAY not set. Setting to :0"
    export DISPLAY=:0
fi

# ------------------------------------------------------------------------------
# Clean Mode: Remove Everything
# ------------------------------------------------------------------------------
if [ $CLEAN_MODE -eq 1 ]; then
    echo ""
    echo "�� Cleaning up MT5 Bridge resources..."
    
    # Stop and remove container
    echo "   - Stopping mt5-bridge container..."
    docker-compose down 2>/dev/null || true
    
    # Remove wine_prefix volume (forces fresh Wine installation)
    echo "   - Removing wine_prefix volume..."
    docker volume rm mt5bridge_linux_wine_prefix 2>/dev/null || \
    docker volume rm mt5bridge-linux_wine_prefix 2>/dev/null || \
    docker volume ls -q | grep wine_prefix | xargs -r docker volume rm 2>/dev/null || true
    
    # Prune dangling images
    echo "   - Pruning dangling images..."
    docker image prune -f 2>/dev/null || true
    
    echo "✅ Cleanup complete"
fi

# ------------------------------------------------------------------------------
# Build
# ------------------------------------------------------------------------------
echo ""
echo "🏗️  Building MT5 Bridge..."
if [ -z "$BUILD_ARGS" ]; then
    echo "   Using Docker cache for faster build"
else
    echo "   Building without cache (clean build)"
fi

docker-compose build $BUILD_ARGS

# ------------------------------------------------------------------------------
# Start
# ------------------------------------------------------------------------------
echo ""
echo "🚀 Starting MT5 Bridge..."
docker-compose up -d --force-recreate

# ------------------------------------------------------------------------------
# Wait for Health Check
# ------------------------------------------------------------------------------
echo ""
echo "⏳ Waiting for MT5 Bridge to initialize..."
echo "   This may take 3-6 minutes on first run (Wine setup + MT5 installation)"
echo ""

WAIT_COUNT=0
WAIT_MAX=400  # 400 seconds = ~6.5 minutes (enough for Wine + MT5 setup)
HEALTH_STATUS=""

while [ $WAIT_COUNT -lt $WAIT_MAX ]; do
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' mt5-bridge 2>/dev/null || echo "starting")
    
    case "$HEALTH_STATUS" in
        healthy)
            echo "✅ MT5 Bridge is healthy and ready!"
            break
            ;;
        unhealthy)
            echo "⚠️  MT5 Bridge reports unhealthy status"
            break
            ;;
        starting)
            if [ $((WAIT_COUNT % 10)) -eq 0 ]; then
                echo "   ... Still initializing ($WAIT_COUNT/${WAIT_MAX}s)"
            fi
            ;;
    esac
    
    sleep 2
    WAIT_COUNT=$((WAIT_COUNT + 2))
done

# ------------------------------------------------------------------------------
# Status Report
# ------------------------------------------------------------------------------
echo ""
echo "================================================"
echo "📊 MT5 Bridge Status"
echo "================================================"

# Check if container is running
if [ "$(docker ps -q -f name=mt5-bridge)" ]; then
    echo "✅ Container: Running"
else
    echo "❌ Container: Not running"
fi

# Check health
HEALTH=$(docker inspect --format='{{.State.Health.Status}}' mt5-bridge 2>/dev/null || echo "no healthcheck")
echo "🏥 Health: $HEALTH"

# Check API
if curl -s -f http://localhost:8217/test > /dev/null 2>&1; then
    echo "✅ API: Responding at http://localhost:8217"
else
    echo "⚠️  API: Not responding yet (may still be initializing)"
fi

echo ""
echo "================================================"
echo "📖 Important Notes"
echo "================================================"

if [ $CLEAN_MODE -eq 1 ] || [ ! -f "/var/lib/docker/volumes/mt5bridge_linux_wine_prefix/_data/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
    echo ""
    echo "🖥️  FIRST-TIME SETUP:"
    echo "   The MT5 installer window should appear on your screen soon."
    echo "   Please complete the installation manually when it appears."
    echo "   After installation, the bridge will start automatically."
    echo ""
fi

echo "🌐 API Endpoints:"
echo "   - Health Check:    http://localhost:8217/test"
echo "   - API Docs:        http://localhost:8217/docs"
echo "   - Initialize MT5:  POST http://localhost:8217/initialize"
echo ""
echo "🔍 Useful Commands:"
echo "   - View logs:       docker-compose logs -f"
echo "   - Stop bridge:     docker-compose down"
echo "   - Restart:         docker-compose restart"
echo "   - Clean rebuild:   ./rebuild.sh clean"
echo ""

# ------------------------------------------------------------------------------
# Follow Logs
# ------------------------------------------------------------------------------
echo "📜 Showing recent logs (Ctrl+C to exit)..."
echo "================================================"
sleep 2
docker-compose logs -f --tail=100
