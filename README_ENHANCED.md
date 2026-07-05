# MetaTrader 5 (MT5) Linux Bridge

An open-source, lightweight Docker-based bridge that enables the official MetaTrader 5 Python library to run seamlessly on Linux.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Docker](https://img.shields.io/badge/Docker-Required-blue.svg)](https://www.docker.com/)
[![Wine 10](https://img.shields.io/badge/Wine-10.0-red.svg)](https://www.winehq.org/)

---

## 🚀 Quick Start (60 seconds)

```bash
# Clone the repository
git clone <your-repo-url>
cd MT5Bridge_Linux

# Run quick start script
./quickstart.sh
```

That's it! The MT5 installer will appear on your screen. Complete the installation and the bridge starts automatically.

---

## 📋 Table of Contents

- [The Linux Issue](#the-linux-issue-why-this-exists)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Option 1: Quick Start (Recommended)](#option-1-quick-start-recommended)
  - [Option 2: Manual Installation](#option-2-manual-installation)
  - [Option 3: Clean Install](#option-3-clean-install)
- [Architecture](#how-it-works-architecture)
- [API Reference](#api-endpoint-reference)
- [Usage in Python](#using-the-bridge-in-your-python-app)
- [Troubleshooting](#troubleshooting)
- [Advanced Configuration](#advanced-configuration)

---

## The Linux Issue (Why this exists)

The official `MetaTrader5` Python package is a Windows-only library. It relies heavily on Windows system files (DLLs) and the Windows API to communicate directly with the desktop MT5 terminal.

If you try to import it or run it on Linux, it will fail. This makes it very difficult to deploy automated Python trading bots, real-time data pipelines, or web dashboards to Linux-based cloud servers (like a VPS or Docker container).

**MT5 Linux Bridge solves this problem.** It wraps the Windows-native Python package and the MT5 desktop terminal inside a Wine-configured Docker container, exposing all MT5 functions through a fast, asynchronous FastAPI REST API.

---

## Installation

### Prerequisites

Before you begin, ensure you have:

- ✅ **Linux operating system** with active desktop environment (Ubuntu, Debian, Fedora, etc.)
- ✅ **Docker** (version 20.10 or later)
- ✅ **Docker Compose** (version 1.29 or later)
- ✅ **X11 display server** (usually pre-installed on Linux desktops)
- ✅ **xhost utility** (for X11 permissions)

#### Install Prerequisites

**Ubuntu/Debian:**
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt-get update
sudo apt-get install docker-compose

# Install xhost (for X11 GUI support)
sudo apt-get install x11-xserver-utils

# Add your user to docker group (no sudo needed)
sudo usermod -aG docker $USER
# Log out and back in for this to take effect
```

**Fedora:**
```bash
sudo dnf install docker docker-compose xorg-x11-server-utils
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
```

**Verify Installation:**
```bash
docker --version           # Should show Docker version 20.10+
docker-compose --version   # Should show docker-compose version 1.29+
xhost                      # Should run without errors
```

---

### Option 1: Quick Start (Recommended)

**Best for:** First-time users, quick testing, demos

```bash
# 1. Clone repository
git clone <your-repo-url>
cd MT5Bridge_Linux

# 2. Run quick start script (handles everything automatically)
./quickstart.sh
```

**What it does:**
- ✅ Checks prerequisites (Docker, Docker Compose)
- ✅ Configures X11 permissions automatically
- ✅ Builds Docker image
- ✅ Starts the bridge container
- ✅ Shows logs in real-time

**Expected Output:**
```
🚀 MT5 Bridge Quick Start
================================
✅ Docker and Docker Compose found
✅ X11 access configured
   DISPLAY: :0
🏗️  Building and starting MT5 Bridge...
✅ MT5 Bridge is starting!

📖 What Happens Next
1️⃣  Wine environment is being initialized
2️⃣  MT5 installer window will appear on your screen
3️⃣  Complete the MT5 installation manually
4️⃣  Bridge will start automatically after installation
5️⃣  API will be available at http://localhost:8217
```

**Next Steps:**
1. Wait 2-3 minutes for Wine initialization
2. **MT5 installer window appears** - Complete the installation
3. Wait for "✅ Wine is working" in logs
4. API is ready at `http://localhost:8217/docs`

---

### Option 2: Manual Installation

**Best for:** Developers, custom configurations, integration into larger projects

#### Step 1: Configure X11 Access

The MT5 installer requires GUI access to your screen:

```bash
# Allow Docker containers to access your display
xhost +local:docker
```

**To make this permanent** (survives reboots):
```bash
echo "xhost +local:docker" >> ~/.bashrc
```

#### Step 2: Build and Start

```bash
# Build the Docker image
docker-compose build

# Start the container
docker-compose up -d

# Follow logs
docker-compose logs -f
```

#### Step 3: Complete MT5 Installation

1. Within 2-3 minutes, the **MetaTrader 5 Installation Wizard** will pop up on your desktop
2. Click "Next" through the installer
3. Wait for installation to complete (1-2 minutes)
4. The installer will close automatically
5. Bridge will start the FastAPI server

#### Step 4: Verify Installation

```bash
# Check container status
docker-compose ps

# Check health
docker inspect --format='{{.State.Health.Status}}' mt5-bridge
# Should show: healthy

# Test API
curl http://localhost:8217/test
# Response: {"time": "2026-07-05 12:34:56"}
```

---

### Option 3: Clean Install

**Best for:** Troubleshooting, corrupted Wine prefix, starting fresh

If Wine gets corrupted or you want to completely reset:

```bash
# Stop and remove everything (including Wine installation)
./rebuild.sh clean

# Or manually:
docker-compose down
docker volume rm mt5bridge_linux_wine_prefix
docker-compose up --build -d
```

This removes the Wine environment and MT5 installation. You'll need to complete the MT5 installer again.

---

## How It Works (Architecture)

```
┌────────────────────────────────────────────────────────┐
│                     Linux Host                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │                 Docker Container                 │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │                  Wine 10                   │  │  │
│  │  │  ┌─────────────────┐  ┌─────────────────┐  │  │  │
│  │  │  │  FastAPI Server │  │   MT5 Terminal  │  │  │  │
│  │  │  │ (Windows Python)│◄─►│  (terminal64)  │  │  │  │
│  │  │  └────────┬────────┘  └─────────────────┘  │  │  │
│  │  └───┬───────┼────────────────────────────────┘  │  │
│  └──────┼───────┼───────────────────────────────────┘  │
│         │       │                                      │
│   HTTP  │       │  X11 Display Socket                  │
│  (Port) │       └──(During Installer GUI setup Only)──►│ (Host Screen)
└─────────┼──────────────────────────────────────────────┘
          ▼
   (Your Application)
```

### Components:

1. **Docker Container**: Runs Debian with Wine 10 installed
2. **Wine Environment**: Windows compatibility layer for running MT5 on Linux
3. **Windows Python 3.10**: Embedded Python that can import the official `MetaTrader5` library
4. **FastAPI Server**: REST API exposing all MT5 functions
5. **MT5 Terminal**: Official MetaTrader 5 desktop application
6. **X11 Socket**: For GUI display during initial setup

### Thread Safety:
MT5 terminal is not thread-safe. The FastAPI server uses a single-threaded background worker (`ThreadPoolExecutor` with `max_workers=1`) to ensure all MT5 operations are sequential while keeping the API asynchronous.

---

## API Endpoint Reference

The API is fully documented with interactive Swagger docs available at `http://localhost:8217/docs` when the bridge is running.

### Base URL
```
http://localhost:8217
```

### 1. Connection & Lifecycle

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/install` | POST | Launch MT5 installer (if auto-install failed) |
| `/initialize` | POST | Connect to broker with credentials |
| `/shutdown` | POST | Disconnect and close MT5 terminal |

**Example: Initialize MT5**
```bash
curl -X POST http://localhost:8217/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "login": 12345678,
    "password": "your_password",
    "server": "Broker-Server-Name"
  }'
```

### 2. Status & Account Information

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/test` | GET | Health check (returns server time) |
| `/status` | GET | MT5 connection status |
| `/get_account_info` | GET | Account balance, equity, leverage, etc. |

**Example: Get Account Info**
```bash
curl http://localhost:8217/get_account_info
```

### 3. Market Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/rates/from` | POST | Fetch OHLC bars from specific date/position |
| `/rates/range` | POST | Fetch OHLC bars between two dates |
| `/ticks/from` | POST | Fetch tick data from timestamp |
| `/ticks/range` | POST | Fetch ticks between two timestamps |

**Example: Fetch Candles**
```bash
curl -X POST http://localhost:8217/rates/from \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "EURUSD",
    "timeframe": "H1",
    "count": 100
  }'
```

### 4. Trading Operations

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/trade/open` | POST | Open market order (BUY/SELL) |
| `/trade/close` | POST | Close position by ticket ID |
| `/trade/close_all` | POST | Close all positions |
| `/trade/pending` | POST | Place pending order (LIMIT/STOP) |
| `/trade/modify_position` | POST | Modify SL/TP of position |
| `/trade/modify_order` | POST | Modify pending order |
| `/trade/cancel_order` | POST | Cancel pending order |

**Example: Open Trade**
```bash
curl -X POST http://localhost:8217/trade/open \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "EURUSD",
    "order_type": "BUY",
    "volume": 0.1,
    "sl": 1.0800,
    "tp": 1.0900
  }'
```

### 5. Symbols & Information

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/symbols` | GET | List all active symbols |
| `/symbols/total` | GET | Total symbol count |
| `/symbol/info` | POST | Get symbol specifications |
| `/symbol/tick` | POST | Get latest tick |
| `/symbol/select` | POST | Enable/disable symbol in Market Watch |

### 6. History

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/history/deals` | POST | Get completed deals in date range |
| `/history/deals/total` | POST | Count completed deals |
| `/history/orders` | POST | Get order history |
| `/history/orders/total` | POST | Count historical orders |

### 7. Economic Calendar

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/calendar/health` | GET | Calendar data status |
| `/calendar/countries` | GET | List all countries |
| `/calendar/events` | GET | Get economic events |
| `/calendar/values/recent` | GET | Recent economic releases |
| `/calendar/values/upcoming` | GET | Upcoming economic events |
| `/calendar/search` | GET | Search calendar by keyword |

---

## Using the Bridge in Your Python App

The bridge works like a drop-in replacement for the official `MetaTrader5` Python library. Instead of calling `mt5.copy_rates_from(...)` directly, your code calls the bridge's HTTP endpoint.

### Quick Example

```python
import asyncio
import httpx

async def main():
    base_url = "http://localhost:8217"
    
    # 1. Initialize MT5
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/initialize",
            json={
                "login": 12345678,
                "password": "your_password",
                "server": "YourBroker-Server"
            }
        )
        print(response.json())
    
    # 2. Fetch candle data
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/rates/from",
            json={
                "symbol": "EURUSD",
                "timeframe": "H1",
                "count": 100
            }
        )
        candles = response.json()
        print(f"Fetched {len(candles)} candles")
    
    # 3. Get account info
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url}/get_account_info")
        account = response.json()
        print(f"Balance: ${account['balance']}")

asyncio.run(main())
```

### Using the Included Service Client

We provide a ready-made Python client (`mt5_service.py`) that wraps all API endpoints:

```python
import asyncio
from mt5_service import MT5Service

async def main():
    mt5 = MT5Service(host="localhost", port=8217)
    
    # Initialize
    await mt5.initialize_mt5(
        login=12345678,
        password="your_password",
        server="YourBroker-Demo"
    )
    
    # Fetch data
    data = await mt5.fetch_ohlcv_v2("EURUSD", timeframe="H1", count=100)
    print(data)
    
    # Get account
    account = await mt5.get_account_info()
    print(f"Balance: {account['balance']}")

asyncio.run(main())
```

---

## Troubleshooting

### Issue: No MT5 Installer Window Appears

**Symptoms:**
- Container starts but no GUI window shows
- Logs show `⚠️ Host Display connection failed`

**Solutions:**

1. **Enable X11 access:**
   ```bash
   xhost +local:docker
   echo $DISPLAY  # Should show :0 or :1
   ```

2. **Check DISPLAY variable:**
   ```bash
   # In docker-compose.yml, ensure:
   environment:
     - DISPLAY=${DISPLAY:-:0}
   ```

3. **Restart container:**
   ```bash
   docker-compose restart
   ```

### Issue: Wine Test Fails / kernel32.dll Error

**Symptoms:**
```
❌ Wine is broken or prefix is corrupted
wine: could not load kernel32.dll
```

**Solution:**
```bash
# Clean rebuild (removes Wine prefix)
./rebuild.sh clean

# Or manually:
docker-compose down
docker volume rm mt5bridge_linux_wine_prefix
docker-compose up --build -d
```

### Issue: Container Keeps Restarting

**Check logs:**
```bash
docker-compose logs -f
```

**Common causes:**
1. Wine initialization timeout (wait 5-6 minutes on first run)
2. Missing X11 permissions (run `xhost +local:docker`)
3. DISPLAY variable not set (export DISPLAY=:0)

### Issue: API Returns 503 Service Unavailable

**Symptoms:**
```bash
curl http://localhost:8217/test
# Connection refused or 503 error
```

**Solutions:**

1. **Wait for initialization:**
   ```bash
   docker-compose logs -f
   # Look for: "✅ All initialization complete!"
   ```

2. **Check container health:**
   ```bash
   docker inspect --format='{{.State.Health.Status}}' mt5-bridge
   # Should show: healthy (after 3-6 minutes)
   ```

3. **Verify MT5 is installed:**
   ```bash
   docker exec mt5-bridge ls "/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
   # Should exist after installation
   ```

### Issue: Permission Denied Errors

**Symptoms:**
```
Error response from daemon: permission denied
```

**Solution:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Log out and back in, then verify:
docker ps
```

---

## Advanced Configuration

### Custom Port

Change the host port in `docker-compose.yml`:

```yaml
ports:
  - "9999:5000"  # Use port 9999 instead of 8217
```

### Environment Variables

Create a `.env` file:

```bash
# Display configuration
DISPLAY=:0

# Wine configuration
WINESERVER_TIMEOUT=300
WINEARCH=win64

# API configuration
FLASK_PORT=5000
```

### Resource Limits

Adjust in `docker-compose.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '4'      # Increase CPU
      memory: 8G     # Increase RAM
    reservations:
      cpus: '2'
      memory: 4G
```

### Persistent MT5 Data

Mount MT5 data directory:

```yaml
volumes:
  - wine_prefix:/home/wineuser/.wine
  - mt5_data:/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5
```

---

## Development & Testing

### View Logs
```bash
docker-compose logs -f
docker-compose logs -f --tail=100  # Last 100 lines
```

### Execute Commands in Container
```bash
docker exec -it mt5-bridge bash
wine --version
python3 --version
```

### Test Wine
```bash
docker exec mt5-bridge wine cmd /c ver
```

### Rebuild After Code Changes
```bash
./rebuild.sh              # Fast rebuild with cache
./rebuild.sh --no-cache   # Full rebuild
```

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

## License

This project is licensed under the MIT License - feel free to use, modify, and distribute in your own projects!

---

## Support

- 📖 **Documentation**: See additional docs in this repository
- 🐛 **Issues**: Report bugs via GitHub Issues
- 💬 **Discussions**: Ask questions in GitHub Discussions
- 📧 **Contact**: <your-email@example.com>

---

## Acknowledgments

- [Wine Project](https://www.winehq.org/) - Windows compatibility layer
- [MetaQuotes](https://www.metaquotes.net/) - MetaTrader 5 platform
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework

---

**Made with ❤️ for algorithmic traders on Linux**
