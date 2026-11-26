from services import market_heatmap_providers as providers


def test_twelve_data_refresh_only_persists_quotes_returned_by_provider(monkeypatch):
    saved = []
    monkeypatch.setattr(
        providers,
        "_td_quote_map",
        lambda symbols: {
            "AAPL": {
                "symbol": "AAPL", "close": "220.5", "previous_close": "218.0",
                "percent_change": "1.15", "volume": "12345", "currency": "USD",
                "exchange": "NASDAQ",
            }
        },
    )
    monkeypatch.setattr(
        providers,
        "_td_get",
        lambda path, params: [
            {"symbol": "XAU/USD", "name": "Gold Spot", "category": "Precious Metals"},
            {"symbol": "XAG/USD", "name": "Silver Spot", "category": "Precious Metals"},
        ],
    )
    monkeypatch.setattr(
        providers,
        "_save_td_item",
        lambda item, quote, **kwargs: saved.append((item["symbol"], quote["close"])) or True,
    )

    result = providers.refresh_global()

    assert result["status"] == "success"
    assert result["updated"] == 1
    assert saved == [("AAPL", "220.5")]


def test_india_refresh_requires_current_users_openalgo_api_key(monkeypatch):
    monkeypatch.setattr(providers, "get_api_key_for_tradingview", lambda username: None)

    result = providers.refresh_india("demo-user")

    assert result["status"] == "not_configured"
    assert result["updated"] == 0


def test_india_refresh_normalizes_broker_quotes(monkeypatch):
    saved_instruments = []
    saved_snapshots = []
    monkeypatch.setattr(providers, "get_api_key_for_tradingview", lambda username: "test-key")
    monkeypatch.setattr(
        providers,
        "get_multiquotes",
        lambda **kwargs: (
            True,
            {"results": [{
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "data": {"ltp": 1250.0, "prev_close": 1200.0, "volume": 1000},
            }]},
            200,
        ),
    )
    monkeypatch.setattr(providers, "upsert_instrument", lambda item: saved_instruments.append(item))
    monkeypatch.setattr(providers, "save_snapshot", lambda item: saved_snapshots.append(item))

    result = providers.refresh_india("demo-user")

    assert result["status"] == "success"
    assert result["updated"] == 1
    assert saved_instruments[0]["symbol"] == "RELIANCE"
    assert saved_snapshots[0]["currency"] == "INR"
    assert saved_snapshots[0]["change_percent"] == 4.166666666666667



def test_numeric_normalizer_keeps_negative_price_changes():
    assert providers._as_float("-1.25") == -1.25
    assert providers._as_float("not-a-number") is None
