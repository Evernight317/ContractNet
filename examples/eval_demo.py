from __future__ import annotations
"""Benchmark evaluation demo — run all benchmarks and print comparison."""

import json
import sys
from pathlib import Path

# Add parent to path for eval imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.runner import EvalRunner, EvalConfig, BENCHMARKS


def main():
    runner = EvalRunner()
    config = EvalConfig(name="default", max_concurrent=4)

    print(f"\n{'='*60}")
    print("ContractNet Benchmark Evaluation")
    print(f"{'='*60}\n")

    results = runner.run_all_benchmarks(config)

    print(f"\n{'='*60}")
    print("Summary")
    print(f"{'='*60}")
    for r in results:
        status = "✓" if r.success else "✗"
        print(f"  {status} {r.benchmark:30} | {r.duration_s:6.1f}s | config={r.config}")

    # Print detailed metrics
    print(f"\n{'='*60}")
    print("Detailed Metrics")
    print(f"{'='*60}")
    for r in results:
        print(f"\n{r.benchmark}:")
        for key, value in r.metrics.items():
            if isinstance(value, float):
                print(f"  {key:30}: {value:.2%}" if "rate" in key else f"  {key:30}: {value:.2f}")
            else:
                print(f"  {key:30}: {value}")


if __name__ == "__main__":
    main()
