# =============================================================================
# storage/db.py — SQLite Persistence Layer
# =============================================================================
"""
Schema:
    trades      — All closed trade records (entry + exit + PnL)
    tick_log    — Optional: raw tick snapshots for replay/audit
"""

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "trades.db"

conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
conn.row_factory = sqlite3.Row   # dict-like access
cursor = conn.cursor()

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

cursor.executescript("""
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT    NOT NULL,
    side        TEXT    NOT NULL,
    entry_price REAL    NOT NULL,
    exit_price  REAL,
    qty         INTEGER NOT NULL,
    stop_loss   REAL,
    target      REAL,
    opened_at   TEXT,
    closed_at   TEXT,
    exit_reason TEXT,
    pnl         REAL
);

CREATE TABLE IF NOT EXISTS tick_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol     TEXT NOT NULL,
    timestamp  TEXT NOT NULL,
    ltp        REAL,
    vwap       REAL,
    rsi        REAL,
    volume     INTEGER,
    signal     TEXT
);
""")
conn.commit()
logger.debug("DB schema initialised at %s", DB_PATH)


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def log_trade(trade: dict) -> None:
    """Insert a new trade record (entry only; exit_price/pnl may be None)."""
    cursor.execute(
        """
        INSERT INTO trades
            (symbol, side, entry_price, exit_price, qty,
             stop_loss, target, opened_at, closed_at, exit_reason, pnl)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            trade.get("symbol"),
            trade.get("side"),
            trade.get("entry_price"),
            trade.get("exit_price"),
            trade.get("qty"),
            trade.get("stop_loss"),
            trade.get("target"),
            trade.get("opened_at"),
            trade.get("closed_at"),
            trade.get("exit_reason"),
            trade.get("pnl"),
        ),
    )
    conn.commit()


def update_trade_exit(symbol: str, closed_trade: dict) -> None:
    """Update the most recent open trade for a symbol with exit details."""
    cursor.execute(
        """
        UPDATE trades
        SET exit_price  = ?,
            closed_at   = ?,
            exit_reason = ?,
            pnl         = ?
        WHERE symbol = ?
          AND closed_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (
            closed_trade.get("exit_price"),
            closed_trade.get("closed_at"),
            closed_trade.get("exit_reason"),
            closed_trade.get("pnl"),
            symbol,
        ),
    )
    conn.commit()


def get_all_trades() -> list[dict]:
    cursor.execute("SELECT * FROM trades ORDER BY id DESC")
    return [dict(row) for row in cursor.fetchall()]


def get_trade_summary() -> dict:
    cursor.execute("""
        SELECT
            COUNT(*)                             AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses,
            ROUND(SUM(pnl), 2)                   AS total_pnl
        FROM trades
        WHERE closed_at IS NOT NULL
    """)
    row = cursor.fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------------------
# Tick Log (optional, for audit trail)
# ---------------------------------------------------------------------------

def log_tick(symbol: str, timestamp: str, ltp: float, vwap: float,
             rsi: float, volume: int, signal: str) -> None:
    cursor.execute(
        "INSERT INTO tick_log (symbol, timestamp, ltp, vwap, rsi, volume, signal) VALUES (?,?,?,?,?,?,?)",
        (symbol, timestamp, ltp, vwap, rsi, volume, signal),
    )
    conn.commit()
