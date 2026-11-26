"""Thread-safe SQLite store for sources, edit jobs, and approval audit records."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from video_mcp.models import (
    ApprovalDecision,
    ApprovalRecord,
    EditJob,
    JobStatus,
    OutputProfile,
    RenderedArtifact,
    SourceAsset,
    SourceKind,
    TranscriptSegment,
    utc_now_iso,
)


class JobStore:
    """SQLite persistence for video automation state and approval audit trails."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;

                CREATE TABLE IF NOT EXISTS sources (
                    source_id TEXT PRIMARY KEY,
                    uri TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    filename TEXT NOT NULL,
                    probe_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_ids_json TEXT NOT NULL,
                    operations_json TEXT NOT NULL,
                    output_profile TEXT NOT NULL,
                    status TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    approval_id TEXT,
                    publish_records_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reviewer TEXT,
                    notes TEXT,
                    artifact_checksums_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS activity_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    job_id TEXT,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS transcripts (
                    source_id TEXT PRIMARY KEY,
                    segments_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES sources(source_id) ON DELETE CASCADE
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------

    def save_source(self, source: SourceAsset) -> SourceAsset:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sources (
                    source_id, uri, kind, local_path, sha256, size_bytes,
                    filename, probe_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    local_path=excluded.local_path,
                    sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes,
                    probe_json=excluded.probe_json
                """,
                (
                    source.source_id,
                    source.uri,
                    source.kind.value,
                    source.local_path,
                    source.sha256,
                    source.size_bytes,
                    source.filename,
                    json.dumps(source.probe),
                    source.created_at,
                ),
            )
        return source

    def get_source(self, source_id: str) -> SourceAsset | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        return self._row_to_source(row) if row else None

    def get_source_by_sha256(self, sha256: str) -> SourceAsset | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sources WHERE sha256 = ? LIMIT 1", (sha256,)
            ).fetchone()
        return self._row_to_source(row) if row else None

    def list_sources(self, limit: int = 50) -> list[SourceAsset]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sources ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_source(r) for r in rows]

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> SourceAsset:
        return SourceAsset(
            source_id=row["source_id"],
            uri=row["uri"],
            kind=SourceKind(row["kind"]),
            local_path=row["local_path"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            filename=row["filename"],
            probe=json.loads(row["probe_json"]),
            created_at=row["created_at"],
        )

    # ------------------------------------------------------------------
    # Jobs
    # ------------------------------------------------------------------

    def save_job(self, job: EditJob) -> EditJob:
        job.updated_at = utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    job_id, title, source_ids_json, operations_json,
                    output_profile, status, artifacts_json, approval_id,
                    publish_records_json, error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    title=excluded.title,
                    source_ids_json=excluded.source_ids_json,
                    operations_json=excluded.operations_json,
                    output_profile=excluded.output_profile,
                    status=excluded.status,
                    artifacts_json=excluded.artifacts_json,
                    approval_id=excluded.approval_id,
                    publish_records_json=excluded.publish_records_json,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    job.job_id,
                    job.title,
                    json.dumps(job.source_ids),
                    json.dumps(job.operations),
                    job.output_profile.value,
                    job.status.value,
                    json.dumps([a.model_dump() for a in job.artifacts]),
                    job.approval_id,
                    json.dumps(job.publish_records),
                    job.error,
                    job.created_at,
                    job.updated_at,
                ),
            )
        return job

    def get_job(self, job_id: str) -> EditJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, status: JobStatus | None = None, limit: int = 50) -> list[EditJob]:
        with self._lock:
            if status is not None:
                rows = self._conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_job(r) for r in rows]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> EditJob:
        return EditJob(
            job_id=row["job_id"],
            title=row["title"],
            source_ids=json.loads(row["source_ids_json"]),
            operations=json.loads(row["operations_json"]),
            output_profile=OutputProfile(row["output_profile"]),
            status=JobStatus(row["status"]),
            artifacts=[RenderedArtifact(**a) for a in json.loads(row["artifacts_json"])],
            approval_id=row["approval_id"],
            publish_records=json.loads(row["publish_records_json"]),
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def save_approval(self, record: ApprovalRecord) -> ApprovalRecord:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO approvals (
                    approval_id, job_id, decision, reviewer, notes,
                    artifact_checksums_json, created_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO UPDATE SET
                    decision=excluded.decision,
                    reviewer=excluded.reviewer,
                    notes=excluded.notes,
                    decided_at=excluded.decided_at
                """,
                (
                    record.approval_id,
                    record.job_id,
                    record.decision.value,
                    record.reviewer,
                    record.notes,
                    json.dumps(record.artifact_checksums),
                    record.created_at,
                    record.decided_at,
                ),
            )
        return record

    def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        return self._row_to_approval(row) if row else None

    def list_approvals(
        self, decision: ApprovalDecision | None = None, limit: int = 50
    ) -> list[ApprovalRecord]:
        with self._lock:
            if decision is not None:
                rows = self._conn.execute(
                    "SELECT * FROM approvals WHERE decision = ? ORDER BY created_at DESC LIMIT ?",
                    (decision.value, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._row_to_approval(r) for r in rows]

    @staticmethod
    def _row_to_approval(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"],
            job_id=row["job_id"],
            decision=ApprovalDecision(row["decision"]),
            reviewer=row["reviewer"],
            notes=row["notes"],
            artifact_checksums=json.loads(row["artifact_checksums_json"]),
            created_at=row["created_at"],
            decided_at=row["decided_at"],
        )

    # ------------------------------------------------------------------
    # Activity Events
    # ------------------------------------------------------------------

    def log_activity(
        self,
        category: str,
        message: str,
        level: str = "info",
        job_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        created_at = utc_now_iso()
        details_dict = details or {}
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO activity_events (
                    category, level, message, job_id, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (category, level, message, job_id, json.dumps(details_dict), created_at),
            )
            event_id = cursor.lastrowid
        return {
            "event_id": event_id,
            "category": category,
            "level": level,
            "message": message,
            "job_id": job_id,
            "details": details_dict,
            "created_at": created_at,
        }

    def list_activity(
        self,
        limit: int = 100,
        since_id: int | None = None,
        job_id: str | None = None,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if since_id is not None:
            clauses.append("event_id > ?")
            params.append(since_id)
        if job_id is not None:
            clauses.append("job_id = ?")
            params.append(job_id)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "ASC" if since_id is not None else "DESC"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM activity_events {where_sql} ORDER BY event_id {order} LIMIT ?",
                tuple(params),
            ).fetchall()
        return [
            {
                "event_id": r["event_id"],
                "category": r["category"],
                "level": r["level"],
                "message": r["message"],
                "job_id": r["job_id"],
                "details": json.loads(r["details_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Transcript Cache & Stale Job Recovery
    # ------------------------------------------------------------------

    def save_transcript(self, source_id: str, segments: list[TranscriptSegment]) -> None:
        now = utc_now_iso()
        payload = json.dumps([s.model_dump() for s in segments])
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transcripts (source_id, segments_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    segments_json=excluded.segments_json,
                    created_at=excluded.created_at
                """,
                (source_id, payload, now),
            )

    def get_transcript(self, source_id: str) -> list[TranscriptSegment] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT segments_json FROM transcripts WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return [TranscriptSegment(**item) for item in json.loads(row["segments_json"])]

    def recover_stale_rendering_jobs(self) -> list[str]:
        """Mark any jobs left in `rendering` from a prior crash as `failed`."""
        stale = self.list_jobs(status=JobStatus.RENDERING, limit=200)
        recovered_ids: list[str] = []
        for job in stale:
            job.status = JobStatus.FAILED
            job.error = "Interrupted by server restart while rendering"
            job.approval_id = None
            self.save_job(job)
            self.log_activity(
                category="render",
                level="error",
                message=f"Recovered stale rendering job '{job.title}' as failed after restart",
                job_id=job.job_id,
            )
            recovered_ids.append(job.job_id)
        return recovered_ids

