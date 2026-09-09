# =============================================================================
# event_agent/jobs/job_ledger.py — Persistent Job Runs Ledger
# =============================================================================
"""
V3.6.1 Persistent Job Ledger.
Stores immutable audit records of all background and scheduled data collection runs.
Every scheduled run creates a job_runs record with exact execution metrics,
timings, source counts, error logs, and cryptographic hashes.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "job_runs.db"


@dataclass
class JobRunRecord:
    id: Optional[int]
    run_id: str
    job_name: str
    started_at: str
    completed_at: Optional[str]
    duration_ms: int
    status: str                        # "RUNNING" | "SUCCESS" | "PARTIAL" | "FAILED" | "SKIPPED"
    records_fetched: int
    records_processed: int
    records_rejected: int
    sources_attempted: int
    sources_succeeded: int
    sources_failed: int
    data_quality: str                  # "HEALTHY" | "DEGRADED" | "UNAVAILABLE"
    error_message: Optional[str]
    config_hash: str
    code_commit: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class JobLedger:
    """
    SQLite-backed audit repository for all background job executions.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    job_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_ms INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    records_fetched INTEGER NOT NULL,
                    records_processed INTEGER NOT NULL,
                    records_rejected INTEGER NOT NULL,
                    sources_attempted INTEGER NOT NULL,
                    sources_succeeded INTEGER NOT NULL,
                    sources_failed INTEGER NOT NULL,
                    data_quality TEXT NOT NULL,
                    error_message TEXT,
                    config_hash TEXT NOT NULL,
                    code_commit TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def create_run(
        self,
        job_name: str,
        config_hash: str = "v361_default_cfg",
        code_commit: str = "545c2cd",
    ) -> JobRunRecord:
        """Initializes a new job run in RUNNING status."""
        now = datetime.now(timezone.utc)
        run_hash = hashlib.sha256(f"{job_name}:{now.isoformat()}".encode("utf-8")).hexdigest()[:8]
        run_id = f"RUN-{now.strftime('%Y%m%d-%H%M%S')}-{run_hash}"

        record = JobRunRecord(
            id=None,
            run_id=run_id,
            job_name=job_name,
            started_at=now.isoformat(),
            completed_at=None,
            duration_ms=0,
            status="RUNNING",
            records_fetched=0,
            records_processed=0,
            records_rejected=0,
            sources_attempted=0,
            sources_succeeded=0,
            sources_failed=0,
            data_quality="RUNNING",
            error_message=None,
            config_hash=config_hash,
            code_commit=code_commit,
            created_at=now.isoformat(),
        )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_runs (
                    run_id, job_name, started_at, completed_at, duration_ms,
                    status, records_fetched, records_processed, records_rejected,
                    sources_attempted, sources_succeeded, sources_failed,
                    data_quality, error_message, config_hash, code_commit, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.run_id, record.job_name, record.started_at, record.completed_at,
                    record.duration_ms, record.status, record.records_fetched,
                    record.records_processed, record.records_rejected,
                    record.sources_attempted, record.sources_succeeded,
                    record.sources_failed, record.data_quality, record.error_message,
                    record.config_hash, record.code_commit, record.created_at,
                ),
            )
            record.id = cursor.lastrowid
            conn.commit()

        logger.info("Started job run: %s (%s)", record.job_name, record.run_id)
        return record

    def complete_run(
        self,
        run_id: str,
        status: str,
        records_fetched: int,
        records_processed: int,
        records_rejected: int,
        sources_attempted: int,
        sources_succeeded: int,
        sources_failed: int,
        data_quality: str,
        error_message: Optional[str] = None,
    ) -> JobRunRecord:
        """Completes an existing run with duration and metrics."""
        now = datetime.now(timezone.utc)
        completed_at_iso = now.isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT started_at FROM job_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Job run {run_id} not found in database.")

            start_dt = datetime.fromisoformat(row[0])
            duration_ms = int((now - start_dt).total_seconds() * 1000.0)

            conn.execute(
                """
                UPDATE job_runs SET
                    completed_at = ?,
                    duration_ms = ?,
                    status = ?,
                    records_fetched = ?,
                    records_processed = ?,
                    records_rejected = ?,
                    sources_attempted = ?,
                    sources_succeeded = ?,
                    sources_failed = ?,
                    data_quality = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                (
                    completed_at_iso, duration_ms, status, records_fetched,
                    records_processed, records_rejected, sources_attempted,
                    sources_succeeded, sources_failed, data_quality,
                    error_message, run_id,
                ),
            )
            conn.commit()

        logger.info("Completed job run: %s status=%s in %dms", run_id, status, duration_ms)
        return self.get_run_by_id(run_id)

    def get_run_by_id(self, run_id: str) -> Optional[JobRunRecord]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT * FROM job_runs WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def get_run(self, run_id: str) -> Optional[JobRunRecord]:
        """Alias for get_run_by_id."""
        return self.get_run_by_id(run_id)

    def get_recent_runs(self, limit: int = 50) -> List[JobRunRecord]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM job_runs ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def get_failed_runs(self, limit: int = 20) -> List[JobRunRecord]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT * FROM job_runs WHERE status IN ('FAILED', 'PARTIAL') ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def _row_to_record(self, row: tuple) -> JobRunRecord:
        return JobRunRecord(
            id=row[0],
            run_id=row[1],
            job_name=row[2],
            started_at=row[3],
            completed_at=row[4],
            duration_ms=row[5],
            status=row[6],
            records_fetched=row[7],
            records_processed=row[8],
            records_rejected=row[9],
            sources_attempted=row[10],
            sources_succeeded=row[11],
            sources_failed=row[12],
            data_quality=row[13],
            error_message=row[14],
            config_hash=row[15],
            code_commit=row[16],
            created_at=row[17],
        )
