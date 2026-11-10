"""Agent base class and capability profile system."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from contractnet.core.types import (
    Artifact,
    Bid,
    Contract,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Agent Performance
# ──────────────────────────────────────────────

class AgentPerformance(BaseModel):
    total_tasks: int = 0
    success_rate: float = 0.0
    avg_cost: int = 0
    avg_steps: int = 0
    avg_quality: float = 0.0
    last_updated: float = Field(default_factory=time.time)


# ──────────────────────────────────────────────
# Capability Profile
# ──────────────────────────────────────────────

class CapabilityProfile(BaseModel):
    agent_id: str
    name: str
    task_types: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    model: str | None = None
    self_assessed_skills: dict[str, float] = Field(default_factory=dict)
    historical_performance: dict[str, AgentPerformance] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# Execution Record
# ──────────────────────────────────────────────

class ExecutionRecord(BaseModel):
    task_id: str
    contract_id: str
    task_type: str
    description: str
    steps_taken: int = 0
    tokens_used: int = 0
    success: bool = False
    quality_score: float | None = None
    feedback: str | None = None
    timestamp: float = Field(default_factory=time.time)


# ──────────────────────────────────────────────
# Failure Pattern & Success Template (for AgentMemory)
# ──────────────────────────────────────────────

class FailurePattern(BaseModel):
    task_type: str
    common_feedback: str
    occurrence_count: int = 1


class SuccessTemplate(BaseModel):
    task_type: str
    description: str
    steps_taken: int
    quality_score: float


# ──────────────────────────────────────────────
# Agent Base Class
# ──────────────────────────────────────────────

class BaseAgent(ABC):
    """Abstract base class for all agents.

    Each agent can:
        - Bid on contracts that match its capability
        - Execute awarded contracts via ReAct loop
        - Maintain execution history and update performance

    Agents do NOT communicate directly — all collaboration via Contract Bus.
    """

    def __init__(self, profile: CapabilityProfile) -> None:
        self.profile = profile
        self.memory = None  # lazily initialized to avoid circular import
        self._busy = False

    @property
    def agent_id(self) -> str:
        return self.profile.agent_id

    @property
    def is_busy(self) -> bool:
        return self._busy

    @abstractmethod
    def execute(self, contract: Contract, context: dict | None = None) -> Artifact:
        """Execute a contract and produce an artifact.

        Subclasses implement the actual ReAct loop:
            Think → Act(tool_call) → Observe → repeat until done or deadline.
        """
        ...

    def bid(self, contract: Contract) -> Bid | None:
        """Evaluate whether to bid on this contract.

        Decision logic:
            1. Check required_tools availability (hard filter)
            2. Compute capability_score and confidence
            3. Skip if capability below threshold (0.3)
        """
        # Step 1: required tools check (hard filter)
        missing_tools = [
            t for t in contract.constraints.required_tools
            if t not in self.profile.tools
        ]
        if missing_tools:
            logger.debug(
                "Agent %s skipping contract %s: missing tools %s",
                self.agent_id, contract.contract_id, missing_tools,
            )
            return None

        # Step 2: compute scores
        capability_score = self._compute_capability(contract)
        confidence = self._compute_confidence(contract)

        if capability_score < 0.3:
            logger.debug(
                "Agent %s skipping contract %s: low capability %.2f",
                self.agent_id, contract.contract_id, capability_score,
            )
            return None

        # Step 3: estimate cost
        estimated_cost = self._estimate_cost(contract)
        estimated_steps = min(contract.constraints.max_steps, contract.deadline_steps)

        return Bid(
            contract_id=contract.contract_id,
            agent_id=self.agent_id,
            capability_score=capability_score,
            estimated_cost=estimated_cost,
            estimated_steps=estimated_steps,
            confidence=confidence,
            execution_plan=f"Agent {self.profile.name} will execute using {self.profile.model}",
        )

    def record_execution(self, record: ExecutionRecord) -> None:
        """Record execution result and update performance metrics."""
        if self.memory is None:
            from contractnet.memory.agent_memory import AgentMemory
            self.memory = AgentMemory(self.profile)
        self.memory.record_execution(record)

    def get_execution_log(self) -> list[ExecutionRecord]:
        if self.memory is None:
            return []
        return self.memory.get_execution_log()

    # ──────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────

    def _compute_capability(self, contract: Contract) -> float:
        """Compute capability match score [0, 1].

        capability = 0.6 * type_match + 0.4 * tool_match
        """
        # Task type overlap
        if "*" in self.profile.task_types:
            type_match = 1.0
        else:
            contract_desc = contract.description.lower()
            matches = [1.0 if tt in contract_desc else 0.0 for tt in self.profile.task_types]
            type_match = max(matches, default=0.5)

        # Tool coverage
        required = contract.constraints.required_tools
        if required:
            covered = sum(1 for t in required if t in self.profile.tools)
            tool_match = covered / len(required)
        else:
            tool_match = 1.0

        return 0.6 * type_match + 0.4 * tool_match

    def _compute_confidence(self, contract: Contract) -> float:
        """Compute confidence based on static + dynamic assessment.

        confidence = 0.4 * static_match + 0.6 * dynamic_performance
        """
        static = self._compute_capability(contract)

        # Dynamic: historical performance for similar task types
        # Infer task type from contract description
        task_type = self._infer_task_type_from_contract(contract)
        perf = self.profile.historical_performance.get(task_type)
        if perf and perf.total_tasks > 0:
            dynamic = 0.5 * perf.success_rate + 0.5 * perf.avg_quality
        else:
            dynamic = 0.5  # neutral prior

        return 0.4 * static + 0.6 * dynamic

    def _estimate_cost(self, contract: Contract) -> int:
        """Estimate token cost for executing this contract."""
        base_cost = contract.constraints.max_tokens
        task_type = self._infer_task_type_from_contract(contract)
        perf = self.profile.historical_performance.get(task_type)
        if perf and perf.avg_cost > 0:
            return int(0.5 * base_cost + 0.5 * perf.avg_cost)
        return base_cost

    def _update_performance(self, record: ExecutionRecord) -> None:
        """Update capability profile with execution results."""
        key = record.task_type
        perf = self.profile.historical_performance.get(key, AgentPerformance())
        n = perf.total_tasks
        perf.total_tasks = n + 1
        perf.success_rate = (n * perf.success_rate + int(record.success)) / (n + 1)
        perf.avg_cost = (n * perf.avg_cost + record.tokens_used) // (n + 1)
        perf.avg_steps = (n * perf.avg_steps + record.steps_taken) // (n + 1)
        if record.quality_score is not None:
            perf.avg_quality = (n * perf.avg_quality + record.quality_score) / (n + 1)
        perf.last_updated = time.time()
        self.profile.historical_performance[key] = perf

    @staticmethod
    def _infer_task_type_from_contract(contract: Contract) -> str:
        """Infer task type from contract description for performance lookup."""
        desc = contract.description.lower()
        for ttype in ("code", "test", "doc", "analysis", "design", "review"):
            if ttype in desc:
                return ttype
        return "general"
