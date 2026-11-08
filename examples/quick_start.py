from __future__ import annotations
"""Quick start example — run a goal through ContractNet."""

from contractnet.core.orchestrator import Orchestrator
from contractnet.core.planner import Planner
from contractnet.core.auctioneer import Auctioneer
from contractnet.core.quality_gate import QualityGate
from contractnet.core.conflict_resolver import ConflictResolver
from contractnet.core.contract import ContractManager
from contractnet.core.agent import BaseAgent, CapabilityProfile
from contractnet.core.types import Artifact, Contract
from contractnet.memory.state_store import StateStore
from contractnet.tools.builtins import ALL_PROFILES


class DemoAgent(BaseAgent):
    """A simple demo agent that generates text output."""

    def execute(self, contract: Contract, context: dict | None = None) -> Artifact:
        return Artifact(
            task_id=contract.task_id,
            content=f"[{self.profile.name}] Output for: {contract.description}\n"
                    f"Using model: {self.profile.model}\n"
                    f"Tools available: {', '.join(self.profile.tools)}",
            artifact_type="text",
        )


def main():
    # 1. Set up state store
    state_store = StateStore()

    # 2. Create orchestrator with all modules
    orchestrator = Orchestrator(
        planner=Planner(),
        auctioneer=Auctioneer(),
        quality_gate=QualityGate(state_store=state_store),
        conflict_resolver=ConflictResolver(),
        contract_manager=ContractManager(),
        state_store=state_store,
        max_concurrent=4,
    )

    # 3. Register agents
    for profile in ALL_PROFILES.values():
        orchestrator.register_agent(DemoAgent(profile))

    # 4. Run a goal
    goal = "实现一个带 JWT 认证的 Todo API，包含测试和文档"
    print(f"\n{'='*60}")
    print(f"Goal: {goal}")
    print(f"{'='*60}\n")

    result = orchestrator.run(goal)

    # 5. Print results
    print(f"\n{'='*60}")
    print("Execution Complete")
    print(f"{'='*60}")
    print(f"Success: {'✓' if result.success else '✗'}")
    print(f"Duration: {result.duration_s}s")
    print(f"Artifacts produced: {len(result.artifacts)}")
    print(f"Total tokens: {result.total_tokens}")
    print(f"\nMetrics:")
    for key, value in result.metrics.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2%}" if "rate" in key else f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")

    print(f"\nArtifacts:")
    for art in result.artifacts:
        print(f"\n--- {art.artifact_id} (type={art.artifact_type}, quality={art.quality_score}) ---")
        print(art.content[:300])


if __name__ == "__main__":
    main()
