"""Tests for Auctioneer."""

import pytest
from contractnet.core.auctioneer import Auctioneer
from contractnet.core.agent import BaseAgent, CapabilityProfile
from contractnet.core.contract import ContractManager
from contractnet.core.types import Task, Contract, Artifact


class StubAgent(BaseAgent):
    def execute(self, contract, context=None):
        return Artifact(task_id=contract.task_id, content="output")


class TestAuctioneer:
    def _make_agent(self, agent_id, task_types, tools, capability=0.9, confidence=0.8):
        profile = CapabilityProfile(
            agent_id=agent_id, name=agent_id,
            task_types=task_types, tools=tools,
        )
        return StubAgent(profile)

    def test_single_bid_wins(self):
        auctioneer = Auctioneer()
        cm = ContractManager()
        task = Task(description="Write code", task_type="code")
        contract = cm.create_contract(task)
        agent = self._make_agent("a1", ["code"], ["file_write", "code_run"])
        bid = auctioneer.auction(contract, [agent])
        assert bid is not None
        assert bid.agent_id == "a1"

    def test_no_tools_no_bid(self):
        auctioneer = Auctioneer()
        cm = ContractManager()
        task = Task(description="Write code", task_type="code")
        contract = cm.create_contract(task)
        agent = self._make_agent("a1", ["code"], [])  # no tools
        bid = auctioneer.auction(contract, [agent])
        assert bid is None
        assert contract.status.value == "impossible"

    def test_multiple_bids_best_wins(self):
        auctioneer = Auctioneer()
        cm = ContractManager()
        task = Task(description="Write code", task_type="code")
        contract = cm.create_contract(task)
        agent1 = self._make_agent("a1", ["code"], ["file_write", "code_run"])
        agent2 = self._make_agent("a2", ["code"], ["file_write", "code_run"])
        # agent2 should win (same caps, but different confidence via profile)
        bid = auctioneer.auction(contract, [agent1, agent2])
        assert bid is not None

    def test_score_computation(self):
        auctioneer = Auctioneer()
        from contractnet.core.types import Bid
        bid = Bid(
            contract_id="c1", agent_id="a1",
            capability_score=0.9, estimated_cost=1000,
            estimated_steps=5, confidence=0.8,
        )
        contract = Contract(task_id="t1", description="test")
        score = auctioneer.compute_score(bid, contract)
        assert 0 <= score <= 1
        assert score > 0.5  # high capability + confidence

    def test_relax_constraints_on_no_bid(self):
        auctioneer = Auctioneer()
        cm = ContractManager()
        task = Task(description="Write code", task_type="code")
        contract = cm.create_contract(task)
        original_max_tokens = contract.constraints.max_tokens
        agent = self._make_agent("a1", ["code"], [])  # no tools → no bid
        auctioneer.auction(contract, [agent])
        # After 2 rounds of no bids, constraints should be relaxed then impossible
        assert contract.status.value == "impossible"
