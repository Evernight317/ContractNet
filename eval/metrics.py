"""Metrics definitions and calculation for ContractNet evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EvalMetrics:
    """Aggregated evaluation metrics for a single run."""
    # Task-level
    task_completion_rate: float = 0.0       # completed / total
    task_avg_steps: float = 0.0             # average steps per task
    task_avg_duration_ms: float = 0.0       # average execution time

    # Auction-level
    avg_bids_per_contract: float = 0.0      # bidding competition level
    auction_no_bid_rate: float = 0.0        # contracts with no bids
    avg_auction_rounds: float = 0.0         # average rounds to award

    # Quality-level
    quality_first_pass_rate: float = 0.0    # passed on first try
    quality_avg_score: float = 0.0          # average quality score
    quality_retry_rate: float = 0.0         # tasks needing retry

    # Conflict-level
    conflict_count: int = 0                 # total conflicts
    conflict_detection_rate: float = 0.0    # detected / actual
    conflict_resolution_success: float = 0.0 # resolved / detected

    # Cost-level
    total_tokens: int = 0                   # total LLM token consumption
    tokens_per_task: float = 0.0            # tokens / completed tasks
    total_llm_calls: int = 0               # total LLM API calls
    estimated_cost_usd: float = 0.0         # estimated API cost

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def compute_metrics(
    dag,
    artifacts,
    auction_history: dict,
    conflict_history: list,
    quality_results: list,
    total_tokens: int = 0,
) -> EvalMetrics:
    """Compute all metrics from execution data."""
    tasks = list(dag.tasks.values())
    total_tasks = len(tasks)
    done = sum(1 for t in tasks if t.status.value == "done")
    failed = sum(1 for t in tasks if t.status.value == "failed")
    retried = sum(1 for t in tasks if t.retry_count > 0)

    # Quality
    first_pass = sum(1 for q in quality_results if q.passed)
    scores = [q.score for q in quality_results if q.score > 0]

    # Auction
    contracts_with_bids = [k for k, v in auction_history.items() if v]
    no_bid = sum(1 for k, v in auction_history.items() if not v)

    return EvalMetrics(
        task_completion_rate=done / total_tasks if total_tasks > 0 else 0.0,
        task_avg_duration_ms=0.0,  # filled from trace if available
        avg_bids_per_contract=(
            sum(len(v) for v in auction_history.values()) / len(auction_history)
            if auction_history else 0.0
        ),
        auction_no_bid_rate=no_bid / len(auction_history) if auction_history else 0.0,
        quality_first_pass_rate=first_pass / len(quality_results) if quality_results else 0.0,
        quality_avg_score=sum(scores) / len(scores) if scores else 0.0,
        quality_retry_rate=retried / total_tasks if total_tasks > 0 else 0.0,
        conflict_count=len(conflict_history),
        total_tokens=total_tokens,
        tokens_per_task=total_tokens / done if done > 0 else 0.0,
    )
