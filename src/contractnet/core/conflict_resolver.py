"""Conflict Resolver — detect and resolve conflicts between agents.

Implements optimistic concurrency control:
    Let agents execute in parallel → detect conflicts → resolve.

Conflict types:
    - file_write: two agents write the same file
    - interface_mismatch: function signature inconsistency
    - semantic_contradiction: contradictory conclusions
    - dependency_violation: reading incomplete artifact
    - deadlock: circular wait
"""

from __future__ import annotations

import logging

from contractnet.core.types import (
    Artifact,
    Conflict,
    ConflictType,
    Resolution,
    ResolutionStrategy,
    TaskDAG,
    TaskStatus,
)

logger = logging.getLogger(__name__)


class ConflictResolver:
    """Detect and resolve conflicts in multi-agent execution.

    Responsibilities:
        - Detect conflicts between artifacts (file, interface, semantic)
        - Detect deadlocks in task dependency graph
        - Select and apply resolution strategies

    Not responsible for:
        - Quality validation (Quality Gate)
        - Task execution
        - Re-planning (Orchestrator triggers this)
    """

    def __init__(self, quality_gate=None) -> None:
        self.quality_gate = quality_gate
        self._conflict_history: list[Conflict] = []

    def detect(self, dag: TaskDAG, state_store=None) -> list[Conflict]:
        """Detect all current conflicts.

        Scans for:
            1. File write conflicts (same path, different tasks)
            2. Deadlocks in task wait graph
            3. Dependency violations (running before dep done)
        """
        conflicts = []

        # 1. File write conflicts
        if state_store:
            conflicts.extend(self._detect_file_conflicts(state_store))

        # 2. Deadlocks
        deadlocks = self._detect_deadlocks(dag)
        conflicts.extend(deadlocks)

        # 3. Dependency violations
        dep_violations = self._detect_dependency_violations(dag)
        conflicts.extend(dep_violations)

        self._conflict_history.extend(conflicts)
        return conflicts

    def resolve(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Resolve a conflict using the appropriate strategy.

        Args:
            conflict: The detected conflict
            dag: Current task DAG (may be modified by resolution)

        Returns:
            Resolution with strategy and outcome
        """
        ct = conflict.conflict_type
        if ct == ConflictType.FILE_WRITE:
            return self._resolve_file_write(conflict, dag)
        elif ct == ConflictType.INTERFACE_MISMATCH:
            return self._resolve_interface_mismatch(conflict, dag)
        elif ct == ConflictType.SEMANTIC_CONTRADICTION:
            return self._resolve_semantic_contradiction(conflict, dag)
        elif ct == ConflictType.DEPENDENCY_VIOLATION:
            return self._resolve_dependency_violation(conflict, dag)
        elif ct == ConflictType.DEADLOCK:
            return self._resolve_deadlock(conflict, dag)
        else:
            return Resolution(strategy=ResolutionStrategy.SERIALIZE, reason="Unknown conflict type")

    def get_conflict_history(self) -> list[Conflict]:
        return list(self._conflict_history)

    # ──────────────────────────────────────────
    # Detection helpers
    # ──────────────────────────────────────────

    def _detect_file_conflicts(self, state_store) -> list[Conflict]:
        """Detect file write conflicts: two artifacts with same file_path from different tasks."""
        conflicts = []
        artifacts = state_store.get_all_artifacts()
        seen_paths: dict[str, str] = {}  # file_path → artifact_id

        for art in artifacts:
            if not art.file_path:
                continue
            if art.file_path in seen_paths:
                prev_id = seen_paths[art.file_path]
                prev_art = next((a for a in artifacts if a.artifact_id == prev_id), None)
                if prev_art and prev_art.task_id != art.task_id:
                    conflicts.append(Conflict(
                        conflict_type=ConflictType.FILE_WRITE,
                        task_ids=[prev_art.task_id, art.task_id],
                        artifact_ids=[prev_id, art.artifact_id],
                        description=f"File conflict: {art.file_path} written by tasks {prev_art.task_id} and {art.task_id}",
                    ))
            seen_paths[art.file_path] = art.artifact_id

        return conflicts

    def _detect_deadlocks(self, dag: TaskDAG) -> list[Conflict]:
        """Detect circular waits in the task dependency graph.

        Build wait-for graph and find cycles via DFS.
        """
        # Build wait-for: task_a → task_b means a is waiting for b
        wait_for: dict[str, set[str]] = {}
        for task in dag.tasks.values():
            if task.status in (TaskStatus.RUNNING, TaskStatus.AUCTIONING, TaskStatus.ASSIGNED):
                waiting_for = [
                    dep for dep in task.depends_on
                    if dep in dag.tasks and dag.tasks[dep].status != TaskStatus.DONE
                ]
                if waiting_for:
                    wait_for[task.task_id] = set(waiting_for)

        # Find cycles
        cycles = self._find_cycles(wait_for)
        conflicts = []
        for cycle in cycles:
            conflicts.append(Conflict(
                conflict_type=ConflictType.DEADLOCK,
                task_ids=cycle,
                description=f"Deadlock detected: circular wait among tasks {cycle}",
            ))

        return conflicts

    def _detect_dependency_violations(self, dag: TaskDAG) -> list[Conflict]:
        """Detect tasks running before their dependencies are complete."""
        violations = []
        for task in dag.tasks.values():
            if task.status not in (TaskStatus.RUNNING, TaskStatus.REVIEWING):
                continue
            for dep_id in task.depends_on:
                dep = dag.get_task(dep_id)
                if dep and dep.status != TaskStatus.DONE:
                    violations.append(Conflict(
                        conflict_type=ConflictType.DEPENDENCY_VIOLATION,
                        task_ids=[task.task_id, dep_id],
                        description=f"Task {task.task_id} running but dependency {dep_id} not done",
                    ))
        return violations

    def _find_cycles(self, graph: dict[str, set[str]]) -> list[list[str]]:
        """Find all simple cycles in a directed graph using DFS."""
        cycles = []
        visited_global: set[str] = set()

        def dfs(node: str, path: list[str], visited: set[str]) -> None:
            if node in visited:
                # Found a cycle
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle[:-1])  # exclude duplicate end node
                return
            visited.add(node)
            path.append(node)
            for neighbor in graph.get(node, set()):
                dfs(neighbor, path, visited)
            path.pop()
            visited.discard(node)

        for start in graph:
            if start not in visited_global:
                dfs(start, [], set())
                visited_global.add(start)

        return cycles

    # ──────────────────────────────────────────
    # Resolution strategies
    # ──────────────────────────────────────────

    def _resolve_file_write(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Serialize: make later task depend on earlier task."""
        if len(conflict.task_ids) >= 2:
            task_a, task_b = conflict.task_ids[0], conflict.task_ids[1]
            # Make task_b depend on task_a
            task = dag.get_task(task_b)
            if task and task_a not in task.depends_on:
                task.depends_on.append(task_a)
        return Resolution(
            strategy=ResolutionStrategy.SERIALIZE,
            reason=f"Serialized file write: tasks {conflict.task_ids}",
        )

    def _resolve_interface_mismatch(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Re-execute the dependent task after the interface-defining task."""
        return Resolution(
            strategy=ResolutionStrategy.REEXECUTE_DEPENDENT,
            reason=f"Re-execute dependent task after interface task",
        )

    def _resolve_semantic_contradiction(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Parallel compare: score both artifacts, pick the better one."""
        return Resolution(
            strategy=ResolutionStrategy.PARALLEL_COMPARE,
            reason=f"Parallel compare artifacts {conflict.artifact_ids}",
        )

    def _resolve_dependency_violation(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Rollback the violator and wait for dependency completion."""
        for task_id in conflict.task_ids:
            task = dag.get_task(task_id)
            if task:
                task.status = TaskStatus.PENDING
        return Resolution(
            strategy=ResolutionStrategy.ROLLBACK_WAIT,
            reason=f"Rolled back task to wait for dependency",
        )

    def _resolve_deadlock(self, conflict: Conflict, dag: TaskDAG) -> Resolution:
        """Force-terminate the task with highest retry_count in the cycle."""
        if conflict.task_ids:
            worst_task = max(
                conflict.task_ids,
                key=lambda tid: dag.tasks[tid].retry_count if tid in dag.tasks else -1,
            )
            task = dag.get_task(worst_task)
            if task:
                task.status = TaskStatus.FAILED
        return Resolution(
            strategy=ResolutionStrategy.FORCE_TERMINATE,
            reason=f"Force-terminated task {worst_task} to break deadlock",
        )
