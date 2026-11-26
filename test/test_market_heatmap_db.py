from datetime import datetime, timedelta, timezone

import pytest

from database import market_heatmap_db as heatmap_db


@pytest.fixture
def heatmap_store(tmp_path, monkeypatch):
    monkeypatch.setattr(heatmap_db, "DB_PATH", tmp_path / "market_heatmap.db")
    heatmap_db.init_market_heatmap_db()
    return heatmap_db


def test_snapshot_and_movers_use_latest_quote(heatmap_store):
    db = heatmap_store
    db.upsert_instrument({
        "symbol": "AAA", "exchange": "NASDAQ", "name": "Alpha",
        "asset_type": "company", "market": "GLOBAL", "sector": "Technology",
        "currency": "USD",
    })
    db.upsert_instrument({
        "symbol": "BBB", "exchange": "NASDAQ", "name": "Beta",
        "asset_type": "company", "market": "GLOBAL", "sector": "Technology",
        "currency": "USD",
    })
    now = datetime.now(timezone.utc)
    for symbol, change in (("AAA", 2.5), ("BBB", -1.25)):
        db.save_snapshot({
            "symbol": symbol, "exchange": "NASDAQ", "last_price": 100 + change,
            "previous_close": 100, "change_value": change, "change_percent": change,
            "volume": 1000, "source": "test", "as_of": now.isoformat(),
        })

    snapshot = db.get_snapshot("GLOBAL", "company")
    assert len(snapshot) == 2
    assert {row["symbol"] for row in snapshot} == {"AAA", "BBB"}
    assert db.get_movers("GLOBAL", "gainers", 1)[0]["symbol"] == "AAA"
    assert db.get_movers("GLOBAL", "losers", 1)[0]["symbol"] == "BBB"


def test_history_upsert_and_period_return(heatmap_store):
    db = heatmap_store
    db.upsert_instrument({
        "symbol": "XYZ", "exchange": "NASDAQ", "name": "Example",
        "asset_type": "company", "market": "GLOBAL", "sector": "Technology",
        "currency": "USD",
    })
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        {
            "time": (base + timedelta(days=i)).isoformat(),
            "open": 100 + i, "high": 101 + i, "low": 99 + i,
            "close": 100 + i, "volume": 1000,
        }
        for i in range(7)
    ]
    db.save_candles("XYZ", "NASDAQ", "1D", candles, "test")
    history = db.get_history("XYZ", "NASDAQ", "1D")
    assert len(history) == 7
    snapshot = db.get_snapshot("GLOBAL", "company", "1W")
    assert snapshot[0]["change_percent"] == pytest.approx((106 / 101 - 1) * 100)
