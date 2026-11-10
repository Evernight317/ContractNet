"""ReAct Agent — LLM-driven Think-Act-Observe execution loop.

Implements the ReAct (Reasoning + Acting) pattern:
    1. Think: LLM reasons about the task and decides next action
    2. Act: LLM emits tool calls, sandbox executes them
    3. Observe: Tool results fed back to LLM
    4. Repeat until done or deadline reached
"""

from __future__ import annotations

import json
import logging

from contractnet.core.agent import BaseAgent, CapabilityProfile, ExecutionRecord
from contractnet.core.types import Artifact, Contract
from contractnet.llm.client import LLMClient
from contractnet.tools.builtins import TOOL_DEFINITIONS
from contractnet.tools.sandbox import ToolSandbox, ToolPermission

logger = logging.getLogger(__name__)


class ReActAgent(BaseAgent):
    """LLM-driven agent that executes contracts via ReAct loop.

    Unlike StubAgent, this agent uses an LLM to reason about tasks
    and call tools (file_read, code_run, etc.) to produce real artifacts.
    """

    def __init__(
        self,
        profile: CapabilityProfile,
        llm_client: LLMClient,
        sandbox: ToolSandbox | None = None,
        workspace: str | None = None,
    ) -> None:
        super().__init__(profile)
        self.llm_client = llm_client
        self.sandbox = sandbox or ToolSandbox(workspace=workspace)

    def execute(self, contract: Contract, context: dict | None = None) -> Artifact:
        """Execute a contract via ReAct Think-Act-Observe loop.

        Args:
            contract: The awarded contract to execute
            context: Optional execution context (workspace, prior artifacts, etc.)

        Returns:
            Artifact with the final LLM output
        """
        tools = self._get_available_tools(contract)
        messages = self._build_initial_messages(contract, context)

        total_tokens = 0
        steps = 0
        max_steps = contract.constraints.max_steps
        deadline = max(contract.constraints.max_steps, contract.deadline_steps)
        last_content = ""

        while steps <= deadline:
            model_override = {}
            if self.profile.model:
                model_override["model"] = self.profile.model

            response = self.llm_client.chat(
                messages,
                tools=tools or None,
                **model_override,
            )
            total_tokens += response.total_tokens
            last_content = response.content

            # No tool calls → LLM is done reasoning
            if not response.tool_calls:
                logger.info(
                    "Agent %s finished in %d steps (tokens=%d)",
                    self.agent_id, steps, total_tokens,
                )
                break

            # Append assistant message with tool calls
            assistant_msg: dict = {"role": "assistant", "content": response.content or ""}
            assistant_msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in response.tool_calls
            ]
            messages.append(assistant_msg)

            # Execute each tool call and feed results back
            for tc in response.tool_calls:
                result = self._execute_tool_call(tc)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            steps += 1
            logger.debug(
                "Agent %s step %d: %d tool calls executed",
                self.agent_id, steps, len(response.tool_calls),
            )
        else:
            logger.warning(
                "Agent %s hit deadline (%d steps) — returning partial result",
                self.agent_id, deadline,
            )

        # Record execution for performance tracking
        self.record_execution(ExecutionRecord(
            task_id=contract.task_id,
            contract_id=contract.contract_id,
            task_type=self._infer_task_type(contract),
            description=contract.description,
            steps_taken=steps,
            tokens_used=total_tokens,
            success=True,
        ))

        return Artifact(
            task_id=contract.task_id,
            content=last_content,
            artifact_type=self._infer_artifact_type(contract),
        )

    # ──────────────────────────────────────────
    # Private methods
    # ──────────────────────────────────────────

    def _get_available_tools(self, contract: Contract) -> list[dict]:
        """Build tool definitions available to this agent.

        Filters by agent profile tools and contract constraints
        (forbidden tools are excluded).
        """
        forbidden = set(contract.constraints.forbidden_tools)
        allowed = [
            name for name in self.profile.tools
            if name not in forbidden and name in TOOL_DEFINITIONS
        ]
        return [TOOL_DEFINITIONS[name] for name in allowed]

    def _build_initial_messages(
        self, contract: Contract, context: dict | None,
    ) -> list[dict]:
        """Build the initial message list for the LLM conversation."""
        context = context or {}

        # Retrieve memory reference (success templates / failure patterns)
        task_type = self._infer_task_type(contract)
        memory_ref = self.memory.get_reference(task_type, contract.description)

        tool_names = ", ".join(self.profile.tools)
        system = (
            f"You are {self.profile.name}, a specialized agent in a multi-agent system.\n"
            f"Your capabilities: {', '.join(self.profile.task_types)}\n"
            f"Available tools: {tool_names}\n\n"
            f"Instructions:\n"
            f"- Analyze the task and use tools to gather information or produce output.\n"
            f"- When you have completed the task, provide your final result as a clear text response.\n"
            f"- Be concise and focused. Do not repeat steps unnecessarily.\n"
        )
        if memory_ref:
            system += f"\nPast experience:\n{memory_ref}\n"

        user_content = (
            f"Task: {contract.description}\n\n"
            f"Constraints:\n"
            f"  - Max tokens: {contract.constraints.max_tokens}\n"
            f"  - Max steps: {contract.constraints.max_steps}\n"
            f"  - Quality threshold: {contract.constraints.quality_threshold}\n"
        )

        if contract.input_artifacts:
            user_content += f"\nInput artifacts: {', '.join(contract.input_artifacts)}\n"

        if context:
            workspace = context.get("workspace")
            if workspace:
                user_content += f"\nWorkspace directory: {workspace}\n"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    def _execute_tool_call(self, tool_call: dict) -> str:
        """Execute a single tool call via the sandbox.

        Returns the tool output (or error message) as a string.
        """
        name = tool_call["name"]
        try:
            args = json.loads(tool_call["arguments"])
        except json.JSONDecodeError as e:
            return f"Error: invalid tool arguments JSON: {e}"

        perm = ToolPermission(tool_name=name)
        result = self.sandbox.execute(name, args, perm)

        if result.success:
            return result.output
        return f"Error: {result.error}"

    @staticmethod
    def _infer_task_type(contract: Contract) -> str:
        """Infer task type from contract for execution records."""
        desc = contract.description.lower()
        for ttype in ("code", "test", "doc", "analysis", "design", "review"):
            if ttype in desc:
                return ttype
        return "general"

    @staticmethod
    def _infer_artifact_type(contract: Contract) -> str:
        """Infer artifact type from contract description."""
        desc = contract.description.lower()
        if "test" in desc:
            return "code"
        if "doc" in desc or "document" in desc or "readme" in desc:
            return "text"
        if "analyz" in desc or "report" in desc:
            return "report"
        return "text"
