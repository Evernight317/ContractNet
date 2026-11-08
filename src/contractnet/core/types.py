"""Global data structures shared across all modules.

Defined with Pydantic v2 for runtime validation and serialization.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


def _gen_id(prefix: str = "") -> str:
    """Generate a unique ID with optional prefix."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ──────────────────────────────────────────────
# Task
# ──────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    AUCTIONING = "auctioning"
    ASSIGNED = "assigned"
    RUNNING = "running"
    REVIEWING = "reviewing"
    DONE = "done"
    FAILED = "failed"
    REPLANNED = "replanned"
    IMPOSSIBLE = "impossible"


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: _gen_id("task_"))
    parent_task_id: str | None = None
    description: str
    task_type: str  # "code" | "test" | "doc" | "analysis" | "design" | "review"
    input_artifacts: list[str] = Field(default_factory=list)
    output_artifact_id: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    depth: int = 0
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = Field(default_factory=time.time)
    depends_on: list[str] = Field(default_factory=list)  # task_ids this depends on
    metadata: dict = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Contract Constraints & Contract
# ──────────────────────────────────────────────

class ContractConstraints(BaseModel):
    max_tokens: int = 5000
    max_steps: int = 10
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    quality_threshold: float = 0.8
    preferred_model: str | None = None


class ContractStatus(str, Enum):
    OPEN = "open"
    BIDDING = "bidding"
    AWARDED = "awarded"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    IMPOSSIBLE = "impossible"


class Contract(BaseModel):
    contract_id: str = Field(default_factory=lambda: _gen_id("ctr_"))
    task_id: str
    description: str
    input_artifacts: list[str] = Field(default_factory=list)
    output_schema: dict = Field(default_factory=lambda: {"type": "string"})
    constraints: ContractConstraints = Field(default_factory=ContractConstraints)
    deadline_steps: int = 15
    status: ContractStatus = ContractStatus.OPEN
    created_at: float = Field(default_factory=time.time)
    awarded_bid_id: str | None = None
    awarded_agent_id: str | None = None


# ──────────────────────────────────────────────
# Bid
# ──────────────────────────────────────────────

class Bid(BaseModel):
    bid_id: str = Field(default_factory=lambda: _gen_id("bid_"))
    contract_id: str
    agent_id: str
    capability_score: float  # [0, 1]
    estimated_cost: int  # tokens
    estimated_steps: int
    confidence: float  # [0, 1]
    execution_plan: str = ""
    timestamp: float = Field(default_factory=time.time)


# ──────────────────────────────────────────────
# Artifact
# ──────────────────────────────────────────────

class Artifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: _gen_id("art_"))
    task_id: str
    artifact_type: str = "text"  # "code" | "text" | "data" | "report" | "config"
    content: str
    file_path: str | None = None
    schema_validated: bool = False
    quality_score: float | None = None
    created_at: float = Field(default_factory=time.time)
    version: int = 1
    parent_versions: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Quality Result
# ──────────────────────────────────────────────

class ValidationLayer(str, Enum):
    SCHEMA = "schema"
    SEMANTIC = "semantic"
    IMPACT = "impact"


class ValidationResult(BaseModel):
    passed: bool
    layer: ValidationLayer
    score: float = 0.0
    feedback: str = ""


class QualityResult(BaseModel):
    passed: bool
    score: float = 0.0
    feedback: str = ""
    details: list[ValidationResult] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Conflict
# ──────────────────────────────────────────────

class ConflictType(str, Enum):
    FILE_WRITE = "file_write"
    INTERFACE_MISMATCH = "interface_mismatch"
    SEMANTIC_CONTRADICTION = "semantic_contradiction"
    DEPENDENCY_VIOLATION = "dependency_violation"
    DEADLOCK = "deadlock"


class Conflict(BaseModel):
    conflict_id: str = Field(default_factory=lambda: _gen_id("conf_"))
    conflict_type: ConflictType
    task_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    description: str = ""
    detected_at: float = Field(default_factory=time.time)


class ResolutionStrategy(str, Enum):
    SERIALIZE = "serialize"
    REEXECUTE_DEPENDENT = "reexecute_dependent"
    PARALLEL_COMPARE = "parallel_compare"
    ROLLBACK_WAIT = "rollback_wait"
    FORCE_TERMINATE = "force_terminate"


class Resolution(BaseModel):
    strategy: ResolutionStrategy
    winner_artifact_id: str | None = None
    loser_artifact_id: str | None = None
    reason: str = ""


# ──────────────────────────────────────────────
# Task DAG
# ──────────────────────────────────────────────

class TaskDAG(BaseModel):
    goal_id: str = Field(default_factory=lambda: _gen_id("goal_"))
    goal_description: str = ""
    tasks: dict[str, Task] = Field(default_factory=dict)

    def add_task(self, task: Task) -> None:
        self.tasks[task.task_id] = task

    def get_ready_tasks(self) -> list[Task]:
        """Return tasks whose dependencies are all DONE and status is PENDING."""
        ready = []
        for task in self.tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_done = all(
                self.tasks[dep].status == TaskStatus.DONE
                for dep in task.depends_on
                if dep in self.tasks
            )
            if deps_done:
                ready.append(task)
        return ready

    def all_done(self) -> bool:
        """Check if all tasks are in a terminal state."""
        terminal = {TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.IMPOSSIBLE}
        return all(t.status in terminal for t in self.tasks.values())

    def get_task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].status = status

    def merge(self, other: "TaskDAG") -> None:
        """Merge another DAG's tasks into this one."""
        self.tasks.update(other.tasks)
