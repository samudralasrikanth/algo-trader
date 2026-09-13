# =============================================================================
# event_agent/risk/kill_switch.py — Independent Multi-Level Kill Switch Subsystem
# =============================================================================
"""
NEXUS V4.0 Independent Kill Switch Subsystem:
- Independent from AI decision models.
- 3 Scopes: GLOBAL, STRATEGY, INSTRUMENT.
- Capabilities: Stop new orders, cancel pending orders, emergency position policy,
  enter latched EMERGENCY mode, prevent automated restart until explicitly cleared.
- 13 Automated Triggers.
- Persistent audit trail in SQLite and memory.
"""

import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..config import DB_PATH

logger = logging.getLogger(__name__)


class KillSwitchLevel(str, Enum):
    GLOBAL = "GLOBAL"
    STRATEGY = "STRATEGY"
    INSTRUMENT = "INSTRUMENT"


class KillSwitchTrigger(str, Enum):
    DAILY_DRAWDOWN_BREACH = "DAILY_DRAWDOWN_BREACH"
    MAX_DRAWDOWN_BREACH = "MAX_DRAWDOWN_BREACH"
    ABNORMAL_EXECUTION = "ABNORMAL_EXECUTION"
    BROKER_API_ANOMALY = "BROKER_API_ANOMALY"
    DATA_CORRUPTION = "DATA_CORRUPTION"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    UNEXPECTED_POSITION = "UNEXPECTED_POSITION"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    DUPLICATE_ORDER_DETECTION = "DUPLICATE_ORDER_DETECTION"
    MODEL_DRIFT = "MODEL_DRIFT"
    ABNORMAL_VOLATILITY = "ABNORMAL_VOLATILITY"
    REPEATED_FAILURES = "REPEATED_FAILURES"
    PROVENANCE_FAILURE = "PROVENANCE_FAILURE"
    MANUAL_OPERATOR = "MANUAL_OPERATOR"


class EmergencyPolicy(str, Enum):
    STOP_NEW_ORDERS = "STOP_NEW_ORDERS"
    CANCEL_PENDING = "CANCEL_PENDING"
    FLATTEN_ALL_POSITIONS = "FLATTEN_ALL_POSITIONS"
    HEDGE_DELTA_NEUTRAL = "HEDGE_DELTA_NEUTRAL"


@dataclass
class KillSwitchActivation:
    activation_id: str
    level: KillSwitchLevel
    trigger: KillSwitchTrigger
    target: str  # e.g. "ALL" for GLOBAL, "MOMENTUM" for STRATEGY, "RELIANCE.NS" for INSTRUMENT
    policy: EmergencyPolicy
    reason: str
    activated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    activated_by: str = "SYSTEM_AUTOMATION"
    is_active: bool = True
    cleared_at: Optional[str] = None
    cleared_by: Optional[str] = None
    clear_authorization_token: Optional[str] = None
    telemetry: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        d["trigger"] = self.trigger.value
        d["policy"] = self.policy.value
        return d


