"""LLM Client — OpenAI-compatible chat completions wrapper.

Uses the `openai` SDK against any OpenAI-compatible endpoint
(OpenAI, Azure, DeepSeek, Qwen, apiforge and other proxies).

Configuration priority:
    1. Explicit constructor arguments
    2. Environment variables (CONTRACTNET_API_KEY, CONTRACTNET_BASE_URL, CONTRACTNET_MODEL)
    3. .env file in project root (loaded via python-dotenv if available)

Supports:
    - complete(): single-shot completion (used by Planner, QualityGate)
    - chat(): multi-turn messages with optional tool definitions (used by ReAct agents)
    - Retry with exponential backoff on transient errors
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    # Look for .env in project root (walk up from CWD)
    for candidate in [Path.cwd() / ".env", Path(__file__).resolve().parents[4] / ".env"]:
        if candidate.exists():
            load_dotenv(candidate)
            break
except ImportError:
    pass

logger = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    """LLM API configuration."""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 2000
    timeout: int = 60
    max_retries: int = 3

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build config from environment variables.

        Supported variables:
            CONTRACTNET_API_KEY  — API key (required)
            CONTRACTNET_BASE_URL — Base URL (default: OpenAI)
            CONTRACTNET_MODEL    — Default model (default: gpt-4o-mini)
        """
        return cls(
            api_key=os.environ.get("CONTRACTNET_API_KEY", ""),
            base_url=os.environ.get("CONTRACTNET_BASE_URL", "https://api.openai.com/v1"),
            model=os.environ.get("CONTRACTNET_MODEL", "gpt-4o-mini"),
        )


@dataclass
class LLMResponse:
    """Normalized LLM response."""
    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    tool_calls: list[dict] = field(default_factory=list)


class LLMError(Exception):
    """Raised when LLM API call fails after all retries."""


class LLMClient:
    """OpenAI-compatible LLM client.

    Usage:
        client = LLMClient()  # reads env vars
        response = client.complete("Say hello")
        print(response.content)
    """

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        """Initialize the OpenAI SDK client."""
        if not self.config.api_key:
            raise LLMError(
                "No API key configured. Set CONTRACTNET_API_KEY environment variable "
                "or pass api_key in LLMConfig."
            )
        try:
            from openai import OpenAI
        except ImportError as e:
            raise LLMError(
                "openai package not installed. Install with: pip install openai"
            ) from e

        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def complete(self, prompt: str, system: str | None = None, **overrides) -> str:
        """Single-shot completion — returns content string.

        Used by Planner (task decomposition) and QualityGate (LLM-as-Judge).

        Args:
            prompt: User prompt
            system: Optional system prompt
            **overrides: temperature / max_tokens / model overrides

        Returns:
            Response content string

        Raises:
            LLMError: If the API call fails after all retries
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.chat(messages, **overrides)
        return self._strip_markdown_fences(response.content)

    @staticmethod
    def _strip_markdown_fences(text: str) -> str:
        """Strip markdown code fences that LLMs often wrap JSON in."""
        text = text.strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
        return text.strip()

    def chat(self, messages: list[dict], tools: list[dict] | None = None, **overrides) -> LLMResponse:
        """Chat completion with optional tool definitions.

        Used by ReAct agents for multi-turn execution.

        Args:
            messages: Chat messages [{role, content}, ...]
            tools: Optional tool definitions (OpenAI function calling format)
            **overrides: temperature / max_tokens / model overrides

        Returns:
            LLMResponse with content and/or tool_calls
        """
        if not self._client:
            raise LLMError("LLM client not initialized")

        model = overrides.pop("model", self.config.model)
        temperature = overrides.pop("temperature", self.config.temperature)
        max_tokens = overrides.pop("max_tokens", self.config.max_tokens)

        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        # Zhipu GLM reasoning models: disable thinking unless explicitly requested
        # (saves tokens and latency for structured agent tasks).
        # Passed via extra_body because the OpenAI SDK strict-types unknown fields.
        thinking = overrides.pop("thinking", None)
        if thinking is not None:
            kwargs["extra_body"] = {"thinking": thinking}
        elif model.startswith("glm"):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                start = time.time()
                resp = self._client.chat.completions.create(**kwargs)
                duration = time.time() - start

                logger.debug(
                    "LLM call OK: model=%s, %.1fs, tokens=%s",
                    model, duration,
                    resp.usage.total_tokens if resp.usage else "?",
                )

                return self._parse_response(resp)
            except Exception as e:
                last_error = e
                status = getattr(e, "status_code", None)
                # Fail fast on non-transient errors (auth, quota, bad model)
                if status in (401, 403, 404):
                    raise LLMError(str(e)) from e
                wait = 2 ** attempt
                logger.warning(
                    "LLM call attempt %d/%d failed: %s — retrying in %ds",
                    attempt, self.config.max_retries, e, wait,
                )
                time.sleep(wait)

        raise LLMError(f"LLM call failed after {self.config.max_retries} retries: {last_error}")

    def _parse_response(self, resp) -> LLMResponse:
        """Parse OpenAI SDK response into LLMResponse."""
        choice = resp.choices[0] if resp.choices else None
        tool_calls = []
        if choice and choice.message and choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in choice.message.tool_calls
            ]

        usage = resp.usage
        return LLMResponse(
            content=choice.message.content if choice and choice.message else "",
            model=resp.model or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            finish_reason=choice.finish_reason if choice else "",
            tool_calls=tool_calls,
        )
