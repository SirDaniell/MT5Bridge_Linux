import httpx
import json
import os
import asyncio
from datetime import datetime, timedelta, timezone
import pytz
from typing import List, Dict, Optional


class MT5Service:
    """
    MT5 Service client to communicate with the MT5 Bridge Flask server.
    Uses async httpx for non-blocking I/O to support multiple concurrent WebSockets.
    """
    
    _client: Optional[httpx.AsyncClient] = None

    @classmethod
    def get_client(cls) -> httpx.AsyncClient:
        if cls._client is None or cls._client.is_closed:
            cls._client = httpx.AsyncClient(
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=50,
                ),
                timeout=httpx.Timeout(180.0, connect=10.0)
            )
        return cls._client

    def __init__(self, host=None, port=None):
        if host is None:
            host = os.getenv("MT5_HOST", "mt5-bridge")
        if port is None:
            port = int(os.getenv("MT5_PORT", "5000"))
        self.base_url = f"http://{host}:{port}"
        self.client = self.get_client()

        # MT5 timeframe strings
        self.TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
        self.timezone = pytz.timezone("Etc/UTC")
    
    async def close(self):
        """Close the httpx client to free resources."""
        await self.client.aclose()

    async def initialize_mt5(
        self, login, password, server, path=None, timeout=60, portable=False
    ):
        """
        Initializes the MT5 terminal via the bridge server.
        """
        url = f"{self.base_url}/initialize"
        payload = {
            "login": login,
            "password": password,
            "server": server,
            "timeout": timeout,
            "portable": portable,
        }
        if path:
            payload["path"] = path

        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()  # Raise an exception for HTTP errors
            return response.json()
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Connection or request failed: {str(e)}",
            }

    async def shutdown_mt5(self):
        """
        Shuts down the MT5 terminal via the bridge server.
        """
        url = f"{self.base_url}/shutdown"
        try:
            response = await self.client.post(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Shutdown request failed: {str(e)}",
            }

    async def get_status(self):
        """
        Gets the MT5 terminal connection status from the bridge server.
        """
        url = f"{self.base_url}/status"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {
                "terminal_connected": False,
                "error": f"Connection or request failed: {str(e)}",
            }

    async def get_account_info(self):
        """
        Gets account information from the MT5 terminal via the bridge server.
        """
        url = f"{self.base_url}/get_account_info"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Connection or request failed: {str(e)}"}

    async def get_symbol_info(self, symbol):
        """
        Debug symbol availability and info
        """
        try:
            response = await self.client.post(
                f"{self.base_url}/get_symbol_info", json={"symbol": symbol}
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Connection failed: {str(e)}"}

    async def get_available_symbols(self):
        """
        Gets a list of all available symbols from the MT5 terminal via the bridge server.
        """
        url = f"{self.base_url}/get_available_symbols"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Connection or request failed: {str(e)}"}

    async def fetch_ohlc_data_v2(
        self,
        symbol,
        timeframe="H1",
        count=1000,
        date_from=None,
        method="copy_rates_from",
        reporter=None,
    ):
        """
        Enhanced data fetching with multiple fallback methods
        """

        if method == "copy_rates_from":
            return await self._fetch_using_copy_rates_from(
                symbol, timeframe, count, date_from, reporter
            )
        else:
            return await self._fetch_using_copy_rates_range(
                symbol, timeframe, count, date_from, reporter
            )

    async def _fetch_using_copy_rates_from(self, symbol, timeframe, count, date_from, reporter=None):
        """
        Fetch data using copy_rates_from method with retry logic and exponential backoff
        """

        url = f"{self.base_url}/copy_rates_from"
        data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": count,
            "timeout": 120000,  # 120 seconds - broker must complete fetch
        }
        
        if date_from is not None:
            data["date_from"] = date_from.isoformat() + "Z"  # Ensure ISO format with Z for UTC

        # Retry configuration
        max_attempts = 3
        base_delay = 2  # seconds
        
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                if reporter and attempt > 1:
                    reporter.report(
                        progress=0,
                        message="Retrying MT5 Fetch",
                        message2=f"Connection lost. Retrying bar fetch (attempt {attempt}/{max_attempts})..."
                    )

                # 180 second timeout (3 minutes) for HTTP request to account for:
                # - MT5 broker connection time (variable)
                # - Data transfer time (scales with bar count)
                # - Network latency
                # For 15,000 bars this consistently needs >60 seconds empirically
                response = await self.client.post(url, json=data, timeout=180)
                response.raise_for_status()
                result = response.json()
                
                # Check if result indicates success
                if isinstance(result, list) or (isinstance(result, dict) and result.get("data")):
                    return result
                elif isinstance(result, dict) and result.get("error"):
                    last_error = result.get("error")
                    # Don't retry on certain error types (auth, invalid symbol, etc)
                    if "invalid" in str(last_error).lower() or "not found" in str(last_error).lower():
                        return result
                else:
                    last_error = f"Unexpected response format: {type(result)}"

            except httpx.TimeoutException:
                last_error = f"Request timeout (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))  # Exponential: 2s, 4s, 8s
                    await asyncio.sleep(delay)
                    continue
                    
            except httpx.ConnectError as e:
                last_error = f"Connection error: {e} (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue
                    
            except httpx.RequestError as e:
                last_error = f"Request failed: {e} (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue
        
        # All attempts exhausted
        return {"error": f"Failed after {max_attempts} attempts: {last_error}"}

    async def get_ticks(self, symbol, count):
        """
        Gets tick data for a given symbol.
        """
        url = f"{self.base_url}/copy_ticks_from"
        data = {
            "symbol": symbol,
            "count": count,
        }
        try:
            response = await self.client.post(url, json=data, timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Request failed: {e}"}

    async def _fetch_using_copy_rates_range(self, symbol, timeframe, count, date_from, reporter=None):
        """
        Fetch data using copy_rates_range method (fallback) with retry logic
        """

        # ✅ FIX: Always use UTC to avoid timezone mismatch with MT5 broker.
        # datetime.now() returns naive local time (e.g. EAT = UTC+3 on this host).
        # When serialised as isoformat()+"Z" the bridge treats wall-clock values as
        # UTC, effectively requesting data 3 h in the future on a UTC+3 machine.
        date_to = datetime.now(timezone.utc)
        if date_from is None:
            # Estimate date_from based on timeframe and count
            if timeframe == "M1":
                date_from = date_to - timedelta(minutes=count)
            elif timeframe == "M5":
                date_from = date_to - timedelta(minutes=count * 5)
            elif timeframe == "M15":
                date_from = date_to - timedelta(minutes=count * 15)
            elif timeframe == "M30":
                date_from = date_to - timedelta(minutes=count * 30)
            elif timeframe == "H1":
                date_from = date_to - timedelta(hours=count)
            elif timeframe == "H4":
                date_from = date_to - timedelta(hours=count * 4)
            elif timeframe == "D1":
                date_from = date_to - timedelta(days=count)
            else:
                date_from = date_to - timedelta(days=count)
        else:
            date_to = date_from + timedelta(days=count)  # Rough estimate for range

        # Retry configuration
        max_attempts = 3
        base_delay = 2
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                if reporter and attempt > 1:
                    reporter.report(
                        progress=0,
                        message="Retrying Range Fetch",
                        message2=f"Connection lost. Retrying range fetch (attempt {attempt}/{max_attempts})..."
                    )

                # Strip tzinfo before appending Z: the bridge's _parse_dt replaces
                # "Z" with "+00:00" and calls fromisoformat(), so the wall-clock
                # values must already BE UTC — which they are since we use timezone.utc.
                response = await self.client.post(
                    f"{self.base_url}/copy_rates_range",
                    json={
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "date_from": date_from.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                        "date_to": date_to.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
                        "timeout": 120000,  # Broker timeout
                    },
                    timeout=180,  # 180 second HTTP timeout
                )
                response.raise_for_status()
                result = response.json()
                
                # Check if result indicates success
                if isinstance(result, list) or (isinstance(result, dict) and result.get("data")):
                    return result
                elif isinstance(result, dict) and result.get("error"):
                    last_error = result.get("error")
                    # Don't retry on certain error types
                    if "invalid" in str(last_error).lower() or "not found" in str(last_error).lower():
                        return result
                else:
                    last_error = f"Unexpected response format: {type(result)}"

            except httpx.TimeoutException:
                last_error = f"Request timeout (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue

            except httpx.ConnectError as e:
                last_error = f"Connection error: {e} (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue

            except httpx.RequestError as e:
                last_error = f"Exception in copy_rates_range: {e} (attempt {attempt}/{max_attempts})"
                if attempt < max_attempts:
                    delay = base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    continue

        # All attempts exhausted
        return {"error": f"Failed after {max_attempts} attempts: {last_error}"}


    async def get_new_ticks(self, symbol: str, since_msc: int = 0) -> List[Dict]:
        """
        Fetches new ticks since the given millisecond timestamp.
        If since_msc=0, fetches the most recent tick(s).

        @param symbol - Trading symbol (e.g., "EURUSD")
        @param since_msc - Last tick's time_msc (milliseconds since epoch)
        @returns - List of new tick dicts

        Implementation uses /copy_ticks_from endpoint with a recent start date if since_msc=0,
        or from the datetime of since_msc. Filters to > since_msc.
        """
        try:
            if since_msc == 0:
                # Get only the very latest ticks
                # Use UTC timestamp to avoid MT5 timezone ambiguity
                start_date_ts = int(datetime.now(timezone.utc).timestamp()) - 10 # Last 10 seconds
                data = {
                    "symbol": symbol,
                    "date_from": start_date_ts,
                    "count": 5,  # Only need the latest few
                }
            else:
                start_date_ts = int(since_msc / 1000.0)
                data = {
                    "symbol": symbol,
                    "date_from": start_date_ts,
                    "count": 10,  # Limit to 10 ticks per poll to avoid UI thrash
                }

            url = f"{self.base_url}/copy_ticks_from"
            response = await self.client.post(url, json=data, timeout=10)
            response.raise_for_status()
            ticks_data = response.json()

            if isinstance(ticks_data, dict) and "error" in ticks_data:
                print(f"Error fetching ticks: {ticks_data['error']}")
                return []

            # Assuming ticks_data is list of [time, bid, ask, last, volume, time_msc, flags, volume_real]
            new_ticks = []
            for tick_array in ticks_data:
                if isinstance(tick_array, (list, tuple)) and len(tick_array) >= 8:
                    tick_dict = {
                        "time": tick_array[0],
                        "bid": tick_array[1],
                        "ask": tick_array[2],
                        "last": tick_array[3],
                        "volume": tick_array[4],
                        "time_msc": tick_array[5],
                        "flags": tick_array[6],
                        "volume_real": tick_array[7],
                    }
                    if since_msc == 0 or tick_dict["time_msc"] > since_msc:
                        new_ticks.append(tick_dict)

            # Sort by time_msc ascending
            new_ticks.sort(key=lambda t: t["time_msc"])
            return new_ticks

        except httpx.RequestError as e:
            print(f"Request error in get_new_ticks: {e}")
            return []
        except Exception as e:
            print(f"Error in get_new_ticks for {symbol}: {e}")
            return []

    async def get_deals(self, start_date: datetime, end_date: datetime):
        """
        Fetches deals from the bridge.
        """
        url = f"{self.base_url}/get_deals"
        payload = {
            "start_date": start_date.isoformat() + "Z",
            "end_date": end_date.isoformat() + "Z",
        }
        try:
            response = await self.client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Failed to get deals: {str(e)}"}

    # Calendar Endpoints (File-based)
    async def get_calendar_health(self):
        url = f"{self.base_url}/calendar/health"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_countries(self):
        url = f"{self.base_url}/calendar/countries"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_events(
        self,
        importance: Optional[str] = None,
        country_id: Optional[str] = None,
        sector: Optional[str] = None,
    ):
        url = f"{self.base_url}/calendar/events"
        params = {"importance": importance, "country_id": country_id, "sector": sector}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_recent_values(
        self, impact: Optional[str] = None, limit: Optional[int] = None
    ):
        url = f"{self.base_url}/calendar/values/recent"
        params = {"impact": impact, "limit": limit}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_currency_values(self, currency: str):
        url = f"{self.base_url}/calendar/values/currency/{currency}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_country_by_id(self, country_id: int):
        url = f"{self.base_url}/calendar/events/{country_id}"  # Assuming event_id is used for country_id in the bridge
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_event_by_id(self, event_id: int):
        url = f"{self.base_url}/calendar/events/{event_id}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_value_by_id(self, value_id: int):
        url = f"{self.base_url}/calendar/values/{value_id}"  # Assuming values endpoint for value_id
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_events_by_currency(self, currency: str):
        url = f"{self.base_url}/calendar/events/currency/{currency}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_value_history_by_event(
        self,
        event_id: int,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ):
        url = f"{self.base_url}/calendar/value_history_by_event/{event_id}"
        params = {"from": from_date, "to": to_date}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_value_last_by_event(
        self, event_id: int, change_id: Optional[int] = 0
    ):
        url = f"{self.base_url}/calendar/value_last_by_event/{event_id}"
        params = {"change_id": change_id}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_value_last(
        self, change_id: Optional[int] = 0, country_code: Optional[str] = None
    ):
        url = f"{self.base_url}/calendar/value_last"
        params = {"change_id": change_id, "country_code": country_code}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_values_upcoming(self, limit: Optional[int] = None):
        url = f"{self.base_url}/calendar/values/upcoming"
        params = {"limit": limit}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_high_impact_values(self):
        url = f"{self.base_url}/calendar/values/high-impact"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_search(self, query: str):
        url = f"{self.base_url}/calendar/search"
        params = {"q": query}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def refresh_calendar_cache(self):
        url = f"{self.base_url}/calendar/refresh"
        try:
            response = await self.client.post(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    # Calendar Endpoints (ZMQ-based)
    async def get_calendar_zmq_country_by_id(self, id: int):
        url = f"{self.base_url}/calendar/zmq/country/{id}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_event_by_id(self, id: int):
        url = f"{self.base_url}/calendar/zmq/event/{id}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_value_by_id(self, id: int):
        url = f"{self.base_url}/calendar/zmq/value/{id}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_events_by_currency(self, currency: str):
        url = f"{self.base_url}/calendar/zmq/events/currency/{currency}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_value_history_by_event(
        self,
        event_id: int,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ):
        url = f"{self.base_url}/calendar/zmq/values/history/{event_id}"
        params = {"from": from_date, "to": to_date}
        params = {k: v for k, v in params.items() if v is not None}
        try:
            response = await self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_value_last_by_event(self, event_id: int):
        url = f"{self.base_url}/calendar/zmq/values/last/event/{event_id}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}

    async def get_calendar_zmq_value_last_by_country(self, country_code: str):
        url = f"{self.base_url}/calendar/zmq/values/last/country/{country_code}"
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            return {"error": f"Error connecting to calendar service: {e}"}