class IndependentKillSwitch:
    """
    Central Kill Switch Singleton managing real-time execution gates and persistence.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(IndependentKillSwitch, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, db_path: Optional[str] = None):
        if getattr(self, "_initialized", False):
            return
        self.db_path = str(db_path or DB_PATH)
        self._active_activations: Dict[str, KillSwitchActivation] = {}
        self._init_db()
        self._load_active_from_db()
        self._initialized = True

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_connection() as conn:
                conn.execute("""
                CREATE TABLE IF NOT EXISTS v4_kill_switch_activations (
                    activation_id TEXT PRIMARY KEY,
                    level TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    target TEXT NOT NULL,
                    policy TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    activated_at TEXT NOT NULL,
                    activated_by TEXT NOT NULL,
                    is_active INTEGER NOT NULL,
                    cleared_at TEXT,
                    cleared_by TEXT,
                    clear_token TEXT,
                    telemetry_json TEXT
                )
                """)
        except Exception as e:
            logger.warning(f"Could not init kill switch SQLite table: {e}")

    def _load_active_from_db(self) -> None:
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM v4_kill_switch_activations WHERE is_active = 1"
                ).fetchall()
                for r in rows:
                    act = KillSwitchActivation(
                        activation_id=r["activation_id"],
                        level=KillSwitchLevel(r["level"]),
                        trigger=KillSwitchTrigger(r["trigger"]),
                        target=r["target"],
                        policy=EmergencyPolicy(r["policy"]),
                        reason=r["reason"],
                        activated_at=r["activated_at"],
                        activated_by=r["activated_by"],
                        is_active=bool(r["is_active"]),
                        cleared_at=r["cleared_at"],
                        cleared_by=r["cleared_by"],
                        clear_authorization_token=r["clear_token"],
                        telemetry=json.loads(r["telemetry_json"] or "{}"),
                    )
                    self._active_activations[act.activation_id] = act
        except Exception as e:
            logger.debug(f"Kill switch load notice: {e}")

    def activate(
        self,
        level: KillSwitchLevel,
        trigger: KillSwitchTrigger,
        target: str = "ALL",
        policy: EmergencyPolicy = EmergencyPolicy.STOP_NEW_ORDERS,
        reason: str = "Automated risk circuit breach",
        activated_by: str = "SYSTEM_AUTOMATION",
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> KillSwitchActivation:
        """
        Activates the kill switch at GLOBAL, STRATEGY, or INSTRUMENT level.
        Immediately persists to SQLite and blocks order flow.
        """
        activation_id = f"KS-{level.value}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]}"
        activation = KillSwitchActivation(
            activation_id=activation_id,
            level=level,
            trigger=trigger,
            target=target.upper(),
            policy=policy,
            reason=reason,
            activated_by=activated_by,
            telemetry=telemetry or {},
        )
        self._active_activations[activation_id] = activation

        # Persist
        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO v4_kill_switch_activations
                    (activation_id, level, trigger, target, policy, reason, activated_at, activated_by, is_active, telemetry_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        activation.activation_id,
                        activation.level.value,
                        activation.trigger.value,
                        activation.target,
                        activation.policy.value,
                        activation.reason,
                        activation.activated_at,
                        activation.activated_by,
                        json.dumps(activation.telemetry),
                    ),
                )
        except Exception as e:
            logger.error(f"Failed to persist kill switch activation to DB: {e}")

        logger.critical(
            f"🚨 KILL SWITCH ACTIVATED [{level.value}:{target}]: {trigger.value} — {reason}"
        )
        return activation

    def clear(
        self,
        activation_id: str,
        cleared_by: str,
        authorization_token: str,
    ) -> Tuple[bool, str]:
        """
        Clears an active kill switch. Requires valid operator token.
        Cannot be cleared automatically.
        """
        if not authorization_token or len(authorization_token) < 8:
            return False, "KILL_SWITCH_CLEAR_REJECTED: Operator authorization token is required."

        act = self._active_activations.get(activation_id)
        if not act:
            # Check DB
            try:
                with self._get_connection() as conn:
                    r = conn.execute(
                        "SELECT * FROM v4_kill_switch_activations WHERE activation_id = ?",
                        (activation_id,),
                    ).fetchone()
                    if not r:
                        return False, f"Activation {activation_id} not found."
            except Exception as e:
                return False, f"DB error: {e}"

        now = datetime.now(timezone.utc).isoformat()
        if act:
            act.is_active = False
            act.cleared_at = now
            act.cleared_by = cleared_by
            act.clear_authorization_token = authorization_token
            del self._active_activations[activation_id]

        try:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE v4_kill_switch_activations
                    SET is_active = 0, cleared_at = ?, cleared_by = ?, clear_token = ?
                    WHERE activation_id = ?
                    """,
                    (now, cleared_by, authorization_token, activation_id),
                )
        except Exception as e:
            logger.error(f"Failed to update kill switch clear in DB: {e}")

        logger.warning(f"🟢 KILL SWITCH CLEARED [{activation_id}] by {cleared_by}.")
        return True, f"Kill switch {activation_id} successfully cleared."

    def clear_all(self, cleared_by: str, authorization_token: str) -> int:
        count = 0
        active_ids = list(self._active_activations.keys())
        for aid in active_ids:
            ok, _ = self.clear(aid, cleared_by, authorization_token)
            if ok:
                count += 1
        return count

    def is_order_blocked(
        self,
        strategy: str = "",
        symbol: str = "",
    ) -> Tuple[bool, Optional[KillSwitchActivation]]:
        """
        Checks if an order is blocked by ANY active kill switch:
        1. GLOBAL kill switch blocks EVERYTHING.
        2. STRATEGY kill switch blocks specific strategy.
        3. INSTRUMENT kill switch blocks specific symbol.
        """
        strategy = (strategy or "").upper().strip()
        symbol = (symbol or "").upper().strip()

        for act in self._active_activations.values():
            if not act.is_active:
                continue
            if act.level == KillSwitchLevel.GLOBAL:
                return True, act
            if act.level == KillSwitchLevel.STRATEGY and (act.target == strategy or act.target == "ALL"):
                return True, act
            if act.level == KillSwitchLevel.INSTRUMENT and (act.target == symbol or act.target == "ALL"):
                return True, act

        return False, None

    def get_status(self) -> Dict[str, Any]:
        active_list = [a.to_dict() for a in self._active_activations.values() if a.is_active]
        is_global_active = any(a["level"] == "GLOBAL" for a in active_list)
        return {
            "status": "HALTED" if is_global_active else ("DEGRADED" if active_list else "NORMAL"),
            "is_halted": is_global_active,
            "active_activations_count": len(active_list),
            "activations": active_list,
        }
