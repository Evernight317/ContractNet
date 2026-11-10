"""Orchestrator — central controller that drives the full execution lifecycle.

Strings together: Planner → Auctioneer → Agent → QualityGate → ConflictResolver.
Manages task state machines, concurrency, and re-planning decisions.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from dataclasses import dataclass, field

from contractnet.core.agent import BaseAgent, ExecutionRecord
from contractnet.core.auctioneer import Auctioneer
from contractnet.core.conflict_resolver import ConflictResolver
from contractnet.core.contract import ContractManager
from contractnet.core.planner import Planner
from contractnet.core.quality_gate import QualityGate
from contractnet.core.types import (
    Artifact,
    Contract,
    ContractStatus,
    QualityResult,
    Task,
    TaskDAG,
    TaskStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class FinalResult:
    """Result of a complete goal execution."""
    goal: str
    artifacts: list[Artifact] = field(default_factory=list)
    success: bool = False
    duration_s: float = 0.0
    total_tokens: int = 0
    metrics: dict = field(default_factory=dict)


@dataclass
class SystemStatus:
    """Current system status snapshot."""
    total_tasks: int = 0
    done_tasks: int = 0
    failed_tasks: int = 0
    active_contracts: int = 0
    running_agents: list[str] = field(default_factory=list)


class Orchestrator:
    """Central controller for the ContractNet framework.

    Responsibilities:
        - Drive the main execution loop
        - Manage task state transitions
        - Coordinate all modules (Planner, Auctioneer, QualityGate, etc.)
        - Handle concurrency (max parallel agents)
        - Trigger re-planning on failure

    Not responsible for:
        - Decomposition details (Planner)
        - Bid scoring details (Auctioneer)
        - Quality check details (QualityGate)
        - Conflict resolution details (ConflictResolver)
    """

    def __init__(
        self,
        planner: Planner | None = None,
        auctioneer: Auctioneer | None = None,
        quality_gate: QualityGate | None = None,
        conflict_resolver: ConflictResolver | None = None,
        contract_manager: ContractManager | None = None,
        state_store=None,
        max_concurrent: int = 4,
    ) -> None:
        self.planner = planner or Planner()
        self.auctioneer = auctioneer or Auctioneer()
        self.quality_gate = quality_gate or QualityGate()
        self.conflict_resolver = conflict_resolver or ConflictResolver()
        self.contract_manager = contract_manager or ContractManager()
        self.state_store = state_store

        self._agents: dict[str, BaseAgent] = {}
        self._agent_locks: dict[str, Lock] = {}
        self._max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._total_tokens = 0
        self._current_dag: TaskDAG | None = None
        self._cancelled_tasks: set[str] = set()

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent for the auction pool."""
        self._agents[agent.agent_id] = agent
        self._agent_locks[agent.agent_id] = Lock()

    def run(self, goal: str, context: dict | None = None) -> FinalResult:
        """Execute a goal end-to-end.

        Main loop:
            1. Decompose goal → DAG
            2. Find ready tasks → create contracts → auction → award
            3. Execute awarded contracts (concurrent)
            4. Quality gate review
            5. Handle failures (retry / re-plan)
            6. Detect & resolve conflicts
            7. Repeat until all tasks done
            8. Merge artifacts → FinalResult
        """
        start_time = time.time()
        context = context or {}
        all_artifacts: list[Artifact] = []

        # Phase 1: Decompose
        dag = self.planner.plan(goal, context)
        self._current_dag = dag
        logger.info("Goal decomposed into %d tasks", len(dag.tasks))

        # Main loop
        while not dag.all_done():
            ready_tasks = dag.get_ready_tasks()

            if not ready_tasks:
                # No ready tasks — check for stuck state
                logger.warning("No ready tasks but DAG not done — checking for deadlock")
                conflicts = self.conflict_resolver.detect(dag, self.state_store)
                for conflict in conflicts:
                    self.conflict_resolver.resolve(conflict, dag)
                if not conflicts:
                    break  # Truly stuck
                continue

            # Phase 2-3: Auction & Execute ready tasks
            futures: dict[str, Future] = {}
            for task in ready_tasks:
                if task.task_id in self._cancelled_tasks:
                    dag.update_status(task.task_id, TaskStatus.FAILED)
                    continue
                contract = self.contract_manager.create_contract(task)
                self.contract_manager.open_bidding(contract)

                agents = list(self._agents.values())
                winning_bid = self.auctioneer.auction(contract, agents)

                if winning_bid is None:
                    self._handle_impossible(task, dag)
                    continue

                agent = self._agents.get(winning_bid.agent_id)
                if not agent:
                    logger.error("Winning agent %s not found", winning_bid.agent_id)
                    continue

                self.contract_manager.award(contract, winning_bid)
                dag.update_status(task.task_id, TaskStatus.ASSIGNED)

                # Execute async
                future = self._executor.submit(
                    self._execute_task, task, contract, agent,
                )
                futures[task.task_id] = future

            # Phase 4-5: Collect results
            for task_id, future in futures.items():
                try:
                    artifact = future.result(timeout=120)
                    task = dag.get_task(task_id)
                    if not task:
                        continue

                    # Quality gate
                    contract = self.contract_manager.get_contract_for_task(task_id)
                    quality_result = self.quality_gate.review(artifact, contract) if contract else QualityResult(passed=True)

                    if quality_result.passed:
                        dag.update_status(task_id, TaskStatus.DONE)
                        artifact.quality_score = quality_result.score
                        all_artifacts.append(artifact)
                        if self.state_store:
                            self.state_store.save_artifact(artifact)
                        logger.info("Task %s DONE (quality=%.2f)", task_id, quality_result.score)
                    else:
                        self._handle_failure(task, dag, quality_result)

                except Exception as e:
                    logger.error("Task %s execution error: %s", task_id, e)
                    task = dag.get_task(task_id)
                    if task:
                        self._handle_failure(task, dag, QualityResult(passed=False, feedback=str(e)))

            # Phase 6: Conflict detection
            conflicts = self.conflict_resolver.detect(dag, self.state_store)
            for conflict in conflicts:
                resolution = self.conflict_resolver.resolve(conflict, dag)
                logger.info("Resolved conflict: %s → %s", conflict.conflict_type, resolution.strategy)

        # Phase 8: Merge
        duration = time.time() - start_time
        success = all(t.status == TaskStatus.DONE for t in dag.tasks.values())

        return FinalResult(
            goal=goal,
            artifacts=all_artifacts,
            success=success,
            duration_s=round(duration, 2),
            total_tokens=self._total_tokens,
            metrics=self._compute_metrics(dag),
        )

    def get_status(self) -> SystemStatus:
        """Get current system status snapshot."""
        dag = self._current_dag
        total = len(dag.tasks) if dag else 0
        done = sum(1 for t in dag.tasks.values() if t.status == TaskStatus.DONE) if dag else 0
        failed = sum(1 for t in dag.tasks.values() if t.status in (TaskStatus.FAILED, TaskStatus.IMPOSSIBLE)) if dag else 0
        return SystemStatus(
            total_tasks=total,
            done_tasks=done,
            failed_tasks=failed,
            active_contracts=len(self.contract_manager.get_active_contracts()),
            running_agents=[aid for aid, a in self._agents.items() if a.is_busy],
        )

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task — marks it as FAILED so the main loop skips it."""
        self._cancelled_tasks.add(task_id)
        if self._current_dag:
            self._current_dag.update_status(task_id, TaskStatus.FAILED)
        logger.info("Task %s cancelled", task_id)

    def inject_human_feedback(self, task_id: str, feedback: str) -> None:
        """Inject human feedback for a task (for human-in-the-loop).

        Attaches feedback to the task metadata so downstream agents can
        reference it on retry or re-plan.
        """
        if self._current_dag:
            task = self._current_dag.get_task(task_id)
            if task:
                task.metadata["human_feedback"] = feedback
                logger.info("Human feedback recorded for task %s", task_id)
            else:
                logger.warning("Task %s not found in current DAG", task_id)
        else:
            logger.warning("No active DAG — cannot inject feedback")

    # ──────────────────────────────────────────
    # Private methods
    # ──────────────────────────────────────────

    def _execute_task(self, task: Task, contract: Contract, agent: BaseAgent) -> Artifact:
        """Execute a single task via the assigned agent."""
        try:
            lock = self._agent_locks.get(agent.agent_id)
            if lock and lock.acquire(blocking=False):
                try:
                    agent._busy = True
                    artifact = agent.execute(contract)
                    # Accumulate token usage from agent execution log
                    if hasattr(agent, "_execution_log") and agent._execution_log:
                        last = agent._execution_log[-1]
                        self._total_tokens += last.tokens_used
                    return artifact
                finally:
                    agent._busy = False
                    lock.release()
            else:
                # Agent busy — return empty artifact (will be retried)
                return Artifact(task_id=task.task_id, content="", artifact_type="text")
        except Exception as e:
            logger.error("Agent %s execution failed: %s", agent.agent_id, e)
            raise

    def _handle_impossible(self, task: Task, dag: TaskDAG) -> None:
        """Handle tasks that no agent can fulfill."""
        dag.update_status(task.task_id, TaskStatus.IMPOSSIBLE)
        logger.warning("Task %s marked impossible (no agent available)", task.task_id)

    def _handle_failure(self, task: Task, dag: TaskDAG, quality_result: QualityResult) -> None:
        """Handle task failure: retry or re-plan."""
        task.retry_count += 1
        if task.retry_count < task.max_retries:
            dag.update_status(task.task_id, TaskStatus.PENDING)
            logger.info(
                "Task %s retry %d/%d (reason: %s)",
                task.task_id, task.retry_count, task.max_retries,
                quality_result.feedback[:100],
            )
        else:
            # Re-plan
            new_dag = self.planner.replan(task, quality_result.feedback)
            dag.update_status(task.task_id, TaskStatus.REPLANNED)
            for new_task in new_dag.tasks.values():
                dag.add_task(new_task)
            logger.info("Task %s re-planned into %d sub-tasks", task.task_id, len(new_dag.tasks))

    def _compute_metrics(self, dag: TaskDAG) -> dict:
        """Compute summary metrics for the execution."""
        tasks = list(dag.tasks.values())
        total = len(tasks)
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        failed = sum(1 for t in tasks if t.status == TaskStatus.FAILED)

        return {
            "task_completion_rate": done / total if total > 0 else 0.0,
            "task_failure_rate": failed / total if total > 0 else 0.0,
            "total_tasks": total,
            "done_tasks": done,
            "failed_tasks": failed,
            "total_tokens": self._total_tokens,
        }
