"""State Store — global state management with Redis (hot) + SQLite (cold).

Hot layer: current DAG state, active contracts, agent status (TTL: 1h after completion)
Cold layer: all artifacts (versioned), execution traces, bid history, quality records
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from contractnet.core.types import (
    Artifact,
    Contract,
    TaskDAG,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class StateStore:
    """Global state store with hot (Redis) and cold (SQLite) layers.

    Responsibilities:
        - Store and retrieve artifacts (with version management)
        - Maintain task DAG state
        - Store contracts and bids
        - Support snapshot/restore for replay

    Redis is optional: if no redis_client is passed and auto-connect
    fails (no Redis server running), the store silently degrades to
    SQLite-only mode with an in-memory dict for hot data.

    Not responsible for:
        - Agent-local memory (AgentMemory handles this)
        - Quality validation
        - Conflict detection
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        redis_client=None,
        auto_connect_redis: bool = True,
    ) -> None:
        """
        Args:
            db_path: Path for SQLite cold storage. None = in-memory.
            redis_client: Optional Redis client for hot layer.
                         If None and auto_connect_redis is True, attempts
                         to connect to localhost:6379; on failure falls
                         back to in-memory dict (SQLite-only mode).
        """
        self.redis = redis_client
        if self.redis is None and auto_connect_redis:
            self.redis = self._try_connect_redis()
        self._hot: dict[str, str] = {}  # fallback if no Redis
        self._db_path = db_path
        self._conn = sqlite3.connect(
            str(db_path) if db_path else ":memory:",
            check_same_thread=False,
        )
        self._init_db()

    @staticmethod
    def _try_connect_redis():
        """Attempt to connect to a local Redis server; return client or None."""
        try:
            import redis
            client = redis.Redis(host="localhost", port=6379, decode_responses=True)
            client.ping()
            logger.info("Redis connected at localhost:6379 — hot layer active")
            return client
        except ImportError:
            logger.debug("redis package not installed — using SQLite-only mode")
            return None
        except Exception:
            logger.info("Redis not available — using SQLite-only mode")
            return None

    def _init_db(self) -> None:
        """Initialize SQLite schema."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                task_id TEXT,
                artifact_type TEXT,
                content TEXT,
                file_path TEXT,
                schema_validated INTEGER,
                quality_score REAL,
                created_at REAL,
                version INTEGER,
                parent_versions TEXT
            );
            CREATE TABLE IF NOT EXISTS contracts (
                contract_id TEXT PRIMARY KEY,
                task_id TEXT,
                description TEXT,
                status TEXT,
                awarded_agent_id TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS dag_snapshot (
                goal_id TEXT PRIMARY KEY,
                dag_json TEXT,
                timestamp REAL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
        """)
        self._conn.commit()

    # ──────────────────────────────────────────
    # Artifacts
    # ──────────────────────────────────────────

    def save_artifact(self, artifact: Artifact) -> str:
        """Save a new artifact version (auto-increment version)."""
        existing = self._get_artifacts_by_task(artifact.task_id)
        if existing:
            artifact.parent_versions = [a["artifact_id"] for a in existing]
            artifact.version = max(a["version"] for a in existing) + 1

        self._conn.execute(
            """INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                artifact.artifact_id, artifact.task_id, artifact.artifact_type,
                artifact.content, artifact.file_path,
                int(artifact.schema_validated), artifact.quality_score,
                artifact.created_at, artifact.version,
                json.dumps(artifact.parent_versions),
            ),
        )
        self._conn.commit()
        logger.debug("Saved artifact %s v%d for task %s", artifact.artifact_id, artifact.version, artifact.task_id)
        return artifact.artifact_id

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Retrieve a single artifact by ID."""
        row = self._conn.execute(
            "SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,),
        ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_all_artifacts(self) -> list[Artifact]:
        """Retrieve all artifacts (latest version per task)."""
        rows = self._conn.execute(
            """SELECT * FROM artifacts WHERE artifact_id IN (
                SELECT artifact_id FROM artifacts a1
                WHERE version = (SELECT MAX(version) FROM artifacts a2 WHERE a2.task_id = a1.task_id)
            )""",
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    def get_artifact_history(self, task_id: str) -> list[Artifact]:
        """Get all versions of an artifact for a task."""
        rows = self._conn.execute(
            "SELECT * FROM artifacts WHERE task_id=? ORDER BY version", (task_id,),
        ).fetchall()
        return [self._row_to_artifact(r) for r in rows]

    # ──────────────────────────────────────────
    # DAG
    # ──────────────────────────────────────────

    def save_dag(self, dag: TaskDAG) -> None:
        """Persist DAG snapshot."""
        dag_json = dag.model_dump_json()
        self._conn.execute(
            """INSERT OR REPLACE INTO dag_snapshot VALUES (?,?,?)""",
            (dag.goal_id, dag_json, time.time()),
        )
        self._conn.commit()

    def get_dag(self) -> TaskDAG | None:
        """Retrieve latest DAG."""
        row = self._conn.execute(
            "SELECT dag_json FROM dag_snapshot ORDER BY timestamp DESC LIMIT 1",
        ).fetchone()
        return TaskDAG.model_validate_json(row[0]) if row else None

    # ──────────────────────────────────────────
    # Contracts
    # ──────────────────────────────────────────

    def save_contract(self, contract: Contract) -> None:
        """Persist a contract."""
        self._conn.execute(
            """INSERT OR REPLACE INTO contracts VALUES (?,?,?,?,?,?)""",
            (
                contract.contract_id, contract.task_id, contract.description,
                contract.status.value, contract.awarded_agent_id, contract.created_at,
            ),
        )
        self._conn.commit()

    def get_active_contracts(self) -> list[Contract]:
        """Get non-terminal contracts."""
        terminal = {"closed", "cancelled", "impossible"}
        rows = self._conn.execute("SELECT * FROM contracts").fetchall()
        return [
            self._row_to_contract(r) for r in rows
            if r[3] not in terminal
        ]

    # ──────────────────────────────────────────
    # Snapshot / Restore
    # ──────────────────────────────────────────

    def snapshot(self) -> dict:
        """Create a snapshot of current state for replay."""
        artifacts = self.get_all_artifacts()
        return {
            "artifacts": [a.model_dump() for a in artifacts],
            "timestamp": time.time(),
        }

    def restore(self, snapshot: dict) -> None:
        """Restore from a snapshot."""
        for art_data in snapshot.get("artifacts", []):
            art = Artifact.model_validate(art_data)
            self.save_artifact(art)

    # ──────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────

    def _get_artifacts_by_task(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT artifact_id, version FROM artifacts WHERE task_id=?", (task_id,),
        ).fetchall()
        return [{"artifact_id": r[0], "version": r[1]} for r in rows]

    def _row_to_artifact(self, row) -> Artifact:
        return Artifact(
            artifact_id=row[0], task_id=row[1], artifact_type=row[2],
            content=row[3], file_path=row[4],
            schema_validated=bool(row[5]),
            quality_score=row[6], created_at=row[7],
            version=row[8],
            parent_versions=json.loads(row[9]) if row[9] else [],
        )

    def _row_to_contract(self, row) -> Contract:
        return Contract(
            contract_id=row[0], task_id=row[1], description=row[2],
            status=row[3], awarded_agent_id=row[4], created_at=row[5],
        )

    def close(self) -> None:
        self._conn.close()
