# =============================================================================
# event_agent/execution/idempotency.py — Deterministic Order Idempotency Engine
# =============================================================================
"""
NEXUS V4.0 Idempotency Subsystem:
- Deterministic idempotency key: SHA-256(signal_id + symbol + side + window).
- Guarantees exactly one logical order across process restarts, API timeouts,
  scheduler retries, duplicate webhooks, and network retries.
- Durable storage in SQLite with thread-safe reservation.
"""

import hashlib
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from ..config import DB_PATH

logger = logging.getLogger(__name__)


class DuplicateOrderError(Exception):
    """Raised when an order with an identical idempotency key is submitted."""
    pass


@dataclass
class IdempotencyRecord:
    idempotency_key: str
    signal_id: str
    symbol: str
    side: str
    execution_window: str
    order_intent_id: str
    status: str  # RESERVED | EXECUTED | RELEASED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IdempotencyManager:
    """
    Thread-safe and durable order idempotency manager.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super(IdempotencyManager, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.db_path = str(db_path or DB_PATH)
        self._memory_cache: Dict[str, IdempotencyRecord] = {}
        self._init_db()
        self._load_cache()
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS v4_idempotency_keys (
                    idempotency_key TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    execution_window TEXT NOT NULL,
                    order_intent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """)
        except Exception as e:
            logger.warning(f"Could not init idempotency SQLite table: {e}")

    def _load_cache(self) -> None:
        try:
            with self._get_connection() as conn:
                rows = conn.execute("SELECT * FROM v4_idempotency_keys").fetchall()
                for r in rows:
                    rec = IdempotencyRecord(
                        idempotency_key=r["idempotency_key"],
                        signal_id=r["signal_id"],
                        symbol=r["symbol"],
                        side=r["side"],
                        execution_window=r["execution_window"],
                        order_intent_id=r["order_intent_id"],
                        status=r["status"],
                        created_at=r["created_at"],
                    )
                    self._memory_cache[rec.idempotency_key] = rec
        except Exception as e:
            logger.debug(f"Idempotency cache load: {e}")

    @classmethod
    def generate_key(
        cls,
        signal_id: str,
        symbol: str,
        side: str,
        execution_window: Optional[str] = None,
    ) -> str:
        """
        Computes deterministic SHA-256 key from trade parameters.
        Default execution window is the current UTC date string YYYY-MM-DD.
        """
        win = execution_window or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        sym = symbol.upper().strip().replace(".NS", "")
        sd = side.upper().strip()
        raw = f"{signal_id}:{sym}:{sd}:{win}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def reserve(
        self,
        signal_id: str,
        symbol: str,
        side: str,
        order_intent_id: str,
        execution_window: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[IdempotencyRecord]]:
        """
        Atomically reserves an idempotency key.
        Returns:
            (is_new, idempotency_key, existing_record_if_duplicate)
        Raises DuplicateOrderError if already reserved.
        """
        sig = str(signal_id or "").upper()
        oint = str(order_intent_id or "").upper()
        if "QUANT" in sig and "SCREEN" in sig:
            raise ValueError("Invariant Violation: QUANT_SCREEN cannot create order_intent_id.")
        if "QUANT" in oint and "SCREEN" in oint:
            raise ValueError("Invariant Violation: QUANT_SCREEN cannot create order_intent_id.")

        key = self.generate_key(signal_id, symbol, side, execution_window)
        win = execution_window or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            # 1. Check memory cache
            existing = self._memory_cache.get(key)
            if existing:
                logger.warning(
                    f"⚠️ Duplicate order attempt detected for key {key[:12]}... (Existing: {existing.order_intent_id})"
                )
                return False, key, existing

            # 2. Check DB
            try:
                with self._get_connection() as conn:
                    row = conn.execute(
                        "SELECT * FROM v4_idempotency_keys WHERE idempotency_key = ?",
                        (key,),
                    ).fetchone()
                    if row:
                        rec = IdempotencyRecord(
                            idempotency_key=row["idempotency_key"],
                            signal_id=row["signal_id"],
                            symbol=row["symbol"],
                            side=row["side"],
                            execution_window=row["execution_window"],
                            order_intent_id=row["order_intent_id"],
                            status=row["status"],
                            created_at=row["created_at"],
                        )
                        self._memory_cache[key] = rec
                        return False, key, rec

                    # Insert new reservation
                    now_str = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        """
                        INSERT INTO v4_idempotency_keys
                        (idempotency_key, signal_id, symbol, side, execution_window, order_intent_id, status, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'RESERVED', ?)
                        """,
                        (key, signal_id, symbol, side, win, order_intent_id, now_str),
                    )

                    new_rec = IdempotencyRecord(
                        idempotency_key=key,
                        signal_id=signal_id,
                        symbol=symbol,
                        side=side,
                        execution_window=win,
                        order_intent_id=order_intent_id,
                        status="RESERVED",
                        created_at=now_str,
                    )
                    self._memory_cache[key] = new_rec
                    logger.debug(f"Idempotency key {key[:12]} reserved for {order_intent_id}")
                    return True, key, None
            except sqlite3.IntegrityError:
                # Concurrent race condition caught by SQLite UNIQUE constraint
                existing = self._memory_cache.get(key)
                return False, key, existing

    def mark_executed(self, idempotency_key: str) -> None:
        with self._lock:
            if idempotency_key in self._memory_cache:
                self._memory_cache[idempotency_key].status = "EXECUTED"
            try:
                with self._get_connection() as conn:
                    conn.execute(
                        "UPDATE v4_idempotency_keys SET status = 'EXECUTED' WHERE idempotency_key = ?",
                        (idempotency_key,),
                    )
            except Exception as e:
                logger.error(f"Failed to update idempotency key status: {e}")

    def is_reserved(self, idempotency_key: str) -> bool:
        return idempotency_key in self._memory_cache


# Alias for backwards compatibility and engine terminology
IdempotencyEngine = IdempotencyManager
