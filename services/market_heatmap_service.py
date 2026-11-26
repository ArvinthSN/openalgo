"""Read-side service for the Market Heatmap."""
from database.market_heatmap_db import (
    get_history,
    get_instrument_detail,
    get_movers,
    get_snapshot,
)


def market_snapshot(market="ALL", asset_type="ALL", period="1D"):
    return {
        "status": "success",
        "data": get_snapshot(market=market, asset_type=asset_type, period=period),
        "meta": {"market": market, "asset_type": asset_type, "period": period},
    }


def market_movers(market="GLOBAL", direction="gainers", limit=10):
    return {
        "status": "success",
        "data": get_movers(market=market, direction=direction, limit=limit),
    }


def instrument_detail(symbol, exchange=""):
    return get_instrument_detail(symbol, exchange)


def instrument_history(symbol, exchange="", timeframe="1D", limit=250):
    return get_history(symbol, exchange, timeframe, limit)
