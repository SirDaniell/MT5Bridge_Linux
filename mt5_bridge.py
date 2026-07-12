"""
MT5 Bridge — FastAPI async rewrite
====================================
Architecture
------------
  MT5Core          – thin synchronous wrapper around every MetaTrader5 API call.
                     All blocking MT5 work runs here; nothing else imports mt5 directly.

  run_in_executor  – every route offloads MT5Core calls to a thread-pool executor so
                     the async event-loop is never blocked.

  CalendarDataReader – unchanged logic, now also runs in executor. Still pending Implementation so note Calendar endpoint will not work yet. 

  FastAPI routers  – one file, grouped by tag for clean /docs.

Run
---
  uvicorn mt5_bridge:app --host 0.0.0.0 --port 5000 --workers 1

  (Keep workers=1 – MetaTrader5 uses a single shared connection per process.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any, Optional

import MetaTrader5 as mt5
import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("mt5_bridge")

# ---------------------------------------------------------------------------
# Thread-pool (MT5 is NOT thread-safe; keep pool size = 1)
# ---------------------------------------------------------------------------
_executor = ThreadPoolExecutor(max_workers=1)


async def in_thread(fn, *args, **kwargs):
    """Run a synchronous callable in the dedicated MT5 thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, partial(fn, *args, **kwargs))


# ===========================================================================
# MT5Core  – full MT5 API wrapper
# ===========================================================================

