"""Session-authenticated Market Heatmap read API."""
from flask import Blueprint, jsonify, request, session

from services.market_heatmap_service import (
    instrument_detail,
    instrument_history,
    market_movers,
    market_snapshot,
)
from services.market_heatmap_providers import market_data_status, refresh_for_user, refresh_instrument_history
from utils.session import check_session_validity

market_heatmap_bp = Blueprint("market_heatmap_bp", __name__)


@market_heatmap_bp.get("/market-heatmap/api/snapshot")
@check_session_validity
def snapshot():
    market = (request.args.get("market") or "ALL").upper()
    asset_type = (request.args.get("asset_type") or "ALL").lower()
    period = (request.args.get("period") or "1D").upper()
    if market not in {"ALL", "INDIA", "GLOBAL", "COMMODITY"}:
        return jsonify({"status": "error", "message": "Unsupported market filter"}), 400
    if asset_type not in {"ALL", "COMPANY", "COMMODITY", "INDEX"}:
        return jsonify({"status": "error", "message": "Unsupported asset type"}), 400
    if period not in {"1D", "1W", "1M", "3M", "1Y"}:
        return jsonify({"status": "error", "message": "Unsupported period"}), 400
    return jsonify(market_snapshot(market, asset_type, period))


@market_heatmap_bp.get("/market-heatmap/api/movers")
@check_session_validity
def movers():
    market = (request.args.get("market") or "GLOBAL").upper()
    direction = (request.args.get("direction") or "gainers").lower()
    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400
    if market not in {"INDIA", "GLOBAL"} or direction not in {"gainers", "losers"}:
        return jsonify({"status": "error", "message": "Unsupported movers filter"}), 400
    return jsonify(market_movers(market, direction, limit))


@market_heatmap_bp.get("/market-heatmap/api/instruments/<string:symbol>")
@check_session_validity
def instrument(symbol):
    exchange = request.args.get("exchange", "")
    data = instrument_detail(symbol, exchange)
    if data is None:
        return jsonify({"status": "error", "message": "Instrument not found"}), 404
    return jsonify({"status": "success", "data": data})


@market_heatmap_bp.get("/market-heatmap/api/instruments/<string:symbol>/history")
@check_session_validity
def instrument_history_route(symbol):
    exchange = request.args.get("exchange", "")
    timeframe = (request.args.get("timeframe") or "1D").upper()
    if timeframe not in {"1M", "5M", "15M", "30M", "1H", "1D", "1W"}:
        return jsonify({"status": "error", "message": "Unsupported timeframe"}), 400
    try:
        limit = int(request.args.get("limit", 250))
    except ValueError:
        return jsonify({"status": "error", "message": "limit must be an integer"}), 400
    username = session.get("user")
    try:
        refresh_instrument_history(username, symbol, exchange, timeframe, limit)
    except Exception:
        # Return previously persisted candles if a provider is temporarily unavailable.
        pass
    return jsonify({
        "status": "success",
        "data": instrument_history(symbol, exchange, timeframe, limit),
    })



@market_heatmap_bp.get("/market-heatmap/api/refresh")
@check_session_validity
def refresh():
    """Fetch fresh quotes using the configured Twelve Data and logged-in broker feeds."""
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "A signed-in user is required"}), 401
    try:
        return jsonify(refresh_for_user(username))
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 502



@market_heatmap_bp.get("/market-heatmap/api/status")
@check_session_validity
def status():
    return jsonify({"status": "success", "data": market_data_status()})
