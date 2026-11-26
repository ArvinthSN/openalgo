"""SQLite persistence for the Market Heatmap.

The database is intentionally separate from OpenAlgo's operational database.
It stores instrument reference data, latest quote snapshots and OHLCV bars.
No sample prices are inserted; providers populate these tables through the
upsert functions below.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

DB_PATH = Path(os.getenv("MARKET_HEATMAP_DB_PATH", "db/market_heatmap.db"))


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


@contextmanager
def connection():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_market_heatmap_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS instruments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                asset_type TEXT NOT NULL CHECK(asset_type IN ('company','commodity','index')),
                market TEXT NOT NULL CHECK(market IN ('INDIA','GLOBAL','COMMODITY')),
                sector TEXT,
                country TEXT,
                currency TEXT,
                market_cap REAL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, exchange)
            );
            CREATE INDEX IF NOT EXISTS idx_heatmap_instruments_market
                ON instruments(market, asset_type, sector);

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
                last_price REAL NOT NULL,
                previous_close REAL,
                change_value REAL,
                change_percent REAL,
                volume REAL,
                market_cap REAL,
                currency TEXT,
                source TEXT NOT NULL,
                as_of TEXT NOT NULL,
                UNIQUE(instrument_id, source, as_of)
            );
            CREATE INDEX IF NOT EXISTS idx_heatmap_snapshots_latest
                ON market_snapshots(instrument_id, as_of DESC);

            CREATE TABLE IF NOT EXISTS historical_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
                timeframe TEXT NOT NULL,
                candle_time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL,
                source TEXT NOT NULL,
                UNIQUE(instrument_id, timeframe, candle_time, source)
            );
            CREATE INDEX IF NOT EXISTS idx_heatmap_history_lookup
                ON historical_prices(instrument_id, timeframe, candle_time DESC);
            """
        )


def upsert_instrument(item: dict[str, Any]) -> int:
    required = ("symbol", "name", "asset_type", "market")
    if any(not item.get(key) for key in required):
        raise ValueError("symbol, name, asset_type and market are required")
    metadata = item.get("metadata", {})
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO instruments
                (symbol, exchange, name, asset_type, market, sector, country,
                 currency, market_cap, metadata_json, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol, exchange) DO UPDATE SET
                name=excluded.name, asset_type=excluded.asset_type,
                market=excluded.market, sector=excluded.sector,
                country=excluded.country, currency=excluded.currency,
                market_cap=COALESCE(excluded.market_cap, instruments.market_cap),
                metadata_json=excluded.metadata_json, source=excluded.source,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                item["symbol"].upper(), item.get("exchange", ""), item["name"],
                item["asset_type"], item["market"], item.get("sector"),
                item.get("country"), item.get("currency"), item.get("market_cap"),
                json.dumps(metadata), item.get("source"),
            ),
        )
        row = conn.execute(
            "SELECT id FROM instruments WHERE symbol=? AND exchange=?",
            (item["symbol"].upper(), item.get("exchange", "")),
        ).fetchone()
        return int(row["id"])


def save_snapshot(item: dict[str, Any]) -> None:
    with connection() as conn:
        instrument = conn.execute(
            "SELECT id FROM instruments WHERE symbol=? AND exchange=?",
            (item["symbol"].upper(), item.get("exchange", "")),
        ).fetchone()
        if instrument is None:
            raise ValueError("Instrument must be registered before saving a quote")
        conn.execute(
            """
            INSERT INTO market_snapshots
                (instrument_id, last_price, previous_close, change_value,
                 change_percent, volume, market_cap, currency, source, as_of)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, source, as_of) DO UPDATE SET
                last_price=excluded.last_price,
                previous_close=excluded.previous_close,
                change_value=excluded.change_value,
                change_percent=excluded.change_percent,
                volume=excluded.volume,
                market_cap=excluded.market_cap,
                currency=excluded.currency
            """,
            (
                instrument["id"], item["last_price"], item.get("previous_close"),
                item.get("change_value"), item.get("change_percent"),
                item.get("volume"), item.get("market_cap"), item.get("currency"),
                item["source"], item["as_of"],
            ),
        )


def save_candles(symbol: str, exchange: str, timeframe: str, candles: list[dict[str, Any]], source: str) -> int:
    with connection() as conn:
        instrument = conn.execute(
            "SELECT id FROM instruments WHERE symbol=? AND exchange=?",
            (symbol.upper(), exchange),
        ).fetchone()
        if instrument is None:
            raise ValueError("Instrument must be registered before saving candles")
        conn.executemany(
            """
            INSERT INTO historical_prices
                (instrument_id, timeframe, candle_time, open, high, low, close, volume, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instrument_id, timeframe, candle_time, source) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume
            """,
            [
                (instrument["id"], timeframe, c["time"], c["open"], c["high"],
                 c["low"], c["close"], c.get("volume"), source)
                for c in candles
            ],
        )
        return len(candles)


