"""Tests for ContractManager."""

import pytest
from contractnet.core.contract import ContractManager
from contractnet.core.types import Task, ContractStatus, ContractConstraints


class TestContractManager:
    def test_create_contract_from_task(self):
        cm = ContractManager()
        task = Task(description="Write API", task_type="code")
        contract = cm.create_contract(task)
        assert contract.task_id == task.task_id
        assert contract.description == "Write API"
        assert contract.status == ContractStatus.OPEN
        assert "file_write" in contract.constraints.required_tools
        assert "code_run" in contract.constraints.required_tools

    def test_create_contract_type_constraints(self):
        cm = ContractManager()
        for task_type, expected_tool in [
            ("code", "file_write"),
            ("test", "code_run"),
            ("doc", "file_write"),
            ("analysis", "code_run"),
        ]:
            task = Task(description=f"test {task_type}", task_type=task_type)
            contract = cm.create_contract(task)
            assert expected_tool in contract.constraints.required_tools, f"Failed for {task_type}"

    def test_award_contract(self):
        cm = ContractManager()
        from contractnet.core.types import Bid
        task = Task(description="test", task_type="code")
        contract = cm.create_contract(task)
        bid = Bid(contract_id=contract.contract_id, agent_id="agent_1",
                  capability_score=0.9, estimated_cost=500, estimated_steps=3, confidence=0.8)
        cm.award(contract, bid)
        assert contract.status == ContractStatus.AWARDED
        assert contract.awarded_agent_id == "agent_1"

    def test_cancel_contract(self):
        cm = ContractManager()
        task = Task(description="test", task_type="code")
        contract = cm.create_contract(task)
        cm.cancel(contract, "user requested")
        assert contract.status == ContractStatus.CANCELLED

    def test_get_active_contracts(self):
        cm = ContractManager()
        t1 = Task(description="t1", task_type="code")
        t2 = Task(description="t2", task_type="code")
        c1 = cm.create_contract(t1)
        c2 = cm.create_contract(t2)
        cm.close(c1)
        active = cm.get_active_contracts()
        assert len(active) == 1
        assert active[0].contract_id == c2.contract_id

    def test_get_contract_for_task(self):
        cm = ContractManager()
        task = Task(description="test", task_type="code")
        contract = cm.create_contract(task)
        found = cm.get_contract_for_task(task.task_id)
        assert found is not None
        assert found.contract_id == contract.contract_id
        assert cm.get_contract_for_task("nonexistent") is None
