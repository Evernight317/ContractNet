"""Predefined benchmark tasks for ContractNet evaluation.

Each benchmark specifies a goal, expected artifacts, and success criteria.
Difficulty levels: easy, medium, hard.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BenchmarkSpec:
    """A benchmark specification."""
    key: str
    name: str
    goal: str
    expected_artifacts: list[str] = field(default_factory=list)
    success_criteria: dict = field(default_factory=dict)
    difficulty: str = "medium"
    description: str = ""


BENCHMARKS: dict[str, BenchmarkSpec] = {
    "fibonacci": BenchmarkSpec(
        key="fibonacci",
        name="Fibonacci Function",
        goal="写一个 Python 函数计算斐波那契数列前 N 项，包含测试和文档",
        expected_artifacts=["fibonacci.py", "test_fibonacci.py"],
        success_criteria={
            "function_exists": True,
            "tests_pass": True,
            "docstring_present": True,
        },
        difficulty="easy",
        description="Basic code generation with tests and docs",
    ),
    "todo_api": BenchmarkSpec(
        key="todo_api",
        name="Todo API with JWT",
        goal="实现一个带 JWT 认证的 Todo API，包含测试和文档",
        expected_artifacts=["main.py", "auth.py", "test_main.py", "README.md"],
        success_criteria={
            "tests_pass": True,
            "api_endpoints_exist": ["/login", "/todos", "/todos/{id}"],
            "readme_exists": True,
        },
        difficulty="medium",
        description="Full-stack API project with auth, CRUD, tests, and docs",
    ),
    "data_analysis": BenchmarkSpec(
        key="data_analysis",
        name="Sales Data Analysis",
        goal="分析销售数据 CSV，找出下降原因并给出建议",
        expected_artifacts=["analysis.py", "report.md"],
        success_criteria={
            "report_contains_insights": True,
            "charts_generated": True,
        },
        difficulty="medium",
        description="Data analysis pipeline with report generation",
    ),
    "bug_fix": BenchmarkSpec(
        key="bug_fix",
        name="Bug Fix Pipeline",
        goal="修复 GitHub Issue: '登录后 redirect 丢失 query 参数'",
        expected_artifacts=["fix.diff", "test_fix.py"],
        success_criteria={
            "fix_addresses_issue": True,
            "regression_test_added": True,
            "tests_pass": True,
        },
        difficulty="hard",
        description="Bug diagnosis, fix, and regression test in one pipeline",
    ),
    "refactor": BenchmarkSpec(
        key="refactor",
        name="Code Refactor",
        goal="重构一个 200 行的 monolithic Python 脚本，拆分为模块化结构并保持测试通过",
        expected_artifacts=["refactored/", "test_refactored.py"],
        success_criteria={
            "modules_created": True,
            "tests_pass": True,
            "no_function_lost": True,
        },
        difficulty="hard",
        description="Large-scale refactoring with test preservation",
    ),
}


def list_benchmarks() -> list[dict]:
    """Return a summary list of all benchmarks."""
    return [
        {
            "key": b.key,
            "name": b.name,
            "difficulty": b.difficulty,
            "description": b.description,
        }
        for b in BENCHMARKS.values()
    ]


def get_benchmark(key: str) -> BenchmarkSpec | None:
    """Get a benchmark by key."""
    return BENCHMARKS.get(key)
