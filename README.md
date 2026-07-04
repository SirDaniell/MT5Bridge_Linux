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

## Using the Bridge in Your Python App

The bridge works like a drop-in replacement for the official `MetaTrader5` Python library — the only difference is that instead of calling `mt5.copy_rates_from(...)` directly, your code calls the bridge's HTTP endpoint and gets the exact same data back.

Here is how the layers connect:

```
Your Code
    ↓  calls  mt5_service.copy_rates_from("EURUSD", "H1", 100)
MT5Service (mt5_service.py)
    ↓  sends  POST http://localhost:8217/rates/from
MT5 Bridge (Docker container)
    ↓  runs   mt5.copy_rates_from("EURUSD", H1, 100)  ← real Windows MT5 library
MT5 Terminal (Wine)
    ↓  queries your broker's server
Returns candle data all the way back up
```

### Head Start — Use the Included Service File

We have included a ready-made service client at `mt5_service.py` in this repository. Drop it into your project and you are good to go.

**Install the dependency first:**
```bash
pip install httpx
```

**Then use it like this:**

```python
import asyncio
from mt5_service import MT5Service

async def main():
    # Point the service to wherever your bridge is running.
    # Default is localhost:8217 (the port mapped in docker-compose.yml)
    mt5 = MT5Service(host="localhost", port=8217)

    # --- Step 1: Connect to your broker ---
    result = await mt5.initialize_mt5(
        login=12345678,
        password="your_password",
        server="YourBroker-Demo"
    )
    print(result)  # {"success": true, ...}

    # --- Step 2: Fetch candle (bar) data ---
    # This is equivalent to mt5.copy_rates_from("EURUSD", mt5.TIMEFRAME_H1, 100)
    # in the native Windows library
    data = await mt5.fetch_ohlcv_v2("EURUSD", timeframe="H1", count=100)
    print(data)
    # Returns a list of bars, each bar is:
    # [time, open, high, low, close, tick_volume, spread, real_volume]

    # --- Step 3: Get account info ---
    account = await mt5.get_account_info()
    print(account)  # {"balance": 10000.0, "equity": ..., "leverage": 100, ...}

    # --- Step 4: Get the latest live tick ---
    ticks = await mt5.get_ticks("EURUSD", count=5)
    print(ticks)
    # Each tick is: [time, bid, ask, last, volume, time_msc, flags, volume_real]

asyncio.run(main())
```

### Common Operations at a Glance

| What you want to do | Function to call |
|---|---|
| Connect to broker | `mt5.initialize_mt5(login, password, server)` |
| Get account balance | `mt5.get_account_info()` |
| Get candle history | `mt5.fetch_ohlcv_v2(symbol, timeframe, count)` |
| Get latest ticks | `mt5.get_ticks(symbol, count)` |
| Get all symbols | `mt5.get_available_symbols()` |
| Get symbol details | `mt5.get_symbol_info(symbol)` |
| Disconnect cleanly | `mt5.shutdown_mt5()` |

### Environment Variables

If your bridge is running on a remote server or inside Docker on the same machine, you can configure the host using environment variables instead of hardcoding them:

```bash
# Set these in your shell or .env file
export MT5_HOST=localhost
export MT5_PORT=8217
```

The `MT5Service` class reads these automatically, so you do not need to pass `host` and `port` arguments at all:

```python
mt5 = MT5Service()  # Reads MT5_HOST and MT5_PORT from environment
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