def get_snapshot(market: str = "ALL", asset_type: str = "ALL", period: str = "1D") -> list[dict[str, Any]]:
    filters = []
    params: list[Any] = []
    if market != "ALL":
        filters.append("i.market = ?")
        params.append(market)
    if asset_type != "ALL":
        filters.append("i.asset_type = ?")
        params.append(asset_type)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    with connection() as conn:
        rows = conn.execute(
            f"""
            WITH latest AS (
                SELECT s.*, ROW_NUMBER() OVER (
                    PARTITION BY s.instrument_id ORDER BY s.as_of DESC, s.id DESC
                ) AS rank
                FROM market_snapshots s
            )
            SELECT i.symbol, i.exchange, i.name, i.asset_type, i.market, i.sector,
                   i.country, i.currency AS instrument_currency, i.market_cap AS reference_market_cap,
                   l.last_price, l.previous_close, l.change_value, l.change_percent,
                   l.volume, l.market_cap, l.currency, l.source, l.as_of
            FROM instruments i
            LEFT JOIN latest l ON l.instrument_id=i.id AND l.rank=1
            {where}
            ORDER BY i.market, i.sector, i.symbol
            """,
            params,
        ).fetchall()
        result = [dict(row) for row in rows]
        # Longer-period returns come from persisted daily candles. Missing
        # history stays null; it is never replaced with a 1D return.
        offsets = {"1W": 5, "1M": 21, "3M": 63, "1Y": 252}
        offset = offsets.get(period)
        if offset:
            for item in result:
                history = conn.execute(
                    """
                    SELECT close FROM historical_prices h
                    JOIN instruments i ON i.id=h.instrument_id
                    WHERE i.symbol=? AND i.exchange=? AND h.timeframe='1D'
                    ORDER BY h.candle_time DESC LIMIT 1 OFFSET ?
                    """,
                    (item["symbol"], item["exchange"], offset),
                ).fetchone()
                latest = conn.execute(
                    """
                    SELECT close FROM historical_prices h
                    JOIN instruments i ON i.id=h.instrument_id
                    WHERE i.symbol=? AND i.exchange=? AND h.timeframe='1D'
                    ORDER BY h.candle_time DESC LIMIT 1
                    """,
                    (item["symbol"], item["exchange"]),
                ).fetchone()
                if history and latest and history["close"]:
                    item["change_value"] = latest["close"] - history["close"]
                    item["change_percent"] = ((latest["close"] / history["close"]) - 1) * 100
                else:
                    item["change_value"] = None
                    item["change_percent"] = None
        return result


def get_movers(market: str, direction: str, limit: int = 10) -> list[dict[str, Any]]:
    order = "ASC" if direction == "losers" else "DESC"
    with connection() as conn:
        rows = conn.execute(
            f"""
            WITH latest AS (
                SELECT s.*, ROW_NUMBER() OVER (
                    PARTITION BY s.instrument_id ORDER BY s.as_of DESC, s.id DESC
                ) AS rank
                FROM market_snapshots s
            )
            SELECT i.symbol, i.name, i.market, i.sector, l.last_price,
                   l.change_percent, l.volume, l.currency, l.as_of
            FROM instruments i
            JOIN latest l ON l.instrument_id=i.id AND l.rank=1
            WHERE i.market=? AND i.asset_type='company'
              AND l.change_percent IS NOT NULL
            ORDER BY l.change_percent {order}
            LIMIT ?
            """,
            (market, max(1, min(limit, 100))),
        ).fetchall()
        return [dict(row) for row in rows]


def get_instrument_detail(symbol: str, exchange: str = "") -> dict[str, Any] | None:
    with connection() as conn:
        instrument = conn.execute(
            """
            SELECT i.* FROM instruments i WHERE i.symbol=? AND i.exchange=?
            """,
            (symbol.upper(), exchange),
        ).fetchone()
        if instrument is None:
            return None
        result = dict(instrument)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        result["snapshot"] = dict(conn.execute(
            """
            SELECT last_price, previous_close, change_value, change_percent,
                   volume, market_cap, currency, source, as_of
            FROM market_snapshots WHERE instrument_id=?
            ORDER BY as_of DESC, id DESC LIMIT 1
            """,
            (instrument["id"],),
        ).fetchone() or {})
        return result


def get_history(symbol: str, exchange: str = "", timeframe: str = "1D", limit: int = 250) -> list[dict[str, Any]]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT h.candle_time AS time, h.open, h.high, h.low, h.close, h.volume, h.source
            FROM historical_prices h
            JOIN instruments i ON i.id=h.instrument_id
            WHERE i.symbol=? AND i.exchange=? AND h.timeframe=?
            ORDER BY h.candle_time DESC LIMIT ?
            """,
            (symbol.upper(), exchange, timeframe, max(1, min(limit, 2000))),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]
