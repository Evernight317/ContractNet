"""CLI entry point for ContractNet.

Commands:
    contractnet run <goal>           Submit a goal for execution
    contractnet status [--task-id]   View current status
    contractnet dag [--task-id]      View task DAG
    contractnet agent <agent_id>     View agent details
    contractnet conflicts [--task-id] View conflict log
    contractnet replay <goal_id>     Replay execution
    contractnet eval <goal_id>       Export evaluation report
    contractnet dashboard [--port]   Launch web dashboard
"""

from __future__ import annotations

import json
import logging
import sys

import click

from contractnet.core.orchestrator import Orchestrator
from contractnet.core.planner import Planner
from contractnet.core.auctioneer import Auctioneer
from contractnet.core.quality_gate import QualityGate
from contractnet.core.conflict_resolver import ConflictResolver
from contractnet.core.contract import ContractManager
from contractnet.memory.state_store import StateStore
from contractnet.observability.tracer import Tracer, MetricsCollector
from contractnet.observability.dashboard import render_dag_graph, render_trace_tree, render_metrics_table
from contractnet.tools.builtins import ALL_PROFILES

logger = logging.getLogger(__name__)


def _build_orchestrator(max_concurrent: int = 4, db_path: str | None = None) -> Orchestrator:
    """Build a fully wired orchestrator instance."""
    state_store = StateStore(db_path=db_path)
    orchestrator = Orchestrator(
        planner=Planner(),
        auctioneer=Auctioneer(),
        quality_gate=QualityGate(state_store=state_store),
        conflict_resolver=ConflictResolver(),
        contract_manager=ContractManager(),
        state_store=state_store,
        max_concurrent=max_concurrent,
    )
    # Register all preset agents
    from contractnet.core.agent import BaseAgent, CapabilityProfile
    from contractnet.core.types import Artifact, Contract

    # Simple stub agent that returns a text artifact
    class StubAgent(BaseAgent):
        def execute(self, contract: Contract, context: dict | None = None) -> Artifact:
            return Artifact(
                task_id=contract.task_id,
                content=f"Generated output for: {contract.description}",
                artifact_type="text",
            )

    for profile in ALL_PROFILES.values():
        orchestrator.register_agent(StubAgent(profile))

    return orchestrator


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool) -> None:
    """ContractNet — contract-driven multi-agent collaboration framework."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@cli.command()
@click.argument("goal")
@click.option("--context", "-c", help="Context directory path")
@click.option("--max-concurrent", default=4, help="Max concurrent agents")
@click.option("--db", default=None, help="SQLite path for state persistence")
def run(goal: str, context: str | None, max_concurrent: int, db: str | None) -> None:
    """Submit a goal for multi-agent execution."""
    click.echo(f"\n{'='*60}")
    click.echo(f"Goal: {goal}")
    click.echo(f"{'='*60}\n")

    orchestrator = _build_orchestrator(max_concurrent=max_concurrent, db_path=db)
    ctx = {}
    if context:
        import os
        ctx = {"workspace": os.path.abspath(context)}

    result = orchestrator.run(goal, ctx)

    click.echo(f"\n{'='*60}")
    click.echo("Execution Complete")
    click.echo(f"{'='*60}")
    click.echo(f"Success: {'✓' if result.success else '✗'}")
    click.echo(f"Duration: {result.duration_s}s")
    click.echo(f"Artifacts: {len(result.artifacts)}")
    click.echo(f"Tokens: {result.total_tokens}")
    click.echo(f"\nMetrics: {json.dumps(result.metrics, indent=2)}")

    for art in result.artifacts:
        click.echo(f"\n--- Artifact: {art.artifact_id} ---")
        click.echo(f"Type: {art.artifact_type}")
        click.echo(f"Quality: {art.quality_score}")
        click.echo(f"Content preview: {art.content[:200]}")


@cli.command()
@click.option("--task-id", default=None, help="Filter by task ID")
def status(task_id: str | None) -> None:
    """View current system status."""
    orchestrator = _build_orchestrator()
    status = orchestrator.get_status()
    click.echo(f"Active contracts: {status.active_contracts}")
    click.echo(f"Running agents: {status.running_agents}")


@cli.command()
@click.option("--task-id", default=None, help="Filter by task ID")
@click.option("--format", "-f", type=click.Choice(["dot", "text"]), default="text")
def dag(task_id: str | None, format: str) -> None:
    """View task DAG."""
    state_store = StateStore()
    current_dag = state_store.get_dag()
    if not current_dag:
        click.echo("No DAG found. Run a goal first.")
        return
    if format == "dot":
        click.echo(render_dag_graph(current_dag))
    else:
        for task in current_dag.tasks.values():
            click.echo(f"[{task.status.value:10}] {task.task_id}: {task.description[:60]}")


@cli.command()
@click.argument("agent_id")
def agent(agent_id: str) -> None:
    """View agent details."""
    profile = ALL_PROFILES.get(agent_id)
    if not profile:
        click.echo(f"Agent '{agent_id}' not found. Available: {list(ALL_PROFILES.keys())}")
        return
    click.echo(f"Agent: {profile.name} ({profile.agent_id})")
    click.echo(f"Task types: {profile.task_types}")
    click.echo(f"Tools: {profile.tools}")
    click.echo(f"Model: {profile.model}")
    click.echo(f"Skills: {profile.self_assessed_skills}")


@cli.command(name="agents")
def list_agents() -> None:
    """List all registered agent types."""
    for key, profile in ALL_PROFILES.items():
        click.echo(f"  {key:10} | {profile.name:15} | types={','.join(profile.task_types):20} | model={profile.model}")


@cli.command()
@click.option("--task-id", default=None)
def conflicts(task_id: str | None) -> None:
    """View conflict log."""
    orchestrator = _build_orchestrator()
    history = orchestrator.conflict_resolver.get_conflict_history()
    if not history:
        click.echo("No conflicts detected.")
        return
    for c in history:
        click.echo(f"[{c.conflict_type.value}] tasks={c.task_ids}: {c.description}")


@cli.command()
@click.argument("goal_id")
def replay(goal_id: str) -> None:
    """Replay a completed goal execution."""
    click.echo(f"Replay not yet implemented for goal: {goal_id}")


@cli.command()
@click.argument("goal_id")
def eval(goal_id: str) -> None:
    """Export evaluation report."""
    click.echo(f"Evaluation report for {goal_id}: Not yet implemented")


@cli.command()
@click.option("--port", default=8501, help="Dashboard port")
def dashboard(port: int) -> None:
    """Launch web dashboard."""
    from contractnet.observability.dashboard import run_streamlit_dashboard
    run_streamlit_dashboard(port)


def main() -> None:
    """Entry point for the contractnet CLI."""
    cli()


if __name__ == "__main__":
    main()
