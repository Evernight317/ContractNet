"""Agent Memory — per-agent execution experience store.

Maintains:
    - Execution log (all past executions)
    - Capability profile (dynamically updated)
    - Failure patterns (to avoid repeating mistakes)
    - Success templates (to reference efficient solutions)
"""

from __future__ import annotations

import logging

from contractnet.core.agent import (
    AgentPerformance,
    CapabilityProfile,
    ExecutionRecord,
    FailurePattern,
    SuccessTemplate,
)

logger = logging.getLogger(__name__)

# Threshold: if same task_type fails >= this many times with similar feedback, extract pattern
_FAILURE_PATTERN_THRESHOLD = 2
# Threshold: quality score above this to consider as a success template
_SUCCESS_TEMPLATE_QUALITY = 0.85


class AgentMemory:
    """Per-agent memory for cross-task learning.

    Responsibilities:
        - Record execution results
        - Update capability profile with performance data
        - Detect failure patterns and build success templates
        - Provide reference context for future tasks

    Not responsible for:
        - Global state management (StateStore)
        - Cross-agent memory sharing (future extension)
    """

    def __init__(self, profile: CapabilityProfile) -> None:
        self.profile = profile
        self._execution_log: list[ExecutionRecord] = []
        self._failure_patterns: list[FailurePattern] = []
        self._success_templates: list[SuccessTemplate] = []

    def record_execution(self, record: ExecutionRecord) -> None:
        """Record an execution result and update all memory structures."""
        self._execution_log.append(record)
        self._update_performance(record)

        if record.success:
            self._maybe_add_template(record)
        else:
            self._maybe_add_failure_pattern(record)

    def get_reference(self, task_type: str, description: str) -> str | None:
        """Get reference context for a new task.

        Combines:
            - Relevant success templates (what worked before)
            - Relevant failure patterns (what to avoid)
        """
        parts = []

        # Find relevant success templates
        relevant_templates = [
            t for t in self._success_templates
            if t.task_type == task_type
        ]
        if relevant_templates:
            best = max(relevant_templates, key=lambda t: t.quality_score)
            parts.append(f"Reference: Similar task completed in {best.steps_taken} steps with quality {best.quality_score:.2f}")

        # Find relevant failure patterns
        relevant_failures = [
            f for f in self._failure_patterns
            if f.task_type == task_type
        ]
        if relevant_failures:
            for fp in relevant_failures[:2]:  # top 2 most relevant
                parts.append(f"Warning: Similar tasks have failed due to: {fp.common_feedback}")

        return " | ".join(parts) if parts else None

    def get_failure_patterns(self) -> list[FailurePattern]:
        return list(self._failure_patterns)

    def get_success_templates(self) -> list[SuccessTemplate]:
        return list(self._success_templates)

    def get_execution_log(self, task_type: str | None = None) -> list[ExecutionRecord]:
        if task_type:
            return [r for r in self._execution_log if r.task_type == task_type]
        return list(self._execution_log)

    # ──────────────────────────────────────────
    # Private methods
    # ──────────────────────────────────────────

    def _update_performance(self, record: ExecutionRecord) -> None:
        """Update capability profile performance metrics."""
        key = record.task_type
        perf = self.profile.historical_performance.get(key, AgentPerformance())
        n = perf.total_tasks
        perf.total_tasks = n + 1
        perf.success_rate = (n * perf.success_rate + int(record.success)) / (n + 1)
        perf.avg_cost = (n * perf.avg_cost + record.tokens_used) // (n + 1)
        perf.avg_steps = (n * perf.avg_steps + record.steps_taken) // (n + 1)
        if record.quality_score is not None:
            perf.avg_quality = (n * perf.avg_quality + record.quality_score) / (n + 1)
        self.profile.historical_performance[key] = perf

    def _maybe_add_template(self, record: ExecutionRecord) -> None:
        """Extract a success template if quality is high enough."""
        if record.quality_score and record.quality_score >= _SUCCESS_TEMPLATE_QUALITY:
            template = SuccessTemplate(
                task_type=record.task_type,
                description=record.description[:200],
                steps_taken=record.steps_taken,
                quality_score=record.quality_score,
            )
            # Avoid duplicates
            existing = [t for t in self._success_templates if t.description == template.description]
            if not existing:
                self._success_templates.append(template)
                logger.debug("Added success template for %s", record.task_type)

    def _maybe_add_failure_pattern(self, record: ExecutionRecord) -> None:
        """Extract a failure pattern if same task_type fails repeatedly."""
        similar_failures = [
            r for r in self._execution_log
            if r.task_type == record.task_type and not r.success
        ]

        if len(similar_failures) >= _FAILURE_PATTERN_THRESHOLD and record.feedback:
            pattern = FailurePattern(
                task_type=record.task_type,
                common_feedback=record.feedback[:200],
                occurrence_count=len(similar_failures),
            )
            # Check if similar pattern already exists
            existing = [
                p for p in self._failure_patterns
                if p.task_type == pattern.task_type and p.common_feedback == pattern.common_feedback
            ]
            if not existing:
                self._failure_patterns.append(pattern)
                logger.info("Added failure pattern for %s: %s", record.task_type, pattern.common_feedback[:50])
            else:
                existing[0].occurrence_count = pattern.occurrence_count
