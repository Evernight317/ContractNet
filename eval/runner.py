"""Evaluation runner — execute benchmarks and compare configurations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from contractnet.core.orchestrator import Orchestrator, FinalResult
from eval.metrics import EvalMetrics, compute_metrics


@dataclass
class BenchmarkTask:
    """A benchmark task definition."""
    name: str
    goal: str
    expected_artifacts: list[str] = field(default_factory=list)
    success_criteria: dict = field(default_factory=dict)
    difficulty: str = "medium"


@dataclass
class EvalConfig:
    """Configuration for an evaluation run."""
    name: str
    max_concurrent: int = 4
    models: dict | None = None  # agent_type → model override


@dataclass
class EvalResult:
    """Result of evaluating a single benchmark."""
    benchmark: str
    config: str
    success: bool
    metrics: dict = field(default_factory=dict)
    duration_s: float = 0.0
    cost_usd: float = 0.0


# ──────────────────────────────────────────────
# Predefined Benchmarks
# ──────────────────────────────────────────────

BENCHMARKS = {
    "bench_api_crud": BenchmarkTask(
        name="全栈 API 项目生成",
        goal="实现一个带 JWT 认证的 Todo API，包含测试和文档",
        expected_artifacts=["main.py", "auth.py", "test_main.py", "README.md"],
        success_criteria={
            "tests_pass": True,
            "api_endpoints_exist": ["/login", "/todos", "/todos/{id}"],
            "readme_exists": True,
        },
        difficulty="medium",
    ),
    "bench_data_analysis": BenchmarkTask(
        name="数据分析报告",
        goal="分析销售数据 CSV，找出下降原因并给出建议",
        expected_artifacts=["analysis.py", "report.md"],
        success_criteria={
            "report_contains_insights": True,
            "charts_generated": True,
        },
        difficulty="medium",
    ),
    "bench_bug_fix": BenchmarkTask(
        name="Bug 修复流水线",
        goal="修复 GitHub Issue: '登录后 redirect 丢失 query 参数'",
        expected_artifacts=["fix.diff", "test_fix.py"],
        success_criteria={
            "fix_addresses_issue": True,
            "regression_test_added": True,
            "tests_pass": True,
        },
        difficulty="hard",
    ),
}


class EvalRunner:
    """Run benchmarks and compare configurations.

    Usage:
        runner = EvalRunner()
        result = runner.run_benchmark(
            BENCHMARKS["bench_api_crud"],
            EvalConfig(name="default"),
        )
    """

    def run_benchmark(self, benchmark: BenchmarkTask, config: EvalConfig) -> EvalResult:
        """Execute a single benchmark task and collect results."""
        start = time.time()

        orchestrator = self._build_orchestrator(config)
        result = orchestrator.run(benchmark.goal)

        success = self._check_criteria(result, benchmark.success_criteria)
        duration = time.time() - start

        return EvalResult(
            benchmark=benchmark.name,
            config=config.name,
            success=success,
            metrics=result.metrics,
            duration_s=round(duration, 2),
        )

    def run_comparison(
        self,
        benchmark: BenchmarkTask,
        configs: list[EvalConfig],
    ) -> dict:
        """Run the same benchmark with multiple configurations and compare."""
        results = []
        for cfg in configs:
            result = self.run_benchmark(benchmark, cfg)
            results.append(result)
            print(f"  Config {cfg.name}: success={result.success}, duration={result.duration_s}s")

        report = {
            "benchmark": benchmark.name,
            "configs": [
                {
                    "name": r.config,
                    "success": r.success,
                    "duration_s": r.duration_s,
                    "metrics": r.metrics,
                }
                for r in results
            ],
        }
        return report

    def run_all_benchmarks(self, config: EvalConfig) -> list[EvalResult]:
        """Run all predefined benchmarks."""
        results = []
        for key, benchmark in BENCHMARKS.items():
            print(f"\nRunning benchmark: {benchmark.name} ({benchmark.difficulty})")
            result = self.run_benchmark(benchmark, config)
            results.append(result)
        return results

    def _build_orchestrator(self, config: EvalConfig) -> Orchestrator:
        """Build an orchestrator from eval config."""
        from contractnet.core.planner import Planner
        from contractnet.core.auctioneer import Auctioneer
        from contractnet.core.quality_gate import QualityGate
        from contractnet.core.conflict_resolver import ConflictResolver
        from contractnet.core.contract import ContractManager
        from contractnet.memory.state_store import StateStore
        from contractnet.core.agent import BaseAgent
        from contractnet.core.types import Artifact, Contract
        from contractnet.tools.builtins import ALL_PROFILES

        state_store = StateStore()
        orchestrator = Orchestrator(
            planner=Planner(),
            auctioneer=Auctioneer(),
            quality_gate=QualityGate(state_store=state_store),
            conflict_resolver=ConflictResolver(),
            contract_manager=ContractManager(),
            state_store=state_store,
            max_concurrent=config.max_concurrent,
        )

        class StubAgent(BaseAgent):
            def execute(self, contract: Contract, context=None) -> Artifact:
                return Artifact(
                    task_id=contract.task_id,
                    content=f"Output for: {contract.description}",
                    artifact_type="text",
                )

        for profile in ALL_PROFILES.values():
            orchestrator.register_agent(StubAgent(profile))

        return orchestrator

    def _check_criteria(self, result: FinalResult, criteria: dict) -> bool:
        """Check if execution result meets success criteria (simplified)."""
        if not result.success:
            return False
        # Full criteria checking would inspect artifacts
        return True