TIMEFRAME_MAP: dict[str, int] = {
    "M1":  mt5.TIMEFRAME_M1,
    "M2":  mt5.TIMEFRAME_M2,
    "M3":  mt5.TIMEFRAME_M3,
    "M4":  mt5.TIMEFRAME_M4,
    "M5":  mt5.TIMEFRAME_M5,
    "M6":  mt5.TIMEFRAME_M6,
    "M10": mt5.TIMEFRAME_M10,
    "M12": mt5.TIMEFRAME_M12,
    "M15": mt5.TIMEFRAME_M15,
    "M20": mt5.TIMEFRAME_M20,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H2":  mt5.TIMEFRAME_H2,
    "H3":  mt5.TIMEFRAME_H3,
    "H4":  mt5.TIMEFRAME_H4,
    "H6":  mt5.TIMEFRAME_H6,
    "H8":  mt5.TIMEFRAME_H8,
    "H12": mt5.TIMEFRAME_H12,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

ORDER_TYPE_MAP: dict[str, int] = {
    "BUY":             mt5.ORDER_TYPE_BUY,
    "SELL":            mt5.ORDER_TYPE_SELL,
    "BUY_LIMIT":       mt5.ORDER_TYPE_BUY_LIMIT,
    "SELL_LIMIT":      mt5.ORDER_TYPE_SELL_LIMIT,
    "BUY_STOP":        mt5.ORDER_TYPE_BUY_STOP,
    "SELL_STOP":       mt5.ORDER_TYPE_SELL_STOP,
    "BUY_STOP_LIMIT":  mt5.ORDER_TYPE_BUY_STOP_LIMIT,
    "SELL_STOP_LIMIT": mt5.ORDER_TYPE_SELL_STOP_LIMIT,
}

TRADE_ACTION_MAP: dict[str, int] = {
    "DEAL":    mt5.TRADE_ACTION_DEAL,
    "PENDING": mt5.TRADE_ACTION_PENDING,
    "SLTP":    mt5.TRADE_ACTION_SLTP,
    "MODIFY":  mt5.TRADE_ACTION_MODIFY,
    "REMOVE":  mt5.TRADE_ACTION_REMOVE,
    "CLOSE_BY": mt5.TRADE_ACTION_CLOSE_BY,
}


class MT5Core:
    """
    Synchronous wrapper around every public MetaTrader5 function.
    Instances are meant to be used from a single thread (the executor).
    """

    # ------------------------------------------------------------------
    # Connection / lifecycle
    # ------------------------------------------------------------------

    def install(
        self,
        wine_prefix: str = "/home/wineuser/.wine",
    ) -> dict:
        terminal_unix_path = f"{wine_prefix}/drive_c/Program Files/MetaTrader 5/terminal64.exe"
        if os.path.exists(terminal_unix_path):
            return {"success": True, "message": "Already installed", "path": terminal_unix_path, "installed": True}

        installer_url = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
        installer_path = f"{wine_prefix}/drive_c/temp/mt5setup.exe"
        os.makedirs(os.path.dirname(installer_path), exist_ok=True)

        resp = requests.get(installer_url, stream=True, timeout=300)
        resp.raise_for_status()
        with open(installer_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        subprocess.Popen(
            ["wine", installer_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "success": True,
            "message": "Installer started — complete the GUI to finish installation.",
            "path": terminal_unix_path,
            "installed": False,
            "gui_started": True,
        }

    def initialize(
        self,
        login: int,
        password: str,
        server: str,
        path: str = "/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe",
        timeout: int = 600,
        portable: bool = False,
    ) -> dict:
        if not os.path.exists(path):
            raise FileNotFoundError(f"MT5 executable not found at {path}")

        max_retries = 3
        last_error: Any = None

        for attempt in range(max_retries):
            try:
                logger.info("MT5 init attempt %d/%d", attempt + 1, max_retries)

                if attempt == 0:
                    logger.info("Launching terminal process via Wine …")
                    launch_cmd = [
                        "wine", path, "/portable",
                        f"/login:{login}", f"/password:{password}", f"/server:{server}",
                    ]
                    config_path = os.path.join(
                        os.path.dirname(os.path.dirname(path)), "config", "common.ini"
                    )
                    if os.path.exists(config_path):
                        launch_cmd.append(f"/config:{config_path}")

                    subprocess.Popen(
                        launch_cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    logger.info("Waiting 15s for Wine warm-up …")
                    time.sleep(15)

                result = mt5.initialize(
                    path, login=login, password=password,
                    server=server, timeout=timeout, portable=True,
                )

                if result:
                    term = mt5.terminal_info()
                    if term is None:
                        time.sleep(1)
                        term = mt5.terminal_info()
                    return {
                        "success": True,
                        "connected": term.connected if term else False,
                        "version": mt5.version(),
                        "terminal_info": term._asdict() if term else None,
                    }

                last_error = mt5.last_error()
                logger.warning("Init attempt %d failed: %s", attempt + 1, last_error)
                if last_error[0] == -10005 and attempt == max_retries - 1:
                    subprocess.run(
                        ["wineserver", "-k"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                time.sleep(3)

            except Exception as exc:
                last_error = str(exc)
                logger.error("Init attempt %d exception: %s", attempt + 1, exc)
                time.sleep(3)

        return {"success": False, "error": f"Failed after {max_retries} attempts. Last error: {last_error}"}

    def shutdown(self) -> dict:
        mt5.shutdown()
        return {"success": True, "message": "MT5 shutdown OK"}

    # ------------------------------------------------------------------
    # Terminal / account info
    # ------------------------------------------------------------------

    def terminal_info(self) -> dict | None:
        info = mt5.terminal_info()
        return info._asdict() if info else None

    def version(self) -> tuple | None:
        return mt5.version()

    def last_error(self) -> tuple:
        return mt5.last_error()

    def account_info(self) -> dict:
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"account_info failed: {mt5.last_error()}")
        return info._asdict()

    def status(self) -> dict:
        term = mt5.terminal_info()
        return {
            "terminal_connected": term is not None,
            "terminal_info": term._asdict() if term else None,
            "version": mt5.version(),
            "last_error": mt5.last_error(),
        }

    # ------------------------------------------------------------------
    # Symbols
    # ------------------------------------------------------------------

    def symbols_total(self) -> int:
        return mt5.symbols_total()

    def symbols_get(self, group: str | None = None) -> list[dict]:
        syms = mt5.symbols_get(group) if group else mt5.symbols_get()
        if syms is None:
            raise RuntimeError(f"symbols_get failed: {mt5.last_error()}")
        return [s._asdict() for s in syms]

    def symbol_info(self, symbol: str) -> dict:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"symbol_info({symbol}) failed: {mt5.last_error()}")
        return info._asdict()

    def symbol_info_tick(self, symbol: str) -> dict:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"symbol_info_tick({symbol}) failed: {mt5.last_error()}")
        return tick._asdict()

    def symbol_select(self, symbol: str, enable: bool = True) -> bool:
        return mt5.symbol_select(symbol, enable)

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def _resolve_timeframe(self, tf_str: str) -> int:
        tf = TIMEFRAME_MAP.get(tf_str.upper())
        if tf is None:
            raise ValueError(f"Unknown timeframe '{tf_str}'. Valid: {list(TIMEFRAME_MAP)}")
        return tf

    def copy_rates_from(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        count: int,
    ) -> list:
        tf = self._resolve_timeframe(timeframe)
        self._ensure_symbol(symbol)
        
        # Clamp count to terminal maxbars and available series bars to prevent "Invalid params" (-2)
        term_info = mt5.terminal_info()
        if term_info is not None and hasattr(term_info, 'maxbars') and term_info.maxbars > 0:
            count = min(count, term_info.maxbars)
            
        series_info = mt5.series_info(symbol, tf)
        if series_info is not None and hasattr(series_info, 'bars_count') and series_info.bars_count > 0:
            count = min(count, series_info.bars_count)
            
        # MT5 can return None transiently when the terminal is busy (e.g. during
        # concurrent requests routed through the single-thread executor).
        # Retry up to 3 times with short back-off before raising.
        for attempt in range(3):
            rates = mt5.copy_rates_from(symbol, tf, date_from, count)
            if rates is not None:
                return rates.tolist()
            if attempt < 2:
                time.sleep(0.5)
        raise RuntimeError(f"copy_rates_from failed after 3 attempts: {mt5.last_error()}")

    def copy_rates_from_pos(
        self,
        symbol: str,
        timeframe: str,
        start_pos: int,
        count: int,
    ) -> list:
        tf = self._resolve_timeframe(timeframe)
        self._ensure_symbol(symbol)
        
        # Clamp count to terminal maxbars and available series bars to prevent "Invalid params" (-2)
        term_info = mt5.terminal_info()
        if term_info is not None and hasattr(term_info, 'maxbars') and term_info.maxbars > 0:
            count = min(count, term_info.maxbars)
            
        series_info = mt5.series_info(symbol, tf)
        if series_info is not None and hasattr(series_info, 'bars_count') and series_info.bars_count > 0:
            count = min(count, series_info.bars_count)
            
        rates = mt5.copy_rates_from_pos(symbol, tf, start_pos, count)
        if rates is None:
            raise RuntimeError(f"copy_rates_from_pos failed: {mt5.last_error()}")
        return rates.tolist()

    def copy_rates_range(
        self,
        symbol: str,
        timeframe: str,
        date_from: datetime,
        date_to: datetime,
    ) -> list:
        tf = self._resolve_timeframe(timeframe)
        self._ensure_symbol(symbol)
        rates = mt5.copy_rates_range(symbol, tf, date_from, date_to)
        if rates is None:
            raise RuntimeError(f"copy_rates_range failed: {mt5.last_error()}")
        return rates.tolist()

    def copy_ticks_from(
        self,
        symbol: str,
        date_from: datetime,
        count: int,
        flags: int = mt5.COPY_TICKS_ALL,
    ) -> list:
        self._ensure_symbol(symbol)
        ticks = mt5.copy_ticks_from(symbol, date_from, count, flags)
        if ticks is None:
            raise RuntimeError(f"copy_ticks_from failed: {mt5.last_error()}")
        return ticks.tolist()

    def copy_ticks_range(
        self,
        symbol: str,
        date_from: datetime,
        date_to: datetime,
        flags: int = mt5.COPY_TICKS_ALL,
    ) -> list:
        self._ensure_symbol(symbol)
        ticks = mt5.copy_ticks_range(symbol, date_from, date_to, flags)
        if ticks is None:
            raise RuntimeError(f"copy_ticks_range failed: {mt5.last_error()}")
        return ticks.tolist()

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def orders_total(self) -> int:
        return mt5.orders_total()

    def orders_get(
        self,
        symbol: str | None = None,
        group: str | None = None,
        ticket: int | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol
        if group:
            kwargs["group"] = group
        if ticket:
            kwargs["ticket"] = ticket
        orders = mt5.orders_get(**kwargs)
        if orders is None:
            raise RuntimeError(f"orders_get failed: {mt5.last_error()}")
        return [o._asdict() for o in orders]

    def order_calc_margin(
        self,
        action: str,
        symbol: str,
        volume: float,
        price: float,
    ) -> float:
        act = TRADE_ACTION_MAP.get(action.upper(), mt5.TRADE_ACTION_DEAL)
        margin = mt5.order_calc_margin(act, symbol, volume, price)
        if margin is None:
            raise RuntimeError(f"order_calc_margin failed: {mt5.last_error()}")
        return margin

    def order_calc_profit(
        self,
        action: str,
        symbol: str,
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float:
        order_type = ORDER_TYPE_MAP.get(action.upper(), mt5.ORDER_TYPE_BUY)
        profit = mt5.order_calc_profit(order_type, symbol, volume, price_open, price_close)
        if profit is None:
            raise RuntimeError(f"order_calc_profit failed: {mt5.last_error()}")
        return profit

    def order_check(self, request: dict) -> dict:
        result = mt5.order_check(request)
        if result is None:
            raise RuntimeError(f"order_check failed: {mt5.last_error()}")
        return result._asdict()

    def order_send(self, request: dict) -> dict:
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"order_send failed: {mt5.last_error()}")
        d = result._asdict()
        if hasattr(result, "request") and result.request:
            d["request"] = result.request._asdict()
        return d

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def positions_total(self) -> int:
        return mt5.positions_total()

    def positions_get(
        self,
        symbol: str | None = None,
        group: str | None = None,
        ticket: int | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol
        if group:
            kwargs["group"] = group
        if ticket:
            kwargs["ticket"] = ticket
        positions = mt5.positions_get(**kwargs)
        if positions is None:
            raise RuntimeError(f"positions_get failed: {mt5.last_error()}")
        return [p._asdict() for p in positions]

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def history_orders_total(self, date_from: datetime, date_to: datetime) -> int:
        return mt5.history_orders_total(date_from, date_to)

    def history_orders_get(
        self,
        date_from: datetime,
        date_to: datetime,
        group: str | None = None,
        ticket: int | None = None,
        position: int | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if group:
            kwargs["group"] = group
        if ticket:
            kwargs["ticket"] = ticket
        if position:
            kwargs["position"] = position
        orders = mt5.history_orders_get(date_from, date_to, **kwargs)
        if orders is None:
            raise RuntimeError(f"history_orders_get failed: {mt5.last_error()}")
        return [o._asdict() for o in orders]

    def history_deals_total(self, date_from: datetime, date_to: datetime) -> int:
        return mt5.history_deals_total(date_from, date_to)

    def history_deals_get(
        self,
        date_from: datetime,
        date_to: datetime,
        group: str | None = None,
        ticket: int | None = None,
        position: int | None = None,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {}
        if group:
            kwargs["group"] = group
        if ticket:
            kwargs["ticket"] = ticket
        if position:
            kwargs["position"] = position
        deals = mt5.history_deals_get(date_from, date_to, **kwargs)
        if deals is None:
            raise RuntimeError(f"history_deals_get failed: {mt5.last_error()}")
        return [d._asdict() for d in deals]

    # ------------------------------------------------------------------
    # Trading helpers (convenience wrappers)
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float | None = None,
        sl: float = 0.0,
        tp: float = 0.0,
        deviation: int = 20,
        magic: int = 0,
        comment: str = "",
        type_filling: int = mt5.ORDER_FILLING_IOC,
    ) -> dict:
        """Market or instant execution open."""
        ot = ORDER_TYPE_MAP.get(order_type.upper())
        if ot is None:
            raise ValueError(f"Unknown order_type '{order_type}'")

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Cannot get tick for {symbol}")

        if price is None:
            price = tick.ask if ot == mt5.ORDER_TYPE_BUY else tick.bid

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(volume),
            "type":         ot,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    deviation,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": type_filling,
        }
        return self.order_send(request)

    def close_position(self, ticket: int, deviation: int = 20, comment: str = "close") -> dict:
        """Close an open position by ticket."""
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f"Position {ticket} not found")
        pos = positions[0]

        close_type = (
            mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        )
        tick = mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            raise RuntimeError(f"Cannot get tick for {pos.symbol}")
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       pos.symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    deviation,
            "magic":        pos.magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        return self.order_send(request)

    def close_all_positions(self, symbol: str | None = None, deviation: int = 20) -> list[dict]:
        """Close all open positions, optionally filtered by symbol."""
        kwargs: dict[str, Any] = {}
        if symbol:
            kwargs["symbol"] = symbol
        positions = mt5.positions_get(**kwargs) or []
        results = []
        for pos in positions:
            try:
                results.append(self.close_position(pos.ticket, deviation))
            except Exception as exc:
                results.append({"ticket": pos.ticket, "error": str(exc)})
        return results

    def place_pending_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        expiration: datetime | None = None,
        deviation: int = 20,
        magic: int = 0,
        comment: str = "",
        type_filling: int = mt5.ORDER_FILLING_RETURN,
    ) -> dict:
        ot = ORDER_TYPE_MAP.get(order_type.upper())
        if ot is None or ot in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL):
            raise ValueError(f"'{order_type}' is not a pending order type")

        request: dict[str, Any] = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       symbol,
            "volume":       float(volume),
            "type":         ot,
            "price":        price,
            "sl":           sl,
            "tp":           tp,
            "deviation":    deviation,
            "magic":        magic,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC if expiration is None else mt5.ORDER_TIME_SPECIFIED,
            "type_filling": type_filling,
        }
        if expiration:
            request["expiration"] = int(expiration.timestamp())
        return self.order_send(request)

    def modify_position(
        self,
        ticket: int,
        sl: float = 0.0,
        tp: float = 0.0,
    ) -> dict:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f"Position {ticket} not found")
        pos = positions[0]
        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "symbol":   pos.symbol,
            "position": ticket,
            "sl":       sl,
            "tp":       tp,
        }
        return self.order_send(request)

    def modify_order(
        self,
        ticket: int,
        price: float,
        sl: float = 0.0,
        tp: float = 0.0,
        expiration: datetime | None = None,
    ) -> dict:
        orders = mt5.orders_get(ticket=ticket)
        if not orders:
            raise RuntimeError(f"Order {ticket} not found")
        o = orders[0]
        request: dict[str, Any] = {
            "action":    mt5.TRADE_ACTION_MODIFY,
            "symbol":    o.symbol,
            "order":     ticket,
            "price":     price,
            "sl":        sl,
            "tp":        tp,
            "type_time": mt5.ORDER_TIME_GTC if expiration is None else mt5.ORDER_TIME_SPECIFIED,
        }
        if expiration:
            request["expiration"] = int(expiration.timestamp())
        return self.order_send(request)

    def cancel_order(self, ticket: int) -> dict:
        orders = mt5.orders_get(ticket=ticket)
        if not orders:
            raise RuntimeError(f"Order {ticket} not found")
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order":  ticket,
        }
        return self.order_send(request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_symbol(self, symbol: str) -> None:
        # MT5's COM/Wine layer occasionally returns None on the first call when
        # the terminal is busy processing a previous request.  Retry a few times
        # with a short sleep before giving up so transient load doesn't cause 500s.
        for attempt in range(3):
            info = mt5.symbol_info(symbol)
            if info is not None:
                mt5.symbol_select(symbol, True)
                return
            if attempt < 2:
                time.sleep(0.3)
        raise RuntimeError(f"Symbol '{symbol}' not found (3 attempts, last error: {mt5.last_error()})")

    def _ensure_connected(self) -> None:
        if mt5.terminal_info() is None:
            raise RuntimeError("MT5 terminal not connected. Call /initialize first.")


# Module-level singleton
core = MT5Core()


# ===========================================================================
# CalendarDataReader  (unchanged logic)
# ===========================================================================

DATA_FOLDER = os.getenv(
    "CALENDAR_DATA_FOLDER",
    "/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/MQL5/Files/CalendarData",
)


class CalendarDataReader:
    def __init__(self, folder: str):
        self.data_folder = Path(folder)
        self.cache: dict[str, Any] = {}
        self.cache_timestamp: dict[str, datetime] = {}

    def read_json_file(
        self, filename: str, use_cache: bool = True, cache_duration: int = 300
    ) -> Any | None:
        path = self.data_folder / filename
        if not path.exists():
            return None
        if use_cache and filename in self.cache:
            age = (datetime.now() - self.cache_timestamp[filename]).seconds
            if age < cache_duration:
                return self.cache[filename]
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.cache[filename] = data
            self.cache_timestamp[filename] = datetime.now()
            return data
        except Exception as exc:
            logger.error("Error reading %s: %s", filename, exc)
            return None

    def get_countries(self):       return self.read_json_file("countries.json")
    def get_events(self):          return self.read_json_file("events.json")
    def get_recent_values(self):   return self.read_json_file("recent_values.json")
    def get_currency_values(self, currency: str): return self.read_json_file(f"{currency.upper()}_values.json")
    def clear_cache(self):
        self.cache.clear()
        self.cache_timestamp.clear()


calendar_reader = CalendarDataReader(DATA_FOLDER)


# ===========================================================================
# Pydantic request / response models
# ===========================================================================

class InstallRequest(BaseModel):
    wine_prefix: str = "/home/wineuser/.wine"


class InitializeRequest(BaseModel):
    login:    int
    password: str
    server:   str
    path:     str = "/home/wineuser/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe"
    timeout:  int = 600
    portable: bool = False


class SymbolRequest(BaseModel):
    symbol: str


class RatesFromRequest(BaseModel):
    symbol:    str = "EURUSD"
    timeframe: str = "H1"
    count:     int = 100
    date_from: Optional[str] = None  # ISO-8601 or None → copy_rates_from_pos


class RatesRangeRequest(BaseModel):
    symbol:    str
    timeframe: str = "H1"
    date_from: str
    date_to:   str


class TicksFromRequest(BaseModel):
    symbol:    str = "EURUSD"
    count:     int = 100
    # date_from accepts ISO string, unix timestamp (int/float), or None (→ latest ticks)
    # flags is intentionally excluded — old callers never send it; always use COPY_TICKS_ALL
    date_from: Optional[Any] = None


class TicksRangeRequest(BaseModel):
    symbol:    str
    date_from: str
    date_to:   str
    flags:     int = mt5.COPY_TICKS_ALL


class DealsRequest(BaseModel):
    start_date: str
    end_date:   str
    group:      Optional[str] = None
    ticket:     Optional[int] = None
    position:   Optional[int] = None


class HistoryOrdersRequest(BaseModel):
    start_date: str
    end_date:   str
    group:      Optional[str] = None
    ticket:     Optional[int] = None
    position:   Optional[int] = None


class OpenPositionRequest(BaseModel):
    symbol:       str
    order_type:   str = Field(..., description="BUY or SELL")
    volume:       float
    price:        Optional[float] = None
    sl:           float = 0.0
    tp:           float = 0.0
    deviation:    int   = 20
    magic:        int   = 0
    comment:      str   = ""
    type_filling: int   = mt5.ORDER_FILLING_IOC


class ClosePositionRequest(BaseModel):
    ticket:    int
    deviation: int = 20
    comment:   str = "close"


class CloseAllRequest(BaseModel):
    symbol:    Optional[str] = None
    deviation: int = 20


class PendingOrderRequest(BaseModel):
    symbol:       str
    order_type:   str = Field(..., description="BUY_LIMIT | SELL_LIMIT | BUY_STOP | SELL_STOP | BUY_STOP_LIMIT | SELL_STOP_LIMIT")
    volume:       float
    price:        float
    sl:           float = 0.0
    tp:           float = 0.0
    expiration:   Optional[str] = None
    deviation:    int   = 20
    magic:        int   = 0
    comment:      str   = ""
    type_filling: int   = mt5.ORDER_FILLING_RETURN


class ModifyPositionRequest(BaseModel):
    ticket: int
    sl:     float = 0.0
    tp:     float = 0.0


class ModifyOrderRequest(BaseModel):
    ticket:     int
    price:      float
    sl:         float = 0.0
    tp:         float = 0.0
    expiration: Optional[str] = None


class CancelOrderRequest(BaseModel):
    ticket: int


class RawOrderRequest(BaseModel):
    """Pass a fully-formed MT5 trade request dict directly."""
    request: dict


class OrdersGetRequest(BaseModel):
    symbol: Optional[str] = None
    group:  Optional[str] = None
    ticket: Optional[int] = None


class PositionsGetRequest(BaseModel):
    symbol: Optional[str] = None
    group:  Optional[str] = None
    ticket: Optional[int] = None


class MarginCalcRequest(BaseModel):
    action: str = "DEAL"
    symbol: str
    volume: float
    price:  float


class ProfitCalcRequest(BaseModel):
    action:      str = "BUY"
    symbol:      str
    volume:      float
    price_open:  float
    price_close: float


# ===========================================================================
# FastAPI app
# ===========================================================================

app = FastAPI(
    title="MT5 Bridge",
    description="Async FastAPI wrapper around MetaTrader5",
    version="2.0.0",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(s: str) -> datetime:
    """
    Parse an ISO-8601 string (with or without trailing Z / +HH:MM) and return
    a **naive UTC** datetime.

    Why naive?  The MT5 Python library converts datetimes to Unix timestamps via
    ``calendar.timegm(dt.timetuple())``.  ``timetuple()`` discards ``tzinfo``, so
    only the *wall-clock values* matter.  Returning a naive UTC datetime makes the
    intent explicit and avoids any risk of the library misreading a local-time
    datetime as UTC.

    Callers must ensure the string represents UTC time (append "Z" before calling).
    """
    aware = datetime.fromisoformat(s.replace("Z", "+00:00"))
    # Strip tzinfo: MT5 API ignores it anyway; naive UTC is unambiguous.
    return aware.replace(tzinfo=None)


def _mt5_check():
    if mt5.terminal_info() is None:
        raise HTTPException(status_code=503, detail="MT5 terminal not connected")



# ---------------------------------------------------------------------------
# Installation & lifecycle
# ---------------------------------------------------------------------------

@app.post("/install", tags=["lifecycle"])
async def install(body: InstallRequest):
    try:
        return await in_thread(core.install, body.wine_prefix)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/initialize", tags=["lifecycle"])
async def initialize(body: InitializeRequest):
    result = await in_thread(
        core.initialize,
        body.login, body.password, body.server,
        body.path, body.timeout, body.portable,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error"))
    return result


@app.post("/shutdown", tags=["lifecycle"])
async def shutdown():
    return await in_thread(core.shutdown)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@app.get("/status", tags=["info"])
async def get_status():
    return await in_thread(core.status)


@app.get("/get_account_info", tags=["info"])
async def get_account_info():
    _mt5_check()
    try:
        return await in_thread(core.account_info)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/test", tags=["info"])
async def test():
    return {"message": "Server is running", "timestamp": datetime.now().isoformat()}


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

@app.get("/symbols", tags=["symbols"])
async def get_symbols(group: Optional[str] = Query(None)):
    _mt5_check()
    try:
        syms = await in_thread(core.symbols_get, group)
        return {"count": len(syms), "symbols": [s["name"] for s in syms]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/symbols/total", tags=["symbols"])
async def symbols_total():
    _mt5_check()
    return {"total": await in_thread(core.symbols_total)}


@app.post("/symbol/info", tags=["symbols"])
async def get_symbol_info(body: SymbolRequest):
    _mt5_check()
    try:
        return await in_thread(core.symbol_info, body.symbol)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/symbol/tick", tags=["symbols"])
async def get_symbol_tick(body: SymbolRequest):
    _mt5_check()
    try:
        return await in_thread(core.symbol_info_tick, body.symbol)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/symbol/select", tags=["symbols"])
async def symbol_select(body: SymbolRequest, enable: bool = True):
    _mt5_check()
    ok = await in_thread(core.symbol_select, body.symbol, enable)
    return {"success": ok}


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@app.post("/rates/from", tags=["market_data"])
async def copy_rates_from(body: RatesFromRequest):
    _mt5_check()
    try:
        if body.date_from is None:
            data = await in_thread(
                core.copy_rates_from_pos, body.symbol, body.timeframe, 0, body.count
            )
        else:
            dt = _parse_dt(body.date_from)
            data = await in_thread(
                core.copy_rates_from, body.symbol, body.timeframe, dt, body.count
            )
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/rates/range", tags=["market_data"])
async def copy_rates_range(body: RatesRangeRequest):
    _mt5_check()
    try:
        data = await in_thread(
            core.copy_rates_range,
            body.symbol, body.timeframe,
            _parse_dt(body.date_from), _parse_dt(body.date_to),
        )
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ticks/from", tags=["market_data"])
async def copy_ticks_from(body: TicksFromRequest):
    _mt5_check()
    try:
        # Mirror old Flask logic: accept unix timestamp (int/float), ISO string, or None
        if body.date_from is None:
            date_from = datetime.now(timezone.utc)
        elif isinstance(body.date_from, (int, float)):
            date_from = int(body.date_from)
        else:
            date_from = _parse_dt(str(body.date_from))
        data = await in_thread(
            core.copy_ticks_from, body.symbol, date_from, body.count, mt5.COPY_TICKS_ALL
        )
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ticks/range", tags=["market_data"])
async def copy_ticks_range(body: TicksRangeRequest):
    _mt5_check()
    try:
        data = await in_thread(
            core.copy_ticks_range,
            body.symbol, _parse_dt(body.date_from), _parse_dt(body.date_to), body.flags,
        )
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------

@app.get("/positions/total", tags=["positions"])
async def positions_total():
    _mt5_check()
    return {"total": await in_thread(core.positions_total)}


@app.post("/positions", tags=["positions"])
async def get_positions(body: PositionsGetRequest):
    _mt5_check()
    try:
        return await in_thread(core.positions_get, body.symbol, body.group, body.ticket)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@app.get("/orders/total", tags=["orders"])
async def orders_total():
    _mt5_check()
    return {"total": await in_thread(core.orders_total)}


@app.post("/orders", tags=["orders"])
async def get_orders(body: OrdersGetRequest):
    _mt5_check()
    try:
        return await in_thread(core.orders_get, body.symbol, body.group, body.ticket)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/orders/check", tags=["orders"])
async def order_check(body: RawOrderRequest):
    _mt5_check()
    try:
        return await in_thread(core.order_check, body.request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/orders/send", tags=["orders"])
async def order_send(body: RawOrderRequest):
    _mt5_check()
    try:
        return await in_thread(core.order_send, body.request)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/orders/calc_margin", tags=["orders"])
async def order_calc_margin(body: MarginCalcRequest):
    _mt5_check()
    try:
        margin = await in_thread(core.order_calc_margin, body.action, body.symbol, body.volume, body.price)
        return {"margin": margin}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/orders/calc_profit", tags=["orders"])
async def order_calc_profit(body: ProfitCalcRequest):
    _mt5_check()
    try:
        profit = await in_thread(
            core.order_calc_profit,
            body.action, body.symbol, body.volume, body.price_open, body.price_close,
        )
        return {"profit": profit}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Trading – convenience endpoints
# ---------------------------------------------------------------------------

@app.post("/trade/open", tags=["trading"])
async def trade_open(body: OpenPositionRequest):
    """Open a market position (BUY / SELL)."""
    _mt5_check()
    try:
        return await in_thread(
            core.open_position,
            body.symbol, body.order_type, body.volume,
            body.price, body.sl, body.tp,
            body.deviation, body.magic, body.comment, body.type_filling,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/close", tags=["trading"])
async def trade_close(body: ClosePositionRequest):
    """Close an open position by ticket."""
    _mt5_check()
    try:
        return await in_thread(core.close_position, body.ticket, body.deviation, body.comment)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/close_all", tags=["trading"])
async def trade_close_all(body: CloseAllRequest):
    """Close all open positions, optionally filtered by symbol."""
    _mt5_check()
    try:
        return await in_thread(core.close_all_positions, body.symbol, body.deviation)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/pending", tags=["trading"])
async def trade_pending(body: PendingOrderRequest):
    """Place a pending limit/stop order."""
    _mt5_check()
    try:
        expiration = _parse_dt(body.expiration) if body.expiration else None
        return await in_thread(
            core.place_pending_order,
            body.symbol, body.order_type, body.volume, body.price,
            body.sl, body.tp, expiration,
            body.deviation, body.magic, body.comment, body.type_filling,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/modify_position", tags=["trading"])
async def trade_modify_position(body: ModifyPositionRequest):
    """Modify SL/TP of an open position."""
    _mt5_check()
    try:
        return await in_thread(core.modify_position, body.ticket, body.sl, body.tp)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/modify_order", tags=["trading"])
async def trade_modify_order(body: ModifyOrderRequest):
    """Modify price/SL/TP of a pending order."""
    _mt5_check()
    try:
        expiration = _parse_dt(body.expiration) if body.expiration else None
        return await in_thread(
            core.modify_order, body.ticket, body.price, body.sl, body.tp, expiration
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/trade/cancel_order", tags=["trading"])
async def trade_cancel_order(body: CancelOrderRequest):
    """Cancel a pending order by ticket."""
    _mt5_check()
    try:
        return await in_thread(core.cancel_order, body.ticket)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@app.post("/history/deals", tags=["history"])
async def history_deals(body: DealsRequest):
    _mt5_check()
    try:
        return await in_thread(
            core.history_deals_get,
            _parse_dt(body.start_date), _parse_dt(body.end_date),
            body.group, body.ticket, body.position,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/history/deals/total", tags=["history"])
async def history_deals_total(body: DealsRequest):
    _mt5_check()
    try:
        total = await in_thread(
            core.history_deals_total,
            _parse_dt(body.start_date), _parse_dt(body.end_date),
        )
        return {"total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/history/orders", tags=["history"])
async def history_orders(body: HistoryOrdersRequest):
    _mt5_check()
    try:
        return await in_thread(
            core.history_orders_get,
            _parse_dt(body.start_date), _parse_dt(body.end_date),
            body.group, body.ticket, body.position,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/history/orders/total", tags=["history"])
async def history_orders_total(body: HistoryOrdersRequest):
    _mt5_check()
    try:
        total = await in_thread(
            core.history_orders_total,
            _parse_dt(body.start_date), _parse_dt(body.end_date),
        )
        return {"total": total}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Economic calendar
# ---------------------------------------------------------------------------

@app.get("/calendar/health", tags=["calendar"])
async def calendar_health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "data_folder": str(calendar_reader.data_folder),
        "folder_exists": calendar_reader.data_folder.exists(),
    }


@app.get("/calendar/countries", tags=["calendar"])
async def get_calendar_countries():
    data = await in_thread(calendar_reader.get_countries)
    if data is None:
        raise HTTPException(status_code=404, detail="Countries data not available")
    return data


@app.get("/calendar/events", tags=["calendar"])
async def get_calendar_events(
    importance: Optional[str] = None,
    country_id: Optional[str] = None,
    sector:     Optional[str] = None,
):
    data = await in_thread(calendar_reader.get_events)
    if data is None:
        raise HTTPException(status_code=404, detail="Events data not available")
    events = data.get("events", [])
    if importance:
        events = [e for e in events if e.get("importance") == importance.upper()]
    if country_id:
        events = [e for e in events if e.get("country_id") == country_id]
    if sector:
        events = [e for e in events if e.get("sector") == sector.upper()]
    return {"timestamp": data.get("timestamp"), "count": len(events), "events": events}


@app.get("/calendar/events/{event_id}", tags=["calendar"])
async def get_calendar_event(event_id: str):
    data = await in_thread(calendar_reader.get_events)
    if data is None:
        raise HTTPException(status_code=404, detail="Events data not available")
    event = next((e for e in data.get("events", []) if e.get("id") == event_id), None)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@app.get("/calendar/values/recent", tags=["calendar"])
async def get_recent_values(
    impact: Optional[str] = None,
    limit:  Optional[int] = None,
):
    data = await in_thread(calendar_reader.get_recent_values)
    if data is None:
        raise HTTPException(status_code=404, detail="Recent values data not available")
    values = data.get("values", [])
    if impact:
        values = [v for v in values if v.get("impact_type") == impact.upper()]
    if limit:
        values = values[:limit]
    return {
        "timestamp":  data.get("timestamp"),
        "start_date": data.get("start_date"),
        "end_date":   data.get("end_date"),
        "count":      len(values),
        "values":     values,
    }


@app.get("/calendar/values/currency/{currency}", tags=["calendar"])
async def get_currency_values(currency: str):
    data = await in_thread(calendar_reader.get_currency_values, currency)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Data for {currency} not available")
    return data


@app.get("/calendar/values/upcoming", tags=["calendar"])
async def get_upcoming_values(limit: int = 50):
    data = await in_thread(calendar_reader.get_recent_values)
    if data is None:
        raise HTTPException(status_code=404, detail="Recent values data not available")
    # Use naive UTC — broker calendar timestamps are UTC, so compare apples-to-apples.
    now = datetime.utcnow()
    upcoming = []
    for v in data.get("values", []):
        try:
            if datetime.strptime(v.get("time", ""), "%Y.%m.%d %H:%M:%S") > now:
                upcoming.append(v)
        except Exception:
            continue
    upcoming.sort(key=lambda x: x.get("time", ""))
    return {"timestamp": now.isoformat() + "Z", "count": len(upcoming), "values": upcoming[:limit]}


@app.get("/calendar/values/high-impact", tags=["calendar"])
async def get_high_impact_values():
    values_data = await in_thread(calendar_reader.get_recent_values)
    events_data = await in_thread(calendar_reader.get_events)
    if values_data is None or events_data is None:
        raise HTTPException(status_code=404, detail="Calendar data not available")
    events_map = {e["id"]: e for e in events_data.get("events", [])}
    high = []
    for v in values_data.get("values", []):
        eid = v.get("event_id")
        if eid in events_map and events_map[eid].get("importance") == "HIGH":
            v["event_info"] = events_map[eid]
            high.append(v)
    return {"timestamp": datetime.now().isoformat(), "count": len(high), "values": high}


@app.get("/calendar/search", tags=["calendar"])
async def search_calendar(q: str = Query(..., min_length=1)):
    q_lower = q.lower()
    events_data   = await in_thread(calendar_reader.get_events)
    countries_data = await in_thread(calendar_reader.get_countries)
    if events_data is None:
        raise HTTPException(status_code=404, detail="Events data not available")
    countries = {c["id"]: c for c in (countries_data or {}).get("countries", [])}
    results = []
    for ev in events_data.get("events", []):
        cid = ev.get("country_id")
        if q_lower in ev.get("name", "").lower():
            if cid in countries:
                ev["country_info"] = countries[cid]
            results.append(ev)
        elif cid in countries and q_lower in countries[cid].get("name", "").lower():
            ev["country_info"] = countries[cid]
            results.append(ev)
    return {"query": q, "count": len(results), "results": results}


@app.post("/calendar/refresh", tags=["calendar"])
async def refresh_calendar_cache():
    await in_thread(calendar_reader.clear_cache)
    return {"status": "success", "message": "Cache cleared"}


# ===========================================================================
# Legacy aliases  — old Flask route paths, kept for backwards compatibility.
# These are thin pass-throughs to the canonical handlers above.
# DO NOT remove; external callers may still use these paths.
# ===========================================================================

# POST /get_symbol_info  ->  POST /symbol/info
@app.post("/get_symbol_info", tags=["_legacy"], include_in_schema=False)
async def legacy_get_symbol_info(body: SymbolRequest):
    return await get_symbol_info(body)


# GET /get_available_symbols  ->  GET /symbols
@app.get("/get_available_symbols", tags=["_legacy"], include_in_schema=False)
async def legacy_get_available_symbols(group: Optional[str] = Query(None)):
    return await get_symbols(group)


# POST /copy_rates_from  ->  POST /rates/from
@app.post("/copy_rates_from", tags=["_legacy"], include_in_schema=False)
async def legacy_copy_rates_from(body: RatesFromRequest):
    return await copy_rates_from(body)


# POST /copy_rates_range  ->  POST /rates/range
@app.post("/copy_rates_range", tags=["_legacy"], include_in_schema=False)
async def legacy_copy_rates_range(body: RatesRangeRequest):
    return await copy_rates_range(body)


# POST /copy_ticks_from  ->  POST /ticks/from
@app.post("/copy_ticks_from", tags=["_legacy"], include_in_schema=False)
async def legacy_copy_ticks_from(body: TicksFromRequest):
    return await copy_ticks_from(body)


# POST /get_deals  ->  POST /history/deals
@app.post("/get_deals", tags=["_legacy"], include_in_schema=False)
async def legacy_get_deals(body: DealsRequest):
    return await history_deals(body)


# ===========================================================================
# Entry-point
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mt5_bridge:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", 5000)),
        workers=1,          # keep at 1 — MT5 uses a single shared connection
        log_level="info",
    )