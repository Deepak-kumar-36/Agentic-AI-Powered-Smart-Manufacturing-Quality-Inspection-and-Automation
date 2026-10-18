"""Transactional local inspection persistence for the software-only runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class InspectionRecord:
    inspection_id: str
    idempotency_key: str
    status: str
    outcome: str | None
    reason_codes: tuple[str, ...]
    policy_version: str | None
    model_version: str | None
    score: float | None
    evidence: dict[str, Any]


class InspectionStore:
    """SQLite store with explicit transactions and immutable event rows."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        # The HTTP API uses a ThreadingHTTPServer. Serialize access to the
        # single local connection rather than creating an unbounded connection
        # per request.
        self._lock = RLock()
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self.connection.close()

    def _migrate(self) -> None:
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS inspections (
                    inspection_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    outcome TEXT,
                    reason_codes TEXT NOT NULL DEFAULT '[]',
                    policy_version TEXT,
                    model_version TEXT,
                    score REAL,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS inspection_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inspection_id TEXT NOT NULL REFERENCES inspections(inspection_id),
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_inspection ON inspection_events(inspection_id, event_id);
                """
            )

    def create(self, idempotency_key: str, payload: dict[str, Any]) -> InspectionRecord:
        with self._lock:
            if not idempotency_key.strip():
                raise ValueError("idempotency key must not be empty")
            request_hash = _request_hash(payload)
            existing = self.connection.execute(
                "SELECT * FROM inspections WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise ValueError("idempotency key reused with a different request")
                return self._record(existing)
            inspection_id = f"ins_{uuid4().hex}"
            now = _now()
            with self.connection:
                self.connection.execute(
                    "INSERT INTO inspections (inspection_id, idempotency_key, request_hash, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (inspection_id, idempotency_key, request_hash, "CREATED", now, now),
                )
                try:
                    self.connection.execute("ALTER TABLE inspections ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'")
                except sqlite3.OperationalError:
                    pass
                self._event(inspection_id, "inspection.created", payload)
            return self.get(inspection_id)

    def record_decision(
        self,
        inspection_id: str,
        *,
        outcome: str,
        reason_codes: list[str],
        policy_version: str,
        model_version: str | None,
        score: float | None,
        evidence: dict[str, Any] | None = None,
    ) -> InspectionRecord:
        with self._lock:
            if outcome not in {"PASS", "FAIL", "UNVERIFIED"}:
                raise ValueError("invalid outcome")
            now = _now()
            with self.connection:
                updated = self.connection.execute(
                    "UPDATE inspections SET status = ?, outcome = ?, reason_codes = ?, policy_version = ?, model_version = ?, score = ?, evidence_json = ?, updated_at = ? WHERE inspection_id = ?",
                    ("DECIDED", outcome, json.dumps(reason_codes), policy_version, model_version, score, json.dumps(evidence or {}, sort_keys=True), now, inspection_id),
                ).rowcount
                if updated != 1:
                    raise KeyError(inspection_id)
                self._event(inspection_id, "inspection.decision_recorded", {"outcome": outcome, "reason_codes": reason_codes})
            return self.get(inspection_id)

    def get(self, inspection_id: str) -> InspectionRecord:
        with self._lock:
            row = self.connection.execute("SELECT * FROM inspections WHERE inspection_id = ?", (inspection_id,)).fetchone()
            if row is None:
                raise KeyError(inspection_id)
            return self._record(row)

    def list(self, limit: int = 50) -> list[InspectionRecord]:
        with self._lock:
            if not 1 <= limit <= 100:
                raise ValueError("limit must be between 1 and 100")
            rows = self.connection.execute(
                "SELECT * FROM inspections ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._record(row) for row in rows]

    def events(self, inspection_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT event_type, payload, created_at FROM inspection_events WHERE inspection_id = ? ORDER BY event_id",
                (inspection_id,),
            ).fetchall()
            return [{"event_type": row["event_type"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]} for row in rows]

    def _event(self, inspection_id: str, event_type: str, payload: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO inspection_events (inspection_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (inspection_id, event_type, json.dumps(payload, sort_keys=True), _now()),
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> InspectionRecord:
        return InspectionRecord(
            inspection_id=row["inspection_id"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            outcome=row["outcome"],
            reason_codes=tuple(json.loads(row["reason_codes"])),
            policy_version=row["policy_version"],
            model_version=row["model_version"],
            score=row["score"],
            evidence=json.loads(row["evidence_json"] or "{}"),
        )
