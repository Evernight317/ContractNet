"""Tracer — OpenTelemetry-compatible execution tracing.

Provides hierarchical span tracking for the full execution lifecycle:
    Goal → Plan → Auction → Execute → QualityGate → ConflictResolve → Merge
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Span:
    """A single trace span."""
    span_id: str
    name: str
    parent_id: str | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"  # ok | error

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000 if self.end_time else 0.0


@dataclass
class Trace:
    """A complete trace (collection of spans)."""
    trace_id: str
    goal: str = ""
    spans: dict[str, Span] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0

    def to_json(self) -> str:
        return json.dumps({
            "trace_id": self.trace_id,
            "goal": self.goal,
            "spans": {
                sid: {
                    "name": s.name,
                    "parent_id": s.parent_id,
                    "duration_ms": round(s.duration_ms, 1),
                    "attributes": s.attributes,
                    "events": s.events,
                    "status": s.status,
                }
                for sid, s in self.spans.items()
            },
        }, indent=2, default=str)


class Tracer:
    """Execution tracer for ContractNet.

    Responsibilities:
        - Create and manage hierarchical spans
        - Record events within spans
        - Store complete traces for replay and analysis
        - Export trace data (JSON format)

    Not responsible for:
        - Metrics collection (MetricsCollector handles this)
        - Visualization (Dashboard handles this)
    """

    def __init__(self) -> None:
        self._traces: dict[str, Trace] = {}
        self._current_trace: Trace | None = None
        self._span_counter = 0

    def start_trace(self, goal: str) -> str:
        """Start a new trace for a goal execution."""
        trace_id = f"trace_{int(time.time_ns())}"
        trace = Trace(trace_id=trace_id, goal=goal, start_time=time.time())
        self._traces[trace_id] = trace
        self._current_trace = trace
        return trace_id

    def start_span(self, name: str, parent_id: str | None = None) -> str:
        """Start a new span within the current trace."""
        if not self._current_trace:
            logger.warning("No active trace — span will be orphaned")
            return ""

        self._span_counter += 1
        span_id = f"span_{self._span_counter}"
        span = Span(
            span_id=span_id,
            name=name,
            parent_id=parent_id,
            start_time=time.time(),
        )
        self._current_trace.spans[span_id] = span
        return span_id

    def end_span(self, span_id: str, attributes: dict | None = None) -> None:
        """End a span and optionally set attributes."""
        if not self._current_trace or span_id not in self._current_trace.spans:
            return
        span = self._current_trace.spans[span_id]
        span.end_time = time.time()
        if attributes:
            span.attributes.update(attributes)

    def add_event(self, span_id: str, event: str, data: dict | None = None) -> None:
        """Add an event to a span."""
        if not self._current_trace or span_id not in self._current_trace.spans:
            return
        self._current_trace.spans[span_id].events.append({
            "event": event,
            "data": data or {},
            "timestamp": time.time(),
        })

    def set_span_error(self, span_id: str, error: str) -> None:
        """Mark a span as errored."""
        if self._current_trace and span_id in self._current_trace.spans:
            self._current_trace.spans[span_id].status = "error"
            self._current_trace.spans[span_id].attributes["error"] = error

    def end_trace(self) -> None:
        """End the current trace."""
        if self._current_trace:
            self._current_trace.end_time = time.time()
        self._current_trace = None

    def get_trace(self, trace_id: str) -> Trace | None:
        return self._traces.get(trace_id)

    def get_current_trace(self) -> Trace | None:
        return self._current_trace

    def export_trace(self, trace_id: str) -> str:
        """Export a trace as JSON string."""
        trace = self._traces.get(trace_id)
        return trace.to_json() if trace else "{}"


class MetricsCollector:
    """Collects and aggregates runtime metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[float]] = {}
        self._tags: dict[str, dict] = {}

    def record(self, metric: str, value: float, tags: dict | None = None) -> None:
        """Record a metric value."""
        if metric not in self._metrics:
            self._metrics[metric] = []
        self._metrics[metric].append(value)
        if tags:
            self._tags[metric] = tags

    def get_summary(self) -> dict[str, dict]:
        """Get summary statistics for all metrics."""
        summary = {}
        for metric, values in self._metrics.items():
            if not values:
                continue
            summary[metric] = {
                "count": len(values),
                "sum": sum(values),
                "avg": sum(values) / len(values),
                "min": min(values),
                "max": max(values),
            }
        return summary

    def compare(self, other: dict) -> dict:
        """Compare current metrics with another summary."""
        current = self.get_summary()
        diff = {}
        for key in set(current) | set(other):
            curr_avg = current.get(key, {}).get("avg", 0)
            other_avg = other.get(key, {}).get("avg", 0)
            if other_avg != 0:
                diff[key] = {"change_pct": (curr_avg - other_avg) / other_avg * 100}
        return diff
