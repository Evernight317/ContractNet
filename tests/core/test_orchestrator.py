"""Tests for Orchestrator."""

import pytest
from contractnet.core.orchestrator import Orchestrator
from contractnet.core.agent import BaseAgent, CapabilityProfile
from contractnet.core.types import Artifact, Contract


class StubAgent(BaseAgent):
    def execute(self, contract, context=None):
        return Artifact(
            task_id=contract.task_id,
            content=f"Generated: {contract.description}",
            artifact_type="text",
        )


class TestOrchestrator:
    def _build_orchestrator(self):
        orchestrator = Orchestrator(max_concurrent=2)
        from contractnet.tools.builtins import ALL_PROFILES
        for profile in ALL_PROFILES.values():
            orchestrator.register_agent(StubAgent(profile))
        return orchestrator

    def test_run_simple_goal(self):
        orchestrator = self._build_orchestrator()
        result = orchestrator.run("实现一个简单 API")
        assert result.goal == "实现一个简单 API"
        assert len(result.artifacts) > 0
        assert "task_completion_rate" in result.metrics

    def test_get_status(self):
        orchestrator = self._build_orchestrator()
        status = orchestrator.get_status()
        assert hasattr(status, "active_contracts")
        assert hasattr(status, "running_agents")

    def test_register_agent(self):
        orchestrator = Orchestrator()
        from contractnet.tools.builtins import CODER_PROFILE
        agent = StubAgent(CODER_PROFILE)
        orchestrator.register_agent(agent)
        assert agent.agent_id in orchestrator._agents

    def test_metrics_structure(self):
        orchestrator = self._build_orchestrator()
        result = orchestrator.run("实现 API")
        m = result.metrics
        assert "task_completion_rate" in m
        assert "total_tasks" in m
        assert "done_tasks" in m
        assert m["total_tasks"] > 0
