"""Tests for Planner."""

import pytest
from contractnet.core.planner import Planner
from contractnet.core.types import Task, TaskDAG, TaskStatus


class TestPlanner:
    def test_fallback_decomposition(self):
        planner = Planner()  # no LLM → uses fallback
        dag = planner.plan("实现一个 REST API", {})
        assert len(dag.tasks) >= 3
        assert not dag.all_done()

    def test_decomposition_has_dependencies(self):
        planner = Planner()
        dag = planner.plan("实现一个 REST API", {})
        # At least one task should have dependencies
        has_deps = any(t.depends_on for t in dag.tasks.values())
        assert has_deps

    def test_decomposition_task_types(self):
        planner = Planner()
        dag = planner.plan("实现 API 并写测试", {})
        types = {t.task_type for t in dag.tasks.values()}
        assert len(types) >= 2  # should have multiple task types

    def test_replan_finer(self):
        planner = Planner()
        task = Task(description="Complex task", task_type="code", retry_count=3, max_retries=3)
        new_dag = planner.replan(task, "semantic validation failed")
        assert len(new_dag.tasks) >= 2  # decomposed into sub-tasks

    def test_replan_retry(self):
        planner = Planner()
        task = Task(description="Simple task", task_type="code", retry_count=1, max_retries=3)
        new_dag = planner.replan(task, "timeout")
        assert len(new_dag.tasks) >= 1
        new_task = list(new_dag.tasks.values())[0]
        assert new_task.retry_count == 2

    def test_add_task_incremental(self):
        planner = Planner()
        dag = planner.plan("实现 API", {})
        original_count = len(dag.tasks)
        new_task = Task(description="Extra task", task_type="review")
        planner.add_task(dag, new_task)
        assert len(dag.tasks) == original_count + 1
