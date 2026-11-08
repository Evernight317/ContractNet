"""Tests for ConflictResolver."""

import pytest
from contractnet.core.conflict_resolver import ConflictResolver
from contractnet.core.types import Task, TaskDAG, TaskStatus, Conflict, ConflictType, ResolutionStrategy


class TestConflictResolver:
    def test_detect_no_conflicts_empty_dag(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        conflicts = resolver.detect(dag, None)
        assert len(conflicts) == 0

    def test_resolve_file_write(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="t1", task_type="code")
        t2 = Task(description="t2", task_type="code")
        dag.add_task(t1)
        dag.add_task(t2)
        conflict = Conflict(
            conflict_type=ConflictType.FILE_WRITE,
            task_ids=[t1.task_id, t2.task_id],
            description="File conflict",
        )
        resolution = resolver.resolve(conflict, dag)
        assert resolution.strategy == ResolutionStrategy.SERIALIZE
        # t2 should now depend on t1
        assert t1.task_id in t2.depends_on

    def test_resolve_deadlock(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="t1", task_type="code", retry_count=2)
        t2 = Task(description="t2", task_type="code", retry_count=0)
        t1.depends_on = [t2.task_id]
        t2.depends_on = [t1.task_id]
        t1.status = TaskStatus.RUNNING
        t2.status = TaskStatus.RUNNING
        dag.add_task(t1)
        dag.add_task(t2)

        conflict = Conflict(
            conflict_type=ConflictType.DEADLOCK,
            task_ids=[t1.task_id, t2.task_id],
            description="Circular wait",
        )
        resolution = resolver.resolve(conflict, dag)
        assert resolution.strategy == ResolutionStrategy.FORCE_TERMINATE
        # The task with higher retry_count should be terminated
        assert t1.status == TaskStatus.FAILED

    def test_dependency_violation_detection(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="dep", task_type="code")
        t2 = Task(description="dependent", task_type="code", depends_on=[t1.task_id])
        t1.status = TaskStatus.RUNNING  # not done yet
        t2.status = TaskStatus.RUNNING  # but t2 is running!
        dag.add_task(t1)
        dag.add_task(t2)
        conflicts = resolver.detect(dag, None)
        assert any(c.conflict_type == ConflictType.DEPENDENCY_VIOLATION for c in conflicts)

    def test_resolve_dependency_violation(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="dep", task_type="code")
        t2 = Task(description="dependent", task_type="code", depends_on=[t1.task_id])
        t2.status = TaskStatus.RUNNING
        dag.add_task(t1)
        dag.add_task(t2)
        conflict = Conflict(
            conflict_type=ConflictType.DEPENDENCY_VIOLATION,
            task_ids=[t2.task_id, t1.task_id],
        )
        resolution = resolver.resolve(conflict, dag)
        assert resolution.strategy == ResolutionStrategy.ROLLBACK_WAIT
        assert t2.status == TaskStatus.PENDING

    def test_conflict_history(self):
        resolver = ConflictResolver()
        dag = TaskDAG(goal_description="test")
        # Trigger a conflict
        t1 = Task(description="dep", task_type="code")
        t2 = Task(description="dependent", task_type="code", depends_on=[t1.task_id])
        t1.status = TaskStatus.RUNNING
        t2.status = TaskStatus.RUNNING
        dag.add_task(t1)
        dag.add_task(t2)
        resolver.detect(dag, None)
        history = resolver.get_conflict_history()
        assert len(history) > 0
