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


@dataclass(frozen=True)
class InspectionReview:
    review_id: str
    inspection_id: str
    outcome: str
    defect_type: str | None
    note: str | None
    created_at: str
    model_version: str | None
    input_image_hash: str | None


@dataclass(frozen=True)
class ReviewAnalytics:
    total_inspections: int
    reviewed_inspections: int
    unreviewed_inspections: int
    review_coverage_percent: float
    review_records: int
    outcome_distribution: dict[str, int]
    agreement_count: int
    disagreement_count: int
    comparable_inspections: int
    conflicting_review_inspections: int
    unverified_inspections: int
    awaiting_attention: int
    items: list[dict[str, Any]]
    page: int
    page_size: int
    total_items: int


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
                CREATE TABLE IF NOT EXISTS inspection_reviews (
                    review_id TEXT PRIMARY KEY,
                    inspection_id TEXT NOT NULL REFERENCES inspections(inspection_id),
                    outcome TEXT NOT NULL,
                    defect_type TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    model_version TEXT,
                    input_image_hash TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_inspection ON inspection_reviews(inspection_id, created_at, review_id);
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

    def add_review(self, inspection_id: str, *, outcome: str, defect_type: str | None = None, note: str | None = None) -> InspectionReview:
        with self._lock:
            record = self.get(inspection_id)
            provenance = self.connection.execute(
                "SELECT payload FROM inspection_events WHERE inspection_id = ? AND event_type = 'inspection.created' ORDER BY event_id LIMIT 1",
                (inspection_id,),
            ).fetchone()
            payload = json.loads(provenance["payload"]) if provenance else {}
            image_hash = payload.get("image_sha256") if isinstance(payload.get("image_sha256"), str) else None
            if image_hash is None:
                encoded = record.evidence.get("input_image_data")
                if isinstance(encoded, str) and encoded.startswith("data:"):
                    image_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            review = InspectionReview(uuid4().hex, inspection_id, outcome, defect_type, note, _now(), record.model_version, image_hash)
            with self.connection:
                self.connection.execute(
                    "INSERT INTO inspection_reviews (review_id, inspection_id, outcome, defect_type, note, created_at, model_version, input_image_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (review.review_id, review.inspection_id, review.outcome, review.defect_type, review.note, review.created_at, review.model_version, review.input_image_hash),
                )
                self._event(inspection_id, "inspection.review_recorded", {"review_id": review.review_id, "outcome": outcome, "defect_type": defect_type})
            return review

    def reviews(self, inspection_id: str) -> list[InspectionReview]:
        with self._lock:
            self.get(inspection_id)
            rows = self.connection.execute(
                "SELECT review_id, inspection_id, outcome, defect_type, note, created_at, model_version, input_image_hash FROM inspection_reviews WHERE inspection_id = ? ORDER BY created_at, rowid",
                (inspection_id,),
            ).fetchall()
            return [InspectionReview(**dict(row)) for row in rows]

    def review_analytics(
        self, *, page: int = 1, page_size: int = 25, review_outcome: str | None = None,
        ai_outcome: str | None = None, comparison: str | None = None,
        review_state: str | None = None,
    ) -> ReviewAnalytics:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("page must be positive and page_size must be between 1 and 100")
        allowed = {
            "review_outcome": {"CONFIRMED_NORMAL", "CONFIRMED_DEFECT", "INCONCLUSIVE"},
            "ai_outcome": {"PASS", "FAIL", "UNVERIFIED"},
            "comparison": {"AGREEMENT", "DISAGREEMENT", "NOT_COMPARABLE"},
            "review_state": {"REVIEWED", "UNREVIEWED", "INCONCLUSIVE", "CONFLICT", "ATTENTION"},
        }
        for name, value in (("review_outcome", review_outcome), ("ai_outcome", ai_outcome), ("comparison", comparison), ("review_state", review_state)):
            if value is not None and value not in allowed[name]:
                raise ValueError(f"invalid {name}")
        with self._lock:
            base = """
                WITH ranked AS (
                    SELECT r.*, ROW_NUMBER() OVER (PARTITION BY inspection_id ORDER BY created_at DESC, rowid DESC) AS rn
                    FROM inspection_reviews r
                ), stats AS (
                    SELECT inspection_id, COUNT(*) AS review_count, COUNT(DISTINCT outcome) AS outcome_count
                    FROM inspection_reviews GROUP BY inspection_id
                ), states AS (
                    SELECT i.inspection_id, i.outcome AS ai_outcome, i.model_version,
                           l.outcome AS latest_review_outcome, l.defect_type, l.note,
                           l.created_at AS review_created_at, COALESCE(s.review_count, 0) AS review_count,
                           COALESCE(s.outcome_count, 0) AS outcome_count,
                           CASE WHEN l.outcome = 'CONFIRMED_NORMAL' AND i.outcome = 'PASS' THEN 'AGREEMENT'
                                WHEN l.outcome = 'CONFIRMED_DEFECT' AND i.outcome = 'FAIL' THEN 'AGREEMENT'
                                WHEN l.outcome IN ('CONFIRMED_NORMAL', 'CONFIRMED_DEFECT') AND i.outcome IN ('PASS', 'FAIL') THEN 'DISAGREEMENT'
                                ELSE 'NOT_COMPARABLE' END AS comparison
                    FROM inspections i LEFT JOIN ranked l ON l.inspection_id = i.inspection_id AND l.rn = 1
                    LEFT JOIN stats s ON s.inspection_id = i.inspection_id
                )
            """
            rows = self.connection.execute(base + "SELECT * FROM states").fetchall()
            total = len(rows)
            reviewed = sum(row["review_count"] > 0 for row in rows)
            distribution = {key: 0 for key in ("CONFIRMED_NORMAL", "CONFIRMED_DEFECT", "INCONCLUSIVE")}
            for row in rows:
                if row["latest_review_outcome"] in distribution:
                    distribution[row["latest_review_outcome"]] += 1
            agreement = sum(row["comparison"] == "AGREEMENT" for row in rows)
            disagreement = sum(row["comparison"] == "DISAGREEMENT" for row in rows)
            comparable = agreement + disagreement
            conflicts = sum(row["outcome_count"] > 1 for row in rows)
            unverified = sum(row["ai_outcome"] == "UNVERIFIED" for row in rows)
            attention = sum(row["ai_outcome"] == "UNVERIFIED" or row["review_count"] == 0 or row["latest_review_outcome"] == "INCONCLUSIVE" or row["outcome_count"] > 1 for row in rows)
            filtered = []
            for row in rows:
                if review_outcome and row["latest_review_outcome"] != review_outcome: continue
                if ai_outcome and row["ai_outcome"] != ai_outcome: continue
                if comparison and row["comparison"] != comparison: continue
                state = "CONFLICT" if row["outcome_count"] > 1 else "UNREVIEWED" if row["review_count"] == 0 else "INCONCLUSIVE" if row["latest_review_outcome"] == "INCONCLUSIVE" else "REVIEWED"
                if review_state == "ATTENTION" and not (row["ai_outcome"] == "UNVERIFIED" or state in {"UNREVIEWED", "INCONCLUSIVE", "CONFLICT"}): continue
                if review_state and review_state != "ATTENTION" and state != review_state: continue
                filtered.append({"inspection_id": row["inspection_id"], "ai_outcome": row["ai_outcome"], "latest_review_outcome": row["latest_review_outcome"], "defect_type": row["defect_type"], "note": row["note"], "review_created_at": row["review_created_at"], "review_count": row["review_count"], "conflicting_reviews": row["outcome_count"] > 1, "comparison": row["comparison"]})
            start = (page - 1) * page_size
            return ReviewAnalytics(total, reviewed, total - reviewed, round(reviewed / total * 100, 2) if total else 0.0, sum(row["review_count"] for row in rows), distribution, agreement, disagreement, comparable, conflicts, unverified, attention, filtered[start:start + page_size], page, page_size, len(filtered))

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
