"""Provider adapters and ingestion for the Market Heatmap.

Prices are always fetched from configured market-data providers. The instrument
catalog below contains reference metadata only; it never contains quote prices.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from typing import Any

import requests

from database.auth_db import get_api_key_for_tradingview
from database.market_heatmap_db import init_market_heatmap_db, save_snapshot, upsert_instrument
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


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if number > 0 else None
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
    if price is None:
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
    ][:12]
    commodity_quotes = _td_quote_map([item["symbol"] for item in commodities])
    for item in commodities:
        quote = commodity_quotes.get(item["symbol"].upper())
        if quote:
            updated += _save_td_item(
                item, quote, market="COMMODITY", asset_type="commodity",
                sector=item.get("category"), country="Global",
            )
    return {"status": "success", "updated": updated, "provider": "twelvedata"}


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


def refresh_for_user(username: str, *, force: bool = False) -> dict[str, Any]:
    """Refresh all configured feeds, with a per-user cooldown to protect provider quotas."""
    if not username:
        raise ValueError("A signed-in user is required")
    now = time.monotonic()
    with _refresh_lock:
        last = _last_refresh.get(username, 0)
        if not force and now - last < 45:
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
