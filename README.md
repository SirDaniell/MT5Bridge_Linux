# MetaTrader 5 (MT5) Linux Bridge

An open-source, lightweight Docker-based bridge that enables the official MetaTrader 5 Python library to run seamlessly on Linux. 

---

## The Linux Issue (Why this exists)

The official `MetaTrader5` Python package is a Windows-only library. It relies heavily on Windows system files (DLLs) and the Windows API to communicate directly with the desktop MT5 terminal. 

If you try to import it or run it on Linux, it will fail. This makes it very difficult to deploy automated Python trading bots, real-time data pipelines, or web dashboards to Linux-based cloud servers (like a VPS or Docker container).

**MT5 Linux Bridge solves this problem.** It wraps the Windows-native Python package and the MT5 desktop terminal inside a Wine-configured Docker container, exposing all MT5 functions through a fast, asynchronous FastAPI REST API.

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
   (External App / SDK)
```

1. **The Container**: Runs a lightweight Debian environment. It installs **Wine 10** (a compatibility layer for running Windows apps on Linux) and downloads an embedded Windows version of Python 3.10.
2. **FastAPI Inside Wine**: We launch a FastAPI REST server *inside* the Wine environment using the Windows-native Python. This allows the server to import the official, unmodified `MetaTrader5` library.
3. **Thread Safety**: The MT5 terminal is not thread-safe. To prevent crashes, our FastAPI server runs all MT5 interactions in a dedicated single-threaded background worker (`ThreadPoolExecutor` with `max_workers=1`). The REST API endpoints remain completely asynchronous and non-blocking.
4. **Display Forwarding**: During the initial setup, we map the host machine's display socket (X11) into the container. This allows the graphical MT5 installation wizard to show up on your screen so you can complete the initial installer steps.

---

## Installation & Setup

### Prerequisites
*   A Linux operating system with an active desktop environment (Ubuntu, Debian, Fedora, etc.).
*   [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) installed.

### Step 1: Configure Host Display Access
Because the MT5 terminal requires a graphical installation wizard on its first launch, you must allow Docker to connect to your screen. 

Run the setup script from the project root directory:
```bash
./setup-x11-access.sh
```
*This script automatically configures your display variables and grants X11 permissions to local Docker containers.*

### Step 2: Start the Bridge Container
Start the container using Docker Compose:
```bash
docker-compose --profile wine up -d mt5-bridge
```
*(Alternatively, you can start the targeted service directly with `docker-compose up -d mt5-bridge`).*

### Step 3: Complete MT5 Installation
1.  A few seconds after the container starts, the official **MetaTrader 5 Installation Wizard** will pop up on your host desktop.
2.  Follow the prompts and click **Next** to complete the installation.
3.  Once the installer closes, the container automatically configures and starts the FastAPI REST server.

### Step 4: Initialize Broker Connection
You can now connect the bridge to your trading account. Send a POST request to `/initialize` with your broker details:

```bash
curl -X POST http://localhost:8217/initialize \
  -H "Content-Type: application/json" \
  -d '{
    "login": 12345678,
    "password": "your_password",
    "server": "Broker-Server-Name"
  }'
```
*(The default port mapped to your host is `8217` as defined in `docker-compose.yml`).*

---

## API Endpoint Reference

The API is fully documented with interactive Swagger docs available at `http://localhost:8217/docs` when the bridge is running.

### 1. Connection & Lifecycle (`/lifecycle`)
Use these endpoints to control the connection to the MT5 application and your broker.

*   `POST /install`: Starts downloading and launching the MT5 setup wizard (only needed if the automatic first-boot wizard fails).
*   `POST /initialize`: Connects the bridge to your broker using account credentials.
*   `POST /shutdown`: Disconnects from the broker and safely closes the MT5 terminal.

### 2. Status & Account Information (`/info`)
Endpoints to check system health and account state.

