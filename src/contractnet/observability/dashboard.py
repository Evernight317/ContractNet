"""Streamlit Dashboard — real-time visualization for ContractNet.

Pages:
    1. Real-time DAG: task dependency graph with status colors
    2. Trace Explorer: hierarchical span viewer
    3. Metrics Dashboard: runtime metrics with trends
    4. Conflict Log: all detected conflicts and resolutions
    5. Replay: step-by-step task execution replay
"""

from __future__ import annotations

import json


def render_dag_graph(dag) -> str:
    """Generate a Graphviz DOT representation of the task DAG.

    Args:
        dag: TaskDAG instance

    Returns:
        DOT format string for rendering
    """
    lines = ["digraph task_dag {"]
    lines.append("  rankdir=LR;")
    lines.append("  node [fontname=Arial, fontsize=10];")

    color_map = {
        "done": "#4CAF50",
        "running": "#FFC107",
        "failed": "#F44336",
        "pending": "#9E9E9E",
        "replanned": "#2196F3",
        "impossible": "#795548",
    }

    for task in dag.tasks.values():
        color = color_map.get(task.status.value, "#9E9E9E")
        label = task.description[:30].replace('"', "'")
        lines.append(
            f'  "{task.task_id}" [label="{label}", fillcolor="{color}", style=filled];'
        )
        for dep in task.depends_on:
            lines.append(f'  "{dep}" -> "{task.task_id}";')

    lines.append("}")
    return "\n".join(lines)


def render_trace_tree(trace_json: str) -> str:
    """Render a trace as an indented tree string."""
    trace = json.loads(trace_json)
    lines = [f"Trace: {trace['trace_id']}"]
    lines.append(f"Goal: {trace['goal']}")
    lines.append("")

    spans = trace.get("spans", {})

    def render_span(span_id: str, depth: int) -> list[str]:
        span = spans.get(span_id)
        if not span:
            return []
        indent = "  " * depth
        status_icon = "✓" if span["status"] == "ok" else "✗"
        lines = [f"{indent}{status_icon} {span['name']} ({span['duration_ms']:.0f}ms)"]
        for attr, val in span.get("attributes", {}).items():
            lines.append(f"{indent}  • {attr}: {val}")
        for event in span.get("events", []):
            lines.append(f"{indent}  ⚡ {event['event']}")
        # Find children
        children = [sid for sid, s in spans.items() if s.get("parent_id") == span_id]
        for child in children:
            lines.extend(render_span(child, depth + 1))
        return lines

    # Find root spans (no parent)
    roots = [sid for sid, s in spans.items() if not s.get("parent_id")]
    for root in roots:
        lines.extend(render_span(root, 1))

    return "\n".join(lines)


def render_metrics_table(metrics: dict) -> str:
    """Render metrics summary as a formatted table string."""
    lines = ["| Metric | Count | Avg | Min | Max |", "|--------|-------|-----|-----|-----|"]
    for name, stats in metrics.items():
        lines.append(
            f"| {name} | {stats.get('count', 0)} | "
            f"{stats.get('avg', 0):.2f} | "
            f"{stats.get('min', 0):.2f} | "
            f"{stats.get('max', 0):.2f} |"
        )
    return "\n".join(lines)


def render_conflict_log(conflicts: list[dict]) -> str:
    """Render conflict history as a formatted log."""
    if not conflicts:
        return "No conflicts detected."
    lines = ["Conflict Log:", ""]
    for c in conflicts:
        lines.append(
            f"  [{c.get('conflict_type', 'unknown')}] "
            f"Tasks: {c.get('task_ids', [])} — "
            f"{c.get('description', '')}"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────
# Streamlit app (optional — requires streamlit installed)
# ──────────────────────────────────────────────

def run_streamlit_dashboard(port: int = 8501) -> None:
    """Launch the Streamlit dashboard.

    This function is only callable when streamlit is installed.
    Run via: contractnet dashboard --port 8501
    """
    try:
        import streamlit as st
    except ImportError:
        print("Streamlit not installed. Install with: pip install contractnet[dashboard]")
        return

    st.set_page_config(page_title="ContractNet Dashboard", layout="wide")
    st.title("ContractNet — Multi-Agent Collaboration Dashboard")

    st.sidebar.title("Navigation")
    page = st.sidebar.radio("Pages", ["Real-time DAG", "Trace Explorer", "Metrics", "Conflict Log", "Replay"])

    if page == "Real-time DAG":
        st.header("Task Dependency Graph")
        st.caption("Node colors: green=done, yellow=running, red=failed, gray=pending")
        st.info("Submit a goal via CLI to see the DAG here.")

    elif page == "Trace Explorer":
        st.header("Execution Trace")
        st.info("Traces will appear here after execution.")

    elif page == "Metrics":
        st.header("Runtime Metrics")
        st.info("Metrics will appear here after execution.")

    elif page == "Conflict Log":
        st.header("Conflict History")
        st.info("Detected conflicts and resolutions will appear here.")

    elif page == "Replay":
        st.header("Execution Replay")
        st.info("Select a completed goal to replay step-by-step.")
