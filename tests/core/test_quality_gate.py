"""Tests for QualityGate."""

import pytest
from contractnet.core.quality_gate import QualityGate
from contractnet.core.types import Artifact, Contract, ContractConstraints, QualityResult


class TestQualityGate:
    def test_schema_pass_non_json(self):
        gate = QualityGate()
        artifact = Artifact(task_id="t1", content="hello world")
        contract = Contract(task_id="t1", description="Write a greeting")
        result = gate.review(artifact, contract)
        # Non-JSON: schema passes, semantic passes (no judge), impact passes
        assert result.passed

    def test_schema_fail_invalid_json(self):
        gate = QualityGate()
        artifact = Artifact(task_id="t1", content='{"name": "test"}')
        contract = Contract(
            task_id="t1", description="test",
            output_schema={"type": "object", "required": ["name", "age"], "properties": {"name": {"type": "string"}, "age": {"type": "integer"}}},
        )
        result = gate.review(artifact, contract)
        assert not result.passed
        assert "schema" in result.feedback.lower()

    def test_short_circuit_on_schema_fail(self):
        gate = QualityGate()
        artifact = Artifact(task_id="t1", content='{"name": 123}')  # wrong type
        contract = Contract(
            task_id="t1", description="test",
            output_schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        )
        result = gate.review(artifact, contract)
        assert not result.passed
        # Only schema layer should have run
        layers = [d.layer.value for d in result.details]
        assert "schema" in layers
        assert "semantic" not in layers  # short-circuited

    def test_no_judge_passes_semantic(self):
        gate = QualityGate()  # no judge client
        artifact = Artifact(task_id="t1", content="some output")
        contract = Contract(task_id="t1", description="test", constraints=ContractConstraints(quality_threshold=0.8))
        result = gate.review(artifact, contract)
        assert result.passed

    def test_impact_file_conflict(self):
        from contractnet.memory.state_store import StateStore
        state_store = StateStore()
        # Save an artifact with a file path
        art1 = Artifact(task_id="t1", content="content1", file_path="/app/main.py")
        state_store.save_artifact(art1)
        gate = QualityGate(state_store=state_store)
        # New artifact with same file path but different task
        art2 = Artifact(task_id="t2", content="content2", file_path="/app/main.py")
        contract = Contract(task_id="t2", description="test")
        result = gate.review(art2, contract)
        # Impact layer should detect conflict
        assert not result.passed
        assert "conflict" in result.feedback.lower()
