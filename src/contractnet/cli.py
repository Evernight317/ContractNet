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
from contractnet.memory.state_store import StateStore as _StateStore

logger = logging.getLogger(__name__)


def _build_orchestrator(max_concurrent: int = 4, db_path: str | None = None) -> Orchestrator:
    """Build a fully wired orchestrator instance.

    Attempts to create an LLM client from environment configuration.
    If LLM is available, registers ReAct agents; otherwise falls back
    to stub agents that return placeholder output.
    """
    state_store = StateStore(db_path=db_path)

    # Try to initialize LLM client from env (.env file or env vars)
    llm_client = None
    try:
        from contractnet.llm.client import LLMClient
        llm_client = LLMClient()
        logger.info("LLM client initialized: model=%s", llm_client.config.model)
    except Exception as e:
        logger.warning("LLM client init failed (%s) — falling back to stub agents", e)

    orchestrator = Orchestrator(
        planner=Planner(llm_client=llm_client),
        auctioneer=Auctioneer(),
        quality_gate=QualityGate(judge_client=llm_client, state_store=state_store),
        conflict_resolver=ConflictResolver(),
        contract_manager=ContractManager(),
        state_store=state_store,
        max_concurrent=max_concurrent,
    )

    if llm_client:
        from contractnet.core.react_agent import ReActAgent
        from contractnet.tools.sandbox import ToolSandbox

        sandbox = ToolSandbox()
        for profile in ALL_PROFILES.values():
            orchestrator.register_agent(
                ReActAgent(profile, llm_client=llm_client, sandbox=sandbox)
            )
    else:
        from contractnet.core.agent import BaseAgent
        from contractnet.core.types import Artifact, Contract

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
    """Replay a completed goal execution from persisted state."""
    state_store = _StateStore()
    dag = state_store.get_dag()
    if not dag:
        click.echo("No DAG found. Run a goal first.")
        return

    click.echo(f"\n{'='*60}")
    click.echo(f"Replay: {dag.goal_description}")
    click.echo(f"Goal ID: {dag.goal_id}")
    click.echo(f"{'='*60}\n")

    tasks = sorted(dag.tasks.values(), key=lambda t: t.created_at)
    for i, task in enumerate(tasks):
        indent = "  " * task.depth
        status_icon = {"done": "✓", "failed": "✗", "impossible": "⊘", "replanned": "↻"}.get(
            task.status.value, "·"
        )
        click.echo(f"  [{status_icon}] {i+1}. {indent}{task.description[:70]}")
        click.echo(f"       type={task.task_type}  status={task.status.value}  retries={task.retry_count}")
        if task.depends_on:
            click.echo(f"       depends_on: {', '.join(task.depends_on[:3])}")

    artifacts = state_store.get_all_artifacts()
    if artifacts:
        click.echo(f"\n{'─'*60}")
        click.echo(f"Artifacts ({len(artifacts)}):")
        for art in artifacts:
            quality = f"quality={art.quality_score:.2f}" if art.quality_score else "no-score"
            click.echo(f"  {art.artifact_id} | type={art.artifact_type} | v{art.version} | {quality}")
            click.echo(f"    preview: {art.content[:120]}")

    click.echo(f"\n{'='*60}")
    click.echo(f"Total tasks: {len(tasks)}")
    click.echo(f"Done: {sum(1 for t in tasks if t.status.value == 'done')}")
    click.echo(f"{'='*60}")


@cli.command()
@click.argument("goal_id")
def eval(goal_id: str) -> None:
    """Export evaluation report for a completed goal."""
    state_store = _StateStore()
    dag = state_store.get_dag()
    if not dag:
        click.echo("No DAG found. Run a goal first.")
        return

    artifacts = state_store.get_all_artifacts()
    tasks = list(dag.tasks.values())
    total = len(tasks)
    done = sum(1 for t in tasks if t.status.value == "done")
    failed = sum(1 for t in tasks if t.status.value == "failed")
    retried = sum(1 for t in tasks if t.retry_count > 0)

    report = {
        "goal": dag.goal_description,
        "goal_id": dag.goal_id,
        "summary": {
            "total_tasks": total,
            "done_tasks": done,
            "failed_tasks": failed,
            "retried_tasks": retried,
            "completion_rate": round(done / total, 4) if total else 0,
            "artifacts_produced": len(artifacts),
        },
        "artifacts": [
            {
                "id": a.artifact_id,
                "type": a.artifact_type,
                "quality_score": a.quality_score,
                "version": a.version,
            }
            for a in artifacts
        ],
        "tasks": [
            {
                "id": t.task_id,
                "description": t.description[:100],
                "type": t.task_type,
                "status": t.status.value,
                "retries": t.retry_count,
                "depth": t.depth,
            }
            for t in sorted(tasks, key=lambda t: t.created_at)
        ],
    }

    import json as _json
    output = _json.dumps(report, indent=2, ensure_ascii=False)

    report_path = f"eval_report_{dag.goal_id}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(output)

    click.echo(f"Evaluation report saved to: {report_path}")
    click.echo(f"\nSummary:")
    click.echo(f"  Tasks: {done}/{total} done ({failed} failed, {retried} retried)")
    click.echo(f"  Artifacts: {len(artifacts)}")
    if artifacts:
        avg_q = sum(a.quality_score for a in artifacts if a.quality_score) / len(artifacts)
        click.echo(f"  Avg quality: {avg_q:.2f}")
    else:
        click.echo("  Avg quality: N/A")


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
