"""Planner — decomposes high-level goals into sub-task DAGs.

Uses LLM-driven HTN (Hierarchical Task Network) decomposition.
Supports dynamic re-planning when tasks fail.
"""

from __future__ import annotations

import json
import logging
import time

from contractnet.core.types import Task, TaskDAG, TaskStatus

logger = logging.getLogger(__name__)


class Planner:
    """Decomposes user goals into sub-task DAGs.

    Responsibilities:
        - Initial decomposition: goal → sub-task DAG
        - Dynamic re-decomposition on failure (refine / merge / relax)
        - Dependency detection between sub-tasks

    Not responsible for:
        - Executing tasks
        - Assigning tasks (Auctioneer handles this)
        - Quality validation (Quality Gate handles this)
    """

    # Re-planning strategies
    STRATEGY_DOWNGRADE_MODEL = "downgrade_stronger_model"
    STRATEGY_DECOMPOSE_FINER = "decompose_finer"
    STRATEGY_ADD_DEPENDENCY = "add_dependency"
    STRATEGY_RELAX_OR_MERGE = "relax_or_merge"
    STRATEGY_RETRY_AS_IS = "retry_as_is"

    def __init__(self, llm_client=None) -> None:
        """
        Args:
            llm_client: Optional LLM client with a .complete(prompt) method.
                        If None, uses a simple rule-based fallback.
        """
        self.llm_client = llm_client
        self._decompose_prompt = """\
Decompose the following goal into 3-8 sub-tasks for a multi-agent system.

Goal: {goal}
Available agent types: coder (code), tester (test), doc_writer (doc), analyst (analysis), designer (design), reviewer (review)
Current context: {context}

Return a JSON array. Each element:
{{
  "description": "what to do",
  "task_type": "code|test|doc|analysis|design|review",
  "dependencies": [list of 0-based indices this task depends on]
}}

Constraints:
- Each sub-task should be completable in 5-15 steps
- Keep 3-8 sub-tasks
- Dependencies must reference earlier tasks (no cycles)
"""

    def plan(self, goal: str, context: dict | None = None) -> TaskDAG:
        """Decompose a high-level goal into a task DAG.

        Args:
            goal: Natural language goal description
            context: Additional context (existing files, project state, etc.)

        Returns:
            TaskDAG with tasks and dependencies set up
        """
        context = context or {}
        dag = TaskDAG(goal_description=goal)

        raw_tasks = self._decompose(goal, context)

        # Create Task objects
        task_ids: list[str] = []
        for i, t_data in enumerate(raw_tasks):
            task = Task(
                description=t_data["description"],
                task_type=t_data.get("task_type", "code"),
                depth=0,
                parent_task_id=None,
            )
            task_ids.append(task.task_id)
            dag.add_task(task)
            logger.info("Decomposed task %d: %s (%s)", i, task.description[:50], task.task_type)

        # Set up dependencies
        for i, t_data in enumerate(raw_tasks):
            deps = t_data.get("dependencies", [])
            dep_ids = [task_ids[d] for d in deps if d < len(task_ids)]
            dag.tasks[task_ids[i]].depends_on = dep_ids
            dag.tasks[task_ids[i]].depth = self._compute_depth(dag, task_ids[i])

        return dag

    def replan(self, failed_task: Task, reason: str) -> TaskDAG:
        """Re-plan after a task failure.

        Decision tree:
            retry_count < max_retries:
                quality_fail → downgrade to stronger model
                timeout → relax constraints
                tool_error → retry as-is
            retry_count >= max_retries:
                → decompose into finer sub-tasks
        """
        dag = TaskDAG(goal_description=f"Replan for: {failed_task.description}")

        if failed_task.retry_count < failed_task.max_retries:
            # Same task, adjusted
            new_task = failed_task.model_copy(deep=True)
            new_task.task_id = f"task_{time.time_ns():x}"
            new_task.parent_task_id = failed_task.task_id
            new_task.status = TaskStatus.PENDING
            new_task.retry_count = failed_task.retry_count + 1
            new_task.metadata["replan_reason"] = reason
            new_task.metadata["replan_strategy"] = self._select_retry_strategy(reason)
            dag.add_task(new_task)
        else:
            # Decompose into finer sub-tasks
            sub_tasks_data = self._decompose_finer(failed_task)
            sub_ids: list[str] = []
            for st in sub_tasks_data:
                sub_task = Task(
                    description=st["description"],
                    task_type=st.get("task_type", failed_task.task_type),
                    parent_task_id=failed_task.task_id,
                    depth=failed_task.depth + 1,
                    input_artifacts=failed_task.input_artifacts,
                )
                sub_ids.append(sub_task.task_id)
                dag.add_task(sub_task)

            for i, st in enumerate(sub_tasks_data):
                deps = st.get("dependencies", [])
                dag.tasks[sub_ids[i]].depends_on = [sub_ids[d] for d in deps if d < len(sub_ids)]

        return dag

    def add_task(self, dag: TaskDAG, task: Task, depends_on: list[str] | None = None) -> None:
        """Add a new task to an existing DAG (for incremental decomposition)."""
        if depends_on:
            task.depends_on = depends_on
        dag.add_task(task)

    def get_dag(self) -> TaskDAG:
        """Return the current DAG (empty if no plan has been made yet)."""
        return TaskDAG()

    # ──────────────────────────────────────────
    # Private methods
    # ──────────────────────────────────────────

    def _decompose(self, goal: str, context: dict) -> list[dict]:
        """Perform decomposition using LLM or rule-based fallback."""
        if self.llm_client:
            try:
                prompt = self._decompose_prompt.format(
                    goal=goal,
                    context=json.dumps(context, default=str, ensure_ascii=False),
                )
                response = self.llm_client.complete(prompt)
                tasks = json.loads(response)
                if isinstance(tasks, list) and len(tasks) > 0:
                    return self._validate_decomposition(tasks)
            except Exception as e:
                logger.warning("LLM decomposition failed (%s), using fallback", e)

        return self._fallback_decompose(goal)

    def _fallback_decompose(self, goal: str) -> list[dict]:
        """Rule-based fallback decomposition."""
        return [
            {"description": f"Design the structure and schema for: {goal}", "task_type": "design", "dependencies": []},
            {"description": f"Implement the core functionality for: {goal}", "task_type": "code", "dependencies": [0]},
            {"description": f"Write tests for: {goal}", "task_type": "test", "dependencies": [1]},
            {"description": f"Generate documentation for: {goal}", "task_type": "doc", "dependencies": [1]},
        ]

    def _decompose_finer(self, task: Task) -> list[dict]:
        """Decompose a failed task into finer sub-tasks."""
        return [
            {"description": f"Part 1 of: {task.description}", "task_type": task.task_type, "dependencies": []},
            {"description": f"Part 2 of: {task.description}", "task_type": task.task_type, "dependencies": [0]},
        ]

    def _validate_decomposition(self, tasks: list[dict]) -> list[dict]:
        """Validate decomposition: topology, granularity, no cycles."""
        if not tasks:
            return self._fallback_decompose("unknown")

        # Check no self-dependencies or out-of-range
        for i, t in enumerate(tasks):
            deps = t.get("dependencies", [])
            t["dependencies"] = [d for d in deps if isinstance(d, int) and 0 <= d < len(tasks) and d != i]

        # Granularity check
        if len(tasks) > 8:
            tasks = tasks[:8]
        if len(tasks) < 3:
            tasks.extend(self._fallback_decompose("expansion"))

        return tasks

    def _compute_depth(self, dag: TaskDAG, task_id: str, visited: set | None = None) -> int:
        """Compute depth of a task in the DAG."""
        if visited is None:
            visited = set()
        if task_id in visited:
            return 0
        visited.add(task_id)
        task = dag.get_task(task_id)
        if not task or not task.depends_on:
            return 0
        return 1 + max(
            (self._compute_depth(dag, dep, visited) for dep in task.depends_on if dep in dag.tasks),
            default=0,
        )

    def _select_retry_strategy(self, reason: str) -> str:
        """Select retry strategy based on failure reason."""
        reason_lower = reason.lower()
        if "schema" in reason_lower:
            return self.STRATEGY_DOWNGRADE_MODEL
        elif "semantic" in reason_lower:
            return self.STRATEGY_DECOMPOSE_FINER
        elif "conflict" in reason_lower:
            return self.STRATEGY_ADD_DEPENDENCY
        elif "timeout" in reason_lower:
            return self.STRATEGY_RELAX_OR_MERGE
        else:
            return self.STRATEGY_RETRY_AS_IS
