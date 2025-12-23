import subprocess
import time
import requests
import os

# ... existing imports ...
from datetime import datetime, timedelta
import traceback
from flask import Flask, jsonify, request
import MetaTrader5 as mt5
import json
from pathlib import Path
import logging

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route("/install", methods=["POST"])
def install_mt5():
    """Download and install MT5 terminal (will show GUI for user interaction)"""
    try:
        wine_prefix = "/home/wineuser/.wine"
        terminal_unix_path = f"{wine_prefix}/drive_c/Program Files/MetaTrader 5/terminal64.exe"
        
        # Check if already installed
        if os.path.exists(terminal_unix_path):
            logger.info(f"✅ MT5 terminal found at {terminal_unix_path}")
            return jsonify({
                "success": True, 
                "message": "MT5 terminal is already installed", 
                "path": terminal_unix_path,
                "installed": True
            })
        
        # Download MT5 installer
        logger.info("📥 Downloading MT5 installer...")
        installer_url = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
        installer_path = f"{wine_prefix}/drive_c/temp/mt5setup.exe"
        
        os.makedirs(os.path.dirname(installer_path), exist_ok=True)
        
        response = requests.get(installer_url, stream=True, timeout=300)
        response.raise_for_status()
        
        with open(installer_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info("✅ Download complete")
        logger.info("🚀 Starting MT5 installer (GUI will appear)...")
        logger.info("   Please complete the installation in the GUI window that appears")
        
        # Run installer (will show GUI on host display via X11)
        # Using subprocess.Popen to run in background and return immediately
        import subprocess
        subprocess.Popen(
            ["wine", installer_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        return jsonify({
            "success": True,
            "message": "MT5 installer started. Please complete the installation in the GUI window.",
            "path": terminal_unix_path,
            "installed": False,
            "gui_started": True
        })
            
    except Exception as e:
        logger.error(f"Installation error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

# Configuration for Calendar Data
DATA_FOLDER = "/home/daniel-joseph/.wine_mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/CalendarData"


class CalendarDataReader:
    """Handles reading and caching calendar data from JSON files"""

    def __init__(self, data_folder):
        self.data_folder = Path(data_folder)
        self.cache = {}
        self.cache_timestamp = {}

    def read_json_file(self, filename, use_cache=True, cache_duration=300):
        file_path = self.data_folder / filename
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return None

        if use_cache and filename in self.cache:
            cache_age = (datetime.now() - self.cache_timestamp[filename]).seconds
            if cache_age < cache_duration:
                logger.info(f"Returning cached data for {filename}")
                return self.cache[filename]

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.cache[filename] = data
                self.cache_timestamp[filename] = datetime.now()
                logger.info(f"Loaded {filename} from disk")
                return data
        except Exception as e:
            logger.error(f"Error reading {filename}: {str(e)}")
            return None

    def get_countries(self):
        return self.read_json_file("countries.json")

    def get_events(self):
        return self.read_json_file("events.json")

    def get_recent_values(self):
        return self.read_json_file("recent_values.json")

    def get_currency_values(self, currency):
        filename = f"{currency.upper()}_values.json"
        return self.read_json_file(filename)

    def clear_cache(self):
        self.cache = {}
        self.cache_timestamp = {}
        logger.info("Cache cleared")


data_reader = CalendarDataReader(DATA_FOLDER)


@app.route("/initialize", methods=["POST"])
def initialize():
    data = request.get_json()
    login = data.get("login")
    password = data.get("password")
    server = data.get("server")
    # Use Linux path format (works in Wine)
    path = data.get(
        "path",
        "/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    )
    timeout = data.get("timeout", 300)  # Increase default timeout to 300s (5 mins)
    portable = data.get("portable", False)

    if not all([login, password, server]):
        return (
            jsonify({"success": False, "error": "Missing login, password, or server"}),
            400,
        )

    try:
        login = int(login)
    except ValueError:
        return jsonify({"success": False, "error": "Login must be a number"}), 400

    logger.info(f"Initializing MT5 with login={login}, server={server}, path={path}")

    # Retry loop for initialization (Wine often needs a warmup attempt)
    max_retries = 3
    last_error = None
    
    # Aggressive Cleanup: Kill any existing terminal processes first
    try:
        logger.info("🧹 Pre-init cleanup: Killing existing terminal64.exe processes...")
        subprocess.run(["killall", "terminal64.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2) # Give it time to die
    except Exception as e:
        logger.warning(f"Cleanup warning: {e}")

    for attempt in range(max_retries):
        try:
            logger.info(f"Initializing MT5 (Attempt {attempt + 1}/{max_retries})...")
            
            # Ensure path exists
            if not os.path.exists(path):
                logger.error(f"MT5 executable not found at: {path}")
                return jsonify({"success": False, "error": f"MT5 executable not found at {path}"}), 404

            # MANUAL LAUNCH STRATEGY
            # Launch terminal manually with specific flags to ensure it starts correctly in Wine
            # This bypasses issues where mt5.initialize() times out waiting for the GUI
            if attempt == 0: # Only try manual launch on first attempt
                logger.info("🚀 Manually launching terminal process...")
                config_path = os.path.join(os.path.dirname(os.path.dirname(path)), "config", "common.ini")
                
                launch_cmd = [
                    "wine", 
                    path, 
                    "/portable",
                    f"/login:{login}",
                    f"/password:{password}",
                    f"/server:{server}",
                ]
                
                if os.path.exists(config_path):
                     launch_cmd.append(f"/config:{config_path}")
                
                # Verify environment variables
                logger.info(f"Launch env: WINEPREFIX={os.environ.get('WINEPREFIX')}")
                
                # Launch in background
                subprocess.Popen(
                    launch_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                
                # Wait for it to warm up (Wine is slow)
                logger.info("⏳ Waiting 15s for terminal to warm up...")
                time.sleep(15)

            # Now try to attach/initialize
            result = mt5.initialize(
                path=path,
                login=login,
                password=password,
                server=server,
                timeout=timeout,
                portable=True, # Force portable since we launched it that way
            )
            
            if result:
                logger.info("MT5 initialized successfully")
                version = mt5.version()
                logger.info(f"MT5 version: {version}")
                
                # Verify account connection status
                terminal_info = mt5.terminal_info()
                if terminal_info:
                    logger.info(f"Terminal info: {terminal_info}")
                    if terminal_info.connected:
                         logger.info("✅ Terminal connected to broker server")
                    else:
                         logger.warning("⚠️ Terminal initialized but NOT connected to broker server")
                else:
                    # Sometimes info is None immediately after init
                    time.sleep(1)
                    terminal_info = mt5.terminal_info()

                return jsonify({
                    "success": True, 
                    "connected": terminal_info.connected if terminal_info else False,
                    "version": version
                })
            else:
                last_error = mt5.last_error()
                logger.warning(f"MT5 initialization attempt {attempt + 1} failed: {last_error}")
                
                if last_error[0] == -10005: 
                    logger.warning("IPC Timeout detected. Terminal might be stuck.")
                    # Don't kill it immediately, maybe it just needs more time?
                    # But on last attempt, clean up
                    if attempt == max_retries - 1:
                         subprocess.run(["killall", "terminal64.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                time.sleep(3)
        except Exception as e:
            last_error = str(e)
            logger.error(f"MT5 initialization attempt {attempt + 1} exception: {e}")
            logger.error(traceback.format_exc())
            time.sleep(3)

    return jsonify({"success": False, "error": f"Failed after {max_retries} attempts. Last error: {last_error}"}), 500


@app.route("/get_account_info", methods=["GET"])
def get_account_info():
    if not mt5.terminal_info():
        return jsonify({"error": "MT5 terminal not connected"})

    account_info = mt5.account_info()
    if account_info:
        print(f"Account info retrieved: {account_info}")
        return jsonify(account_info._asdict())
    else:
        error = mt5.last_error()
        print(f"Failed to get account info: {error}")
        return jsonify({"error": f"Failed to get account info: {error}"})


@app.route("/status", methods=["GET"])
def get_status():
    terminal_info = mt5.terminal_info()
    if terminal_info:
        terminal_dict = terminal_info._asdict()
    else:
        terminal_dict = None

    return jsonify(
        {
            "terminal_connected": terminal_dict is not None,
            "terminal_info": terminal_dict,
            "version": mt5.version(),
            "last_error": mt5.last_error(),
        }
    )


@app.route("/get_symbol_info", methods=["POST"])
def get_symbol_info():
    symbol = request.json.get("symbol")
    info = mt5.symbol_info(symbol)
    if info:
        return jsonify(info._asdict())
    else:
        error = mt5.last_error()
        return jsonify({"error": f"Symbol {symbol} not found: {error}"})


@app.route("/get_available_symbols", methods=["GET"])
def get_available_symbols():
    if not mt5.terminal_info():
        return jsonify({"error": "MT5 terminal not connected"}), 503

    symbols = mt5.symbols_get()
    if symbols:
        symbol_names = [s.name for s in symbols]
        return jsonify({"symbols": symbol_names, "count": len(symbol_names)})
    else:
        error = mt5.last_error()
        return jsonify({"error": f"Failed to get symbols: {error}"}), 500


@app.route("/copy_rates_range", methods=["POST"])
def copy_rates_range():
    data = request.json
    symbol = data.get("symbol")
    timeframe = data.get("timeframe")
    date_from = data.get("date_from")
    date_to = data.get("date_to")

    rates = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
    if rates is not None and len(rates) > 0:
        return jsonify(rates.tolist())
    else:
        error = mt5.last_error()
        return jsonify({"error": f"Failed to get rates: {error}"})


@app.route("/copy_rates_from", methods=["POST"])
def copy_rates_from():
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        symbol = data.get("symbol", "EURUSD")
        timeframe_str = data.get("timeframe", "H1")
        count = data.get("count", 100)
        date_from_str = data.get("date_from")

        print(
            f"Processing request: symbol={symbol}, timeframe={timeframe_str}, count={count}"
        )

        timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
            "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }

        timeframe = timeframe_map.get(timeframe_str, mt5.TIMEFRAME_H1)

        try:
            if date_from_str:
                date_from = datetime.fromisoformat(date_from_str.replace("Z", "+00:00"))
            else:
                date_from = datetime.now()
        except Exception as e:
            return jsonify({"error": f"Invalid date format: {str(e)}"}), 400

        if not mt5.terminal_info():
            return jsonify({"error": "MT5 terminal not connected"}), 503

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return jsonify({"error": f"Symbol {symbol} not found"}), 404

        if not mt5.symbol_select(symbol, True):
            return jsonify({"error": f"Failed to select symbol {symbol}"}), 500

        rates = mt5.copy_rates_from(symbol, timeframe, date_from, count)

        if rates is None:
            error = mt5.last_error()
            return jsonify({"error": f"Failed to get rates: {error}"}), 500

        if len(rates) == 0:
            return jsonify({"error": "No data available for the specified period"}), 404

        print(f"Successfully returning {len(rates)} rates")
        return jsonify(rates.tolist())

    except Exception as e:
        print(f"Exception in copy_rates_from: {str(e)}")
        print(traceback.format_exc())

        return (
            jsonify(
                {
                    "error": "Internal server error",
                    "details": str(e),
                    "type": "exception",
                }
            ),
            500,
        )


@app.route("/copy_ticks_from", methods=["POST"])
def copy_ticks_from():
    try:
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 400

        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        symbol = data.get("symbol", "EURUSD")
        count = data.get("count", 100)
        date_from_str = data.get("date_from")

        print(f"Processing tick request: symbol={symbol}, count={count}")

        try:
            if date_from_str:
                date_from = datetime.fromisoformat(date_from_str.replace("Z", "+00:00"))
            else:
                date_from = datetime.now()
        except Exception as e:
            return jsonify({"error": f"Invalid date format: {str(e)}"}), 400

        if not mt5.terminal_info():
            return jsonify({"error": "MT5 terminal not connected"}), 503

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return jsonify({"error": f"Symbol {symbol} not found"}), 404

        if not mt5.symbol_select(symbol, True):
            return jsonify({"error": f"Failed to select symbol {symbol}"}), 500

        ticks = mt5.copy_ticks_from(symbol, date_from, count, mt5.COPY_TICKS_ALL)

        if ticks is None:
            error = mt5.last_error()
            return jsonify({"error": f"Failed to get ticks: {error}"}), 500

        if len(ticks) == 0:
            return (
                jsonify({"error": "No ticks available for the specified period"}),
                404,
            )

        print(f"Successfully returning {len(ticks)} ticks")
        return jsonify(ticks.tolist())

    except Exception as e:
        print(f"Exception in copy_ticks_from: {str(e)}")
        print(traceback.format_exc())

        return (
            jsonify(
                {
                    "error": "Internal server error",
                    "details": str(e),
                    "type": "exception",
                }
            ),
            500,
        )


@app.route("/get_deals", methods=["POST"])
def get_deals():
    try:
        if not mt5.terminal_info():
            return jsonify({"error": "MT5 terminal not connected"}), 503

        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")

        if not start_date_str or not end_date_str:
            return jsonify({"error": "Missing start_date or end_date"}), 400

        try:
            start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except Exception as e:
            return jsonify({"error": f"Invalid date format: {str(e)}"}), 400

        deals = mt5.history_deals_get(start_date, end_date)

        if deals is None:
            error = mt5.last_error()
            return jsonify({"error": f"Failed to get deals: {error}"}), 500

        deals_list = [deal._asdict() for deal in deals]

        print(f"Successfully returning {len(deals_list)} deals")
        return jsonify(deals_list)

    except Exception as e:
        print(f"Exception in get_deals: {str(e)}")
        print(traceback.format_exc())

        return (
            jsonify(
                {
                    "error": "Internal server error",
                    "details": str(e),
                    "type": "exception",
                }
            ),
            500,
        )


@app.route("/calendar/health", methods=["GET"])
def calendar_health():
    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "data_folder": str(data_reader.data_folder),
            "folder_exists": data_reader.data_folder.exists(),
        }
    )


@app.route("/calendar/countries", methods=["GET"])
def get_calendar_countries():
    data = data_reader.get_countries()
    if data is None:
        return jsonify({"error": "Countries data not available"}), 404
    return jsonify(data)


@app.route("/calendar/events", methods=["GET"])
def get_calendar_events():
    data = data_reader.get_events()
    if data is None:
        return jsonify({"error": "Events data not available"}), 404

    events = data.get("events", [])

    importance = request.args.get("importance")
    if importance:
        events = [e for e in events if e.get("importance") == importance.upper()]

    country_id = request.args.get("country_id")
    if country_id:
        events = [e for e in events if e.get("country_id") == country_id]

    sector = request.args.get("sector")
    if sector:
        events = [e for e in events if e.get("sector") == sector.upper()]

    return jsonify(
        {"timestamp": data.get("timestamp"), "count": len(events), "events": events}
    )


@app.route("/calendar/events/<event_id>", methods=["GET"])
def get_calendar_event_by_id(event_id):
    data = data_reader.get_events()
    if data is None:
        return jsonify({"error": "Events data not available"}), 404

    events = data.get("events", [])
    event = next((e for e in events if e.get("id") == event_id), None)

    if event is None:
        return jsonify({"error": "Event not found"}), 404

    return jsonify(event)


@app.route("/calendar/values/recent", methods=["GET"])
def get_calendar_recent_values():
    data = data_reader.get_recent_values()
    if data is None:
        return jsonify({"error": "Recent values data not available"}), 404

    values = data.get("values", [])

    impact = request.args.get("impact")
    if impact:
        values = [v for v in values if v.get("impact_type") == impact.upper()]

    limit = request.args.get("limit", type=int)
    if limit:
        values = values[:limit]

    return jsonify(
        {
            "timestamp": data.get("timestamp"),
            "start_date": data.get("start_date"),
            "end_date": data.get("end_date"),
            "count": len(values),
            "values": values,
        }
    )


@app.route("/calendar/values/currency/<currency>", methods=["GET"])
def get_calendar_currency_values(currency):
    data = data_reader.get_currency_values(currency)
    if data is None:
        return jsonify({"error": f"Data for currency {currency} not available"}), 404

    return jsonify(data)


@app.route("/calendar/values/upcoming", methods=["GET"])
def get_calendar_upcoming_values():
    limit = request.args.get("limit", 50, type=int)
    data = data_reader.get_recent_values()
    if data is None:
        return jsonify({"error": "Recent values data not available"}), 404

    now = datetime.now()
    values = data.get("values", [])

    upcoming = []
    for v in values:
        try:
            event_time = datetime.strptime(v.get("time", ""), "%Y.%m.%d %H:%M:%S")
            if event_time > now:
                upcoming.append(v)
        except:
            continue

    upcoming.sort(key=lambda x: x.get("time", ""))
    upcoming = upcoming[:limit]

    return jsonify(
        {
            "timestamp": datetime.now().isoformat(),
            "count": len(upcoming),
            "values": upcoming,
        }
    )


@app.route("/calendar/values/high-impact", methods=["GET"])
def get_calendar_high_impact_values():
    values_data = data_reader.get_recent_values()
    if values_data is None:
        return jsonify({"error": "Recent values data not available"}), 404

    events_data = data_reader.get_events()
    if events_data is None:
        return jsonify({"error": "Events data not available"}), 404

    values = values_data.get("values", [])
    events = {e["id"]: e for e in events_data.get("events", [])}

    high_impact = []
    for v in values:
        event_id = v.get("event_id")
        if event_id in events and events[event_id].get("importance") == "HIGH":
            v["event_info"] = events[event_id]
            high_impact.append(v)

    return jsonify(
        {
            "timestamp": datetime.now().isoformat(),
            "count": len(high_impact),
            "values": high_impact,
        }
    )


@app.route("/calendar/search", methods=["GET"])
def search_calendar_events():
    query = request.args.get("q", "").lower()
    if not query:
        return jsonify({"error": "Query parameter 'q' is required"}), 400

    events_data = data_reader.get_events()
    if events_data is None:
        return jsonify({"error": "Events data not available"}), 404

    countries_data = data_reader.get_countries()
    countries = (
        {c["id"]: c for c in countries_data.get("countries", [])}
        if countries_data
        else {}
    )

    events = events_data.get("events", [])
    results = []

    for event in events:
        if query in event.get("name", "").lower():
            country_id = event.get("country_id")
            if country_id in countries:
                event["country_info"] = countries[country_id]
            results.append(event)
            continue

        country_id = event.get("country_id")
        if country_id in countries:
            if query in countries[country_id].get("name", "").lower():
                event["country_info"] = countries[country_id]
                results.append(event)

    return jsonify({"query": query, "count": len(results), "results": results})


@app.route("/calendar/refresh", methods=["POST"])
def refresh_calendar_cache():
    data_reader.clear_cache()
    return jsonify({"status": "success", "message": "Cache cleared successfully"})


@app.route("/test", methods=["GET", "POST"])
def test_endpoint():
    return jsonify(
        {
            "message": "Server is working",
            "method": request.method,
            "timestamp": datetime.now().isoformat(),
        }
    )




if __name__ == "__main__":
    # Don't initialize MT5 on startup - it requires credentials
    # MT5 will be initialized when /initialize endpoint is called
    logger.info("Starting MT5 Bridge Flask server...")
    
    import os
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host=host, port=port, debug=True)
