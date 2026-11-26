"""Provider adapters and ingestion for the Market Heatmap.

Prices are always fetched from configured market-data providers. The instrument
catalog below contains reference metadata only; it never contains quote prices.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
import websocket

from database.auth_db import get_api_key_for_tradingview
from database.market_heatmap_db import get_history, get_instrument_detail, get_snapshot, init_market_heatmap_db, save_candles, save_snapshot, upsert_instrument
from services.history_service import get_history as fetch_broker_history
from services.quotes_service import get_multiquotes
from utils.logging import get_logger

logger = get_logger(__name__)
TWELVE_DATA_URL = "https://api.twelvedata.com"
REQUEST_TIMEOUT = (4, 15)

# Reference data only. Live prices are never seeded from this catalog.
GLOBAL_INSTRUMENTS = [
    ("AAPL", "Apple Inc.", "Technology"), ("MSFT", "Microsoft", "Technology"),
    ("NVDA", "NVIDIA", "Technology"), ("AVGO", "Broadcom", "Technology"),
    ("ORCL", "Oracle", "Technology"), ("CRM", "Salesforce", "Technology"),
    ("GOOGL", "Alphabet", "Communication Services"), ("META", "Meta Platforms", "Communication Services"),
    ("NFLX", "Netflix", "Communication Services"), ("AMZN", "Amazon", "Consumer Cyclical"),
    ("TSLA", "Tesla", "Consumer Cyclical"), ("HD", "Home Depot", "Consumer Cyclical"),
    ("WMT", "Walmart", "Consumer Defensive"), ("COST", "Costco", "Consumer Defensive"),
    ("PG", "Procter & Gamble", "Consumer Defensive"), ("LLY", "Eli Lilly", "Healthcare"),
    ("JNJ", "Johnson & Johnson", "Healthcare"), ("ABBV", "AbbVie", "Healthcare"),
    ("JPM", "JPMorgan Chase", "Financials"), ("BAC", "Bank of America", "Financials"),
    ("V", "Visa", "Financials"), ("MA", "Mastercard", "Financials"),
    ("XOM", "Exxon Mobil", "Energy"), ("CVX", "Chevron", "Energy"),
    ("CAT", "Caterpillar", "Industrials"), ("GE", "GE Aerospace", "Industrials"),
    ("KO", "Coca-Cola", "Consumer Defensive"), ("PEP", "PepsiCo", "Consumer Defensive"),
]

INDIA_INSTRUMENTS = [
    ("RELIANCE", "Reliance Industries", "Energy"), ("TCS", "Tata Consultancy Services", "Technology"),
    ("HDFCBANK", "HDFC Bank", "Financials"), ("ICICIBANK", "ICICI Bank", "Financials"),
    ("INFY", "Infosys", "Technology"), ("BHARTIARTL", "Bharti Airtel", "Communication Services"),
    ("SBIN", "State Bank of India", "Financials"), ("ITC", "ITC", "Consumer Defensive"),
    ("LT", "Larsen & Toubro", "Industrials"), ("HINDUNILVR", "Hindustan Unilever", "Consumer Defensive"),
    ("AXISBANK", "Axis Bank", "Financials"), ("KOTAKBANK", "Kotak Mahindra Bank", "Financials"),
    ("BAJFINANCE", "Bajaj Finance", "Financials"), ("MARUTI", "Maruti Suzuki", "Consumer Cyclical"),
    ("SUNPHARMA", "Sun Pharmaceutical", "Healthcare"), ("TITAN", "Titan Company", "Consumer Cyclical"),
    ("NTPC", "NTPC", "Utilities"), ("POWERGRID", "Power Grid", "Utilities"),
    ("ONGC", "Oil & Natural Gas Corporation", "Energy"), ("TATAMOTORS", "Tata Motors", "Consumer Cyclical"),
    ("M&M", "Mahindra & Mahindra", "Consumer Cyclical"), ("ULTRACEMCO", "UltraTech Cement", "Materials"),
    ("ADANIENT", "Adani Enterprises", "Industrials"), ("ASIANPAINT", "Asian Paints", "Materials"),
    ("WIPRO", "Wipro", "Technology"), ("HCLTECH", "HCL Technologies", "Technology"),
    ("NESTLEIND", "Nestle India", "Consumer Defensive"), ("JSWSTEEL", "JSW Steel", "Materials"),
]

INDEX_INSTRUMENTS = [
    ("SPX", "S&P 500", "USA"), ("NDX", "NASDAQ 100", "USA"),
    ("DJI", "Dow Jones Industrial Average", "USA"),
    ("FTSE", "FTSE 100", "United Kingdom"),
    ("DAX", "DAX", "Germany"), ("N225", "Nikkei 225", "Japan"),
]

_refresh_lock = threading.Lock()
_last_refresh: dict[str, float] = {}
_refresh_results: dict[str, dict[str, Any]] = {}
_stream_lock = threading.Lock()
_stream_thread: threading.Thread | None = None
_stream_stop = threading.Event()
_stream_symbols: list[str] = []
_stream_status = {"status": "stopped", "last_tick_at": None, "error": None}


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number == number and abs(number) != float('inf') else None
    except (TypeError, ValueError):
        return None


def _td_get(path: str, params: dict[str, Any]) -> Any:
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("TWELVEDATA_API_KEY is not configured")
    response = requests.get(
        f"{TWELVE_DATA_URL}/{path.lstrip('/')}",
        params={**params, "apikey": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("status") == "error":
        raise RuntimeError(payload.get("message", "Twelve Data request failed"))
    return payload


def _td_quote_map(symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    # Twelve Data supports comma-separated symbol batches. Keep each request
    # below the documented 120-symbol batch ceiling.
    payload = _td_get("quote", {"symbol": ",".join(symbols)})
    if isinstance(payload, dict) and "symbol" in payload:
        return {str(payload["symbol"]).upper(): payload}
    if isinstance(payload, dict):
        return {
            str(value.get("symbol", key)).upper(): value
            for key, value in payload.items()
            if isinstance(value, dict) and value.get("symbol")
        }
    return {}


def _save_td_item(item: dict[str, Any], quote: dict[str, Any], *, market: str,
                  asset_type: str, sector: str | None = None, country: str | None = None) -> bool:
    price = _as_float(quote.get("close") or quote.get("price") or quote.get("last"))
    if price is None or price <= 0:
        return False
    previous = _as_float(quote.get("previous_close"))
    change = _as_float(quote.get("change"))
    percent = None
    try:
        percent = float(quote["percent_change"]) if quote.get("percent_change") is not None else None
    except (TypeError, ValueError):
        pass
    if percent is None and previous:
        percent = ((price / previous) - 1) * 100
    symbol = item["symbol"]
    exchange = str(quote.get("exchange") or item.get("exchange") or "TwelveData")
    currency = quote.get("currency") or item.get("currency") or "USD"
    name = quote.get("name") or item["name"]
    upsert_instrument({
        "symbol": symbol, "exchange": exchange, "name": name,
        "asset_type": asset_type, "market": market, "sector": sector,
        "country": country, "currency": currency, "source": "twelvedata",
        "metadata": {"provider_symbol": symbol},
    })
    save_snapshot({
        "symbol": symbol, "exchange": exchange, "last_price": price,
        "previous_close": previous, "change_value": change, "change_percent": percent,
        "volume": _as_float(quote.get("volume")), "currency": currency,
        "source": "twelvedata", "as_of": datetime.now(UTC).isoformat(),
    })
    return True



def _persist_stream_tick(message: dict[str, Any]) -> None:
    symbol = str(message.get("symbol") or "").upper()
    price = _as_float(message.get("price"))
    if not symbol or price is None or price <= 0:
        return
    instrument = next((row for row in get_snapshot() if row["symbol"].upper() == symbol), None)
    if not instrument:
        return
    previous = _as_float(instrument.get("previous_close"))
    change = price - previous if previous else None
    percent = ((price / previous) - 1) * 100 if previous else None
    stamp = message.get("timestamp")
    try:
        as_of = datetime.fromtimestamp(float(stamp), UTC).isoformat() if stamp else datetime.now(UTC).isoformat()
    except (TypeError, ValueError, OSError):
        as_of = datetime.now(UTC).isoformat()
    save_snapshot({
        "symbol": symbol, "exchange": instrument["exchange"], "last_price": price,
        "previous_close": previous, "change_value": change, "change_percent": percent,
        "volume": _as_float(message.get("day_volume")) or instrument.get("volume"),
        "currency": instrument.get("currency"), "source": "twelvedata_ws", "as_of": as_of,
    })
    _stream_status["last_tick_at"] = as_of


def _twelvedata_stream_loop() -> None:
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    url = "wss://ws.twelvedata.com/v1/quotes/price?apikey=" + api_key
    while not _stream_stop.is_set():
        def on_open(ws):
            _stream_status.update({"status": "connected", "error": None})
            if _stream_symbols:
                ws.send(json.dumps({
                    "action": "subscribe", "params": {"symbols": ",".join(_stream_symbols)}
                }))

        def on_message(ws, raw):
            try:
                message = json.loads(raw)
                if isinstance(message, dict) and message.get("event") == "price":
                    _persist_stream_tick(message)
                elif isinstance(message, dict) and message.get("status") == "error":
                    _stream_status["error"] = message.get("message", "Provider stream error")
            except Exception as exc:
                logger.warning("Unable to process Twelve Data stream message: %s", exc)

        def on_error(ws, error):
            _stream_status.update({"status": "error", "error": str(error)})

        def on_close(ws, code, reason):
            if not _stream_stop.is_set():
                _stream_status["status"] = "reconnecting"

        try:
            app = websocket.WebSocketApp(
                url, on_open=on_open, on_message=on_message,
                on_error=on_error, on_close=on_close,
            )
            app.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as exc:
            _stream_status.update({"status": "error", "error": str(exc)})
            logger.warning("Twelve Data WebSocket stopped: %s", exc)
        if not _stream_stop.is_set():
            _stream_stop.wait(5)
    _stream_status["status"] = "stopped"


def start_twelvedata_stream(symbols: list[str]) -> dict[str, Any]:
    """Start one reconnecting server-side stream for the current provider symbol set."""
    global _stream_thread, _stream_symbols
    api_key = os.getenv("TWELVEDATA_API_KEY", "").strip()
    if not api_key:
        return {"status": "not_configured", "message": "TWELVEDATA_API_KEY is not configured"}
    with _stream_lock:
        _stream_symbols = list(dict.fromkeys(symbols))
        if _stream_thread and _stream_thread.is_alive():
            return {**_stream_status, "symbols": len(_stream_symbols)}
        _stream_stop.clear()
        _stream_thread = threading.Thread(
            target=_twelvedata_stream_loop, name="market-heatmap-twelvedata", daemon=True
        )
        _stream_thread.start()
    return {"status": "connecting", "symbols": len(_stream_symbols)}


def refresh_global() -> dict[str, Any]:
    """Fetch global company, index and commodity quotes from Twelve Data."""
    symbols = [row[0] for row in GLOBAL_INSTRUMENTS + INDEX_INSTRUMENTS]
    quotes = _td_quote_map(symbols)
    updated = 0
    for symbol, name, sector in GLOBAL_INSTRUMENTS:
        quote = quotes.get(symbol)
        if quote:
            updated += _save_td_item(
                {"symbol": symbol, "name": name}, quote, market="GLOBAL",
                asset_type="company", sector=sector, country="USA",
            )
    for symbol, name, country in INDEX_INSTRUMENTS:
        quote = quotes.get(symbol)
        if quote:
            updated += _save_td_item(
                {"symbol": symbol, "name": name}, quote, market="GLOBAL",
                asset_type="index", country=country,
            )

    commodity_catalog = _td_get("commodities", {})
    rows = commodity_catalog if isinstance(commodity_catalog, list) else commodity_catalog.get("data", [])
    wanted = ("gold", "silver", "crude oil", "natural gas", "copper", "aluminium",
              "aluminum", "wheat", "corn", "brent")
    commodities = [
        {"symbol": str(row.get("symbol", "")).strip(), "name": row.get("name") or row.get("symbol"),
         "category": row.get("category")}
        for row in rows if isinstance(row, dict)
        and any(word in str(row.get("name", "")).lower() for word in wanted)
        and row.get("symbol")
    ][:8]
    commodity_symbols = [item["symbol"] for item in commodities]
    commodity_quotes = _td_quote_map(commodity_symbols)
    for item in commodities:
        quote = commodity_quotes.get(item["symbol"].upper())
        if quote:
            updated += _save_td_item(
                item, quote, market="COMMODITY", asset_type="commodity",
                sector=item.get("category"), country="Global",
            )
    stream = start_twelvedata_stream(symbols + commodity_symbols)
    return {"status": "success", "updated": updated, "provider": "twelvedata",
            "stream": stream}


def refresh_india(username: str) -> dict[str, Any]:
    """Fetch Indian cash-market quotes through the currently logged-in OpenAlgo broker."""
    api_key = get_api_key_for_tradingview(username)
    if not api_key:
        return {"status": "not_configured", "updated": 0,
                "message": "Generate an OpenAlgo API key and connect your broker to load Indian quotes."}
    symbols = [{"symbol": symbol, "exchange": "NSE"} for symbol, _, _ in INDIA_INSTRUMENTS]
    success, payload, status_code = get_multiquotes(symbols=symbols, api_key=api_key)
    if not success:
        return {"status": "error", "updated": 0,
                "message": payload.get("message", f"Broker quote request failed ({status_code})")}
    by_symbol = {}
    for result in payload.get("results", []):
        symbol = str(result.get("symbol", "")).upper()
        data = result.get("data") or {}
        if symbol and data:
            by_symbol[symbol] = data
    updated = 0
    for symbol, name, sector in INDIA_INSTRUMENTS:
        quote = by_symbol.get(symbol)
        if not quote:
            continue
        price = _as_float(quote.get("ltp") or quote.get("close") or quote.get("last_price"))
        if price is None:
            continue
        previous = _as_float(quote.get("prev_close") or quote.get("previous_close") or quote.get("close"))
        change = price - previous if previous else None
        percent = ((price / previous) - 1) * 100 if previous else None
        upsert_instrument({
            "symbol": symbol, "exchange": "NSE", "name": name,
            "asset_type": "company", "market": "INDIA", "sector": sector,
            "country": "India", "currency": "INR", "source": "openalgo",
        })
        save_snapshot({
            "symbol": symbol, "exchange": "NSE", "last_price": price,
            "previous_close": previous, "change_value": change, "change_percent": percent,
            "volume": _as_float(quote.get("volume")), "currency": "INR",
            "source": "openalgo", "as_of": datetime.now(UTC).isoformat(),
        })
        updated += 1
    return {"status": "success" if updated else "empty", "updated": updated,
            "provider": "openalgo", "message": None if updated else "Broker returned no usable quotes."}


def refresh_instrument_history(username: str, symbol: str, exchange: str, timeframe: str, limit: int = 250) -> int:
    """Fetch missing chart history on demand and persist normalized OHLCV bars."""
    instrument = get_instrument_detail(symbol, exchange)
    if not instrument:
        return 0
    timeframe = timeframe.upper()
    existing = get_history(symbol, exchange, timeframe, limit)
    if len(existing) >= min(limit, 20):
        return len(existing)

    intervals = {
        "1M": ("1min", "1m", 7), "5M": ("5min", "5m", 10),
        "15M": ("15min", "15m", 30), "30M": ("30min", "30m", 45),
        "1H": ("1h", "1h", 90), "1D": ("1day", "D", 400),
        "1W": ("1week", "W", 1500),
    }
    if timeframe not in intervals:
        return len(existing)
    td_interval, broker_interval, days = intervals[timeframe]
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    if instrument["market"] in {"GLOBAL", "COMMODITY"}:
        quote_symbol = instrument["symbol"]
        params = {"symbol": quote_symbol, "interval": td_interval, "outputsize": min(limit, 5000)}
        if instrument.get("exchange") and instrument["exchange"] != "TwelveData":
            params["exchange"] = instrument["exchange"]
        payload = _td_get("time_series", params)
        values = payload.get("values", []) if isinstance(payload, dict) else []
        candles = [{
            "time": row.get("datetime"), "open": float(row["open"]),
            "high": float(row["high"]), "low": float(row["low"]),
            "close": float(row["close"]), "volume": _as_float(row.get("volume")),
        } for row in values if all(row.get(key) is not None for key in ("datetime", "open", "high", "low", "close"))]
        return save_candles(symbol, exchange, timeframe, list(reversed(candles)), "twelvedata") if candles else len(existing)

    api_key = get_api_key_for_tradingview(username)
    if not api_key:
        return len(existing)
    success, payload, _ = fetch_broker_history(
        symbol=symbol, exchange=exchange, interval=broker_interval,
        start_date=start.strftime("%Y-%m-%d"), end_date=end.strftime("%Y-%m-%d"),
        api_key=api_key, source="api",
    )
    if not success:
        logger.warning("OpenAlgo history fetch failed for %s:%s: %s", exchange, symbol, payload.get("message"))
        return len(existing)
    rows = payload.get("data", [])
    candles = []
    for row in rows:
        candle_time = row.get("timestamp") or row.get("time")
        if candle_time is None:
            continue
        try:
            if isinstance(candle_time, (int, float)) or str(candle_time).isdigit():
                candle_time = datetime.fromtimestamp(float(candle_time), UTC).isoformat()
            candles.append({
                "time": str(candle_time), "open": float(row["open"]),
                "high": float(row["high"]), "low": float(row["low"]),
                "close": float(row["close"]), "volume": _as_float(row.get("volume")),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return save_candles(symbol, exchange, timeframe, candles, "openalgo") if candles else len(existing)


def refresh_for_user(username: str, *, force: bool = False) -> dict[str, Any]:
    """Refresh all configured feeds, with a per-user cooldown to protect provider quotas."""
    if not username:
        raise ValueError("A signed-in user is required")
    now = time.monotonic()
    with _refresh_lock:
        last = _last_refresh.get(username, 0)
        if not force and now - last < 600:
            return {"status": "success", "skipped": True,
                    "message": "Market data was refreshed recently.",
                    "providers": _refresh_results.get(username, {})}
        _last_refresh[username] = now
    init_market_heatmap_db()
    providers: dict[str, Any] = {}
    try:
        providers["global"] = refresh_global()
    except Exception as exc:
        logger.warning("Market Heatmap global refresh failed: %s", exc)
        providers["global"] = {"status": "error", "updated": 0, "message": str(exc)}
    try:
        providers["india"] = refresh_india(username)
    except Exception as exc:
        logger.exception("Market Heatmap India refresh failed")
        providers["india"] = {"status": "error", "updated": 0, "message": str(exc)}
    result = {"status": "success", "skipped": False, "providers": providers,
              "refreshed_at": datetime.now(UTC).isoformat()}
    with _refresh_lock:
        _refresh_results[username] = providers
    return result