*   `GET /test`: Check if the bridge REST server is active (returns the server's local time).
*   `GET /status`: Returns whether the MT5 terminal is open and connected to the broker.
*   `GET /get_account_info`: Fetches balance, equity, leverage, margin, and account name.

### 3. Symbol Management (`/symbols`)
Control which trading symbols are visible or active.

*   `GET /symbols`: Lists the names of all active symbols in the Market Watch.
*   `GET /symbols/total`: Returns the total count of symbols available on the broker's server.
*   `POST /symbol/info`: Retrieves detailed specifications for a symbol (like pip size, contract size, and margin currency).
*   `POST /symbol/tick`: Fetches the latest bid/ask tick for a specific symbol.
*   `POST /symbol/select`: Enables or disables a symbol in the Market Watch.

### 4. Historical Market Data (`/market_data`)
Query historical bars (OHLCV) and ticks. Naive UTC timezone format is used for consistency.

*   `POST /rates/from`: Fetches a set number of bars starting from a specific date or position index.
*   `POST /rates/range`: Fetches all bars between a start date and an end date.
*   `POST /ticks/from`: Fetches high-precision tick history starting from a given timestamp.
*   `POST /ticks/range`: Fetches tick history between two timestamps.

### 5. Live Trading Operations (`/trading`)
Execute trades, set stops, and manage pending orders.

*   `POST /trade/open`: Opens a new market execution trade (BUY or SELL) with optional Stop Loss (SL) and Take Profit (TP).
*   `POST /trade/close`: Closes an open position by its ticket ID.
*   `POST /trade/close_all`: Closes all active open positions (can be filtered by symbol).
*   `POST /trade/pending`: Places a pending order (`BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, `SELL_STOP`, `BUY_STOP_LIMIT`, `SELL_STOP_LIMIT`).
*   `POST /trade/modify_position`: Modifies the SL and TP values of an active position.
*   `POST /trade/modify_order`: Modifies the execution price, SL, TP, or expiration of an existing pending order.
*   `POST /trade/cancel_order`: Cancels/deletes an active pending order.

### 6. Trading History (`/history`)
Query historical orders and deals.

*   `POST /history/deals`: Gets completed trades/transactions within a date range.
*   `POST /history/deals/total`: Counts completed transactions within a date range.
*   `POST /history/orders`: Retrieves filled or canceled order history within a date range.
*   `POST /history/orders/total`: Counts order history within a date range.

### 7. Economic Calendar (`/calendar`)
Interact with MT5's built-in economic calendar files.

*   `GET /calendar/health`: Verifies the status of the local MQL5 Calendar files.
*   `GET /calendar/countries`: Lists all countries tracked in the economic calendar.
*   `GET /calendar/events`: Retrieves global economic event list, filterable by importance, country, or sector.
*   `GET /calendar/values/recent`: Fetches recent economic values and releases.
*   `GET /calendar/values/upcoming`: Fetches upcoming scheduled economic indicators.
*   `GET /calendar/search`: Searches calendar events by keyword.

---

## Python Integration Example

If you want to communicate with the MT5 Bridge from another Python application, you can build an asynchronous client class using `httpx`. Below is a clean, practical example demonstrating how to initialize the connection, fetch candle data with retries, and retrieve live ticks.

```python
import asyncio
import httpx
from datetime import datetime, timezone

class MT5BridgeClient:
    def __init__(self, host: str = "localhost", port: int = 8217):
        self.base_url = f"http://{host}:{port}"
        # Configure the HTTP client with generous timeouts (highly recommended for large history queries)
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0))

    async def close(self):
        await self.client.aclose()

    async def initialize(self, login: int, password: str, server: str):
        """Initializes the MT5 terminal and connects to the broker."""
        url = f"{self.base_url}/initialize"
        payload = {
            "login": login,
            "password": password,
            "server": server
        }
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"success": False, "error": f"Initialization failed: {e}"}

    async def get_status(self):
        """Checks if the bridge is running and connected to the broker."""
        url = f"{self.base_url}/status"
        try:
            response = await self.client.get(url)
            return response.json()
        except httpx.RequestError:
            return {"terminal_connected": False, "error": "Bridge offline"}

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "H1", count: int = 100):
        """Fetches historical OHLCV bar data from the broker."""
        url = f"{self.base_url}/rates/from"
        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": count
        }
        try:
            # The bridge handles requests and offloads them to a safe single-threaded runner
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()  # Returns list of bar lists
        except httpx.RequestError as e:
            return {"error": f"Failed to fetch market data: {e}"}

    async def get_latest_ticks(self, symbol: str, count: int = 5):
        """Fetches the latest real-time ticks for a symbol."""
        url = f"{self.base_url}/ticks/from"
        payload = {
            "symbol": symbol,
            "count": count
        }
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Failed to fetch ticks: {e}"}

# Quick async execution example
async def main():
    client = MT5BridgeClient(host="localhost", port=8217)
    
    # 1. Check status
    print("Checking bridge status...")
    status = await client.get_status()
    print("Status:", status)

    # 2. Connect (Replace with actual demo credentials)
    # print("Initializing broker connection...")
    # conn = await client.initialize(login=50098765, password="password123", server="Broker-Demo")
    # print("Connection result:", conn)

    # 3. Fetch recent candles
    print("Fetching last 5 EURUSD hourly candles...")
    candles = await client.fetch_ohlcv("EURUSD", "H1", 5)
    print("Candles:", candles)

    # 4. Fetch ticks
    print("Fetching last 3 ticks for EURUSD...")
    ticks = await client.get_latest_ticks("EURUSD", 3)
    print("Ticks:", ticks)

    await client.close()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Troubleshooting

### 1. IPC Timeout Error
*   **Symptom**: The initialization endpoint returns an error indicating MT5 cannot connect or times out.
*   **Solution**: MT5 is likely running but is blocked by a popup window (e.g. an update prompt or a login modal). Open your host screen, check if the MT5 GUI window has an open dialog box, and close or complete it.

### 2. "Cannot Open Display" / X11 connection failures
*   **Symptom**: The container log displays `Cannot connect to X server`.
*   **Solution**: Run `xhost +local:docker` on the host machine to allow Docker containers to access your graphic socket. Make sure your `DISPLAY` environment variable matches the active desktop workspace (usually `:0`).

### 3. Wiping and Resetting a Corrupted Wine Prefix
*   **Symptom**: Wine is broken or crash loops due to corrupted configuration files.
*   **Solution**: Stop the container, delete the local volume/folder storing the Wine prefix (stored in the Docker volume `wine_prefix` or local mounts), and start the container again. It will automatically recreate a fresh prefix and download the MT5 installer.

---

## License

This project is licensed under the MIT License - feel free to use, modify, and distribute it in your own projects!
