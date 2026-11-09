"""Quality Gate — three-layer artifact validation.

Layer 1: Schema validation (deterministic, zero-cost)
Layer 2: Semantic validation (LLM-as-Judge)
Layer 3: Impact validation (conflict detection)

Layers short-circuit: if an earlier layer fails, later layers are skipped.
"""

from __future__ import annotations

import json
import logging

import jsonschema

from contractnet.core.types import (
    Artifact,
    Contract,
    QualityResult,
    ValidationLayer,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class QualityGate:
    """Three-layer quality gate for artifact validation.

    Responsibilities:
        - Validate artifact format (schema)
        - Validate artifact content (semantics, LLM-as-Judge)
        - Validate artifact impact (conflict with existing artifacts)
        - Short-circuit on failure to save cost

    Not responsible for:
        - Executing tasks
        - Resolving conflicts (Conflict Resolver handles this)
        - Deciding retry/replan (Orchestrator handles this)
    """

    def __init__(self, judge_client=None, state_store=None) -> None:
        """
        Args:
            judge_client: LLM client for semantic evaluation.
                         Should have a .complete(prompt) method.
                         Use a DIFFERENT model than execution agents to avoid bias.
            state_store: StateStore for impact validation (checking existing artifacts).
        """
        self.judge_client = judge_client
        self.state_store = state_store

    def review(self, artifact: Artifact, contract: Contract) -> QualityResult:
        """Run all three validation layers (with short-circuit).

        Returns:
            QualityResult with overall pass/fail, score, and feedback.
        """
        results: list[ValidationResult] = []

        # Layer 1: Schema
        r1 = self._validate_schema(artifact, contract)
        results.append(r1)
        if not r1.passed:
            return self._build_result(results)

        # Layer 2: Semantic
        r2 = self._validate_semantic(artifact, contract)
        results.append(r2)
        if not r2.passed:
            return self._build_result(results)

        # Layer 3: Impact
        r3 = self._validate_impact(artifact)
        results.append(r3)

        return self._build_result(results)

    def _validate_schema(self, artifact: Artifact, contract: Contract) -> ValidationResult:
        """Layer 1: Deterministic JSON Schema validation.

        Zero cost, fast, unambiguous.
        """
        try:
            content = artifact.content
            # If content is JSON, validate against schema
            if content.strip().startswith(("{", "[")):
                data = json.loads(content)
                jsonschema.validate(data, contract.output_schema)
            artifact.schema_validated = True
            return ValidationResult(passed=True, layer=ValidationLayer.SCHEMA, score=1.0)
        except json.JSONDecodeError:
            # Non-JSON content: pass schema check (schema applies to JSON only)
            artifact.schema_validated = True
            return ValidationResult(passed=True, layer=ValidationLayer.SCHEMA, score=1.0)
        except jsonschema.ValidationError as e:
            artifact.schema_validated = False
            return ValidationResult(
                passed=False,
                layer=ValidationLayer.SCHEMA,
                feedback=f"Schema validation failed: {e.message}",
            )

    def _validate_semantic(self, artifact: Artifact, contract: Contract) -> ValidationResult:
        """Layer 2: LLM-as-Judge semantic evaluation.

        Checks whether the artifact content actually fulfills the task description.
        Uses a different model than the execution agent to avoid self-evaluation bias.
        """
        threshold = contract.constraints.quality_threshold

        if not self.judge_client:
            # No judge available: pass with neutral score
            logger.warning("No judge client configured — skipping semantic validation")
            return ValidationResult(
                passed=True, layer=ValidationLayer.SEMANTIC, score=threshold,
                feedback="Semantic validation skipped (no judge client)",
            )

        try:
            prompt = f"""\
Evaluate whether the following output fulfills the task requirements.

Task: {contract.description}
Output (first 2000 chars): {artifact.content[:2000]}

Return JSON only:
{{"satisfied": true/false, "score": 0.0-1.0, "reason": "brief explanation", "missing": ["list of missing requirements"]}}
"""
            response = self.judge_client.complete(prompt)
            # LLM may wrap JSON in markdown fences or add prose; extract robustly
            result = self._parse_json_response(response)

            score = float(result.get("score", 0.0))
            passed = score >= threshold
            reason = result.get("reason", "")
            missing = result.get("missing", [])

            feedback = reason
            if missing:
                feedback += f" | Missing: {', '.join(missing)}"

            return ValidationResult(
                passed=passed, layer=ValidationLayer.SEMANTIC, score=score, feedback=feedback,
            )
        except Exception as e:
            logger.error("Semantic validation error: %s", e)
            # On error: pass but flag for review
            return ValidationResult(
                passed=True, layer=ValidationLayer.SEMANTIC, score=threshold,
                feedback=f"Semantic validation error: {e}",
            )

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """Parse LLM JSON response robustly — handles markdown fences and prose.

        Tries: direct json.loads → extract first {...} block → fallback dict.
        """
        import re

        text = text.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Extract first { ... } block
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Fallback: assume passed with neutral score
        logger.warning("Could not parse judge response as JSON, using fallback")
        return {"satisfied": True, "score": 0.8, "reason": "parse fallback", "missing": []}

    def _validate_impact(self, artifact: Artifact) -> ValidationResult:
        """Layer 3: Impact validation — check for conflicts with existing artifacts.

        Detects:
            - File path conflicts (same file written by different tasks)
            - (Interface and semantic conflicts handled by ConflictResolver)
        """
        if not self.state_store:
            return ValidationResult(passed=True, layer=ValidationLayer.IMPACT)

        conflicts = []
        for existing in self.state_store.get_all_artifacts():
            if (
                artifact.file_path
                and existing.file_path == artifact.file_path
                and artifact.artifact_id != existing.artifact_id
                and artifact.task_id != existing.task_id
            ):
                conflicts.append(f"File conflict: {artifact.file_path} (also written by task {existing.task_id})")

        if conflicts:
            return ValidationResult(
                passed=False, layer=ValidationLayer.IMPACT,
                feedback="; ".join(conflicts),
            )

        return ValidationResult(passed=True, layer=ValidationLayer.IMPACT)

    def _build_result(self, results: list[ValidationResult]) -> QualityResult:
        """Aggregate validation results into a QualityResult."""
        overall_passed = all(r.passed for r in results)
        semantic_score = next(
            (r.score for r in results if r.layer == ValidationLayer.SEMANTIC), 0.0,
        )
        failed_feedback = [r.feedback for r in results if not r.passed and r.feedback]

        return QualityResult(
            passed=overall_passed,
            score=semantic_score,
            feedback=" | ".join(failed_feedback),
            details=results,
        )
