"""Tests for core type definitions."""

import pytest
from contractnet.core.types import (
    Task, TaskStatus, TaskDAG,
    Contract, ContractStatus, ContractConstraints,
    Bid, Artifact, QualityResult, ValidationResult, ValidationLayer,
    Conflict, ConflictType, Resolution, ResolutionStrategy,
)


class TestTask:
    def test_task_creation_defaults(self):
        task = Task(description="Write API", task_type="code")
        assert task.task_id.startswith("task_")
        assert task.status == TaskStatus.PENDING
        assert task.retry_count == 0
        assert task.max_retries == 3
        assert task.depends_on == []

    def test_task_with_dependencies(self):
        task = Task(description="Write tests", task_type="test", depends_on=["task_abc"])
        assert task.depends_on == ["task_abc"]


class TestTaskDAG:
    def test_empty_dag_all_done(self):
        dag = TaskDAG(goal_description="empty")
        assert dag.all_done() is True

    def test_get_ready_tasks_no_deps(self):
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="Task 1", task_type="code")
        dag.add_task(t1)
        ready = dag.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == t1.task_id

    def test_get_ready_tasks_with_deps(self):
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="Task 1", task_type="code")
        t2 = Task(description="Task 2", task_type="code", depends_on=[t1.task_id])
        dag.add_task(t1)
        dag.add_task(t2)

        ready = dag.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == t1.task_id

        # Mark t1 done → t2 becomes ready
        dag.update_status(t1.task_id, TaskStatus.DONE)
        ready = dag.get_ready_tasks()
        assert len(ready) == 1
        assert ready[0].task_id == t2.task_id

    def test_all_done(self):
        dag = TaskDAG(goal_description="test")
        t1 = Task(description="T1", task_type="code")
        t2 = Task(description="T2", task_type="code")
        dag.add_task(t1)
        dag.add_task(t2)
        assert not dag.all_done()

        dag.update_status(t1.task_id, TaskStatus.DONE)
        dag.update_status(t2.task_id, TaskStatus.DONE)
        assert dag.all_done()

    def test_merge(self):
        dag1 = TaskDAG(goal_description="main")
        dag2 = TaskDAG(goal_description="sub")
        t1 = Task(description="T1", task_type="code")
        t2 = Task(description="T2", task_type="code")
        dag1.add_task(t1)
        dag2.add_task(t2)
        dag1.merge(dag2)
        assert len(dag1.tasks) == 2


class TestContract:
    def test_contract_defaults(self):
        c = Contract(task_id="task_1", description="Do something")
        assert c.status == ContractStatus.OPEN
        assert c.constraints.max_tokens == 5000
        assert c.deadline_steps == 15

    def test_contract_constraints(self):
        constraints = ContractConstraints(
            max_tokens=10000, max_steps=20,
            required_tools=["file_write"], quality_threshold=0.9,
        )
        c = Contract(task_id="task_1", description="test", constraints=constraints)
        assert c.constraints.max_tokens == 10000
        assert c.constraints.quality_threshold == 0.9


class TestBid:
    def test_bid_defaults(self):
        bid = Bid(contract_id="ctr_1", agent_id="agent_1",
                  capability_score=0.8, estimated_cost=1000, estimated_steps=5, confidence=0.7)
        assert bid.bid_id.startswith("bid_")
        assert 0 <= bid.capability_score <= 1


class TestArtifact:
    def test_artifact_defaults(self):
        art = Artifact(task_id="task_1", content="hello")
        assert art.artifact_id.startswith("art_")
        assert art.version == 1
        assert art.artifact_type == "text"
        assert art.parent_versions == []
