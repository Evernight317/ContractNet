"""Built-in tool definitions and preset agents.

Provides:
    - Tool registry with descriptions for LLM function calling
    - Pre-configured agent types (Coder, Tester, Doc, Analyst, Reviewer, General)
"""

from __future__ import annotations

from contractnet.core.agent import BaseAgent, CapabilityProfile


# ──────────────────────────────────────────────
# Tool descriptions (for LLM function calling)
# ──────────────────────────────────────────────

TOOL_DEFINITIONS = {
    "file_read": {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read the content of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                },
                "required": ["path"],
            },
        },
    },
    "file_write": {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write content to a file (creates parent dirs if needed)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    "code_run": {
        "type": "function",
        "function": {
            "name": "code_run",
            "description": "Execute Python code and return stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "language": {"type": "string", "enum": ["python", "bash"], "default": "python"},
                },
                "required": ["code"],
            },
        },
    },
    "test_run": {
        "type": "function",
        "function": {
            "name": "test_run",
            "description": "Run test suite via pytest",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Test directory or file path"},
                },
                "required": [],
            },
        },
    },
    "data_read": {
        "type": "function",
        "function": {
            "name": "data_read",
            "description": "Read a data file (CSV, JSON, etc.)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative data file path"},
                },
                "required": ["path"],
            },
        },
    },
    "http_get": {
        "type": "function",
        "function": {
            "name": "http_get",
            "description": "Make an HTTP GET request",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to request"},
                },
                "required": ["url"],
            },
        },
    },
    "list_dir": {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List directory contents",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: .)"},
                },
                "required": [],
            },
        },
    },
}


# ──────────────────────────────────────────────
# Preset Agent Profiles
# ──────────────────────────────────────────────

CODER_PROFILE = CapabilityProfile(
    agent_id="agent_coder",
    name="Coder Agent",
    task_types=["code", "design"],
    tools=["file_read", "file_write", "code_run", "list_dir"],
    self_assessed_skills={"python": 0.9, "javascript": 0.7, "sql": 0.6, "architecture": 0.8},
)

TESTER_PROFILE = CapabilityProfile(
    agent_id="agent_tester",
    name="Tester Agent",
    task_types=["test"],
    tools=["file_read", "code_run", "test_run", "list_dir"],
    self_assessed_skills={"python": 0.85, "pytest": 0.9, "testing": 0.9},
)

DOC_PROFILE = CapabilityProfile(
    agent_id="agent_doc",
    name="Doc Agent",
    task_types=["doc"],
    tools=["file_read", "file_write", "list_dir"],
    self_assessed_skills={"markdown": 0.9, "documentation": 0.9, "api_docs": 0.85},
)

ANALYST_PROFILE = CapabilityProfile(
    agent_id="agent_analyst",
    name="Analyst Agent",
    task_types=["analysis"],
    tools=["data_read", "code_run", "file_read", "file_write"],
    self_assessed_skills={"data_analysis": 0.9, "statistics": 0.8, "visualization": 0.75},
)

REVIEWER_PROFILE = CapabilityProfile(
    agent_id="agent_reviewer",
    name="Reviewer Agent",
    task_types=["review"],
    tools=["file_read", "list_dir"],
    self_assessed_skills={"code_review": 0.9, "architecture": 0.8, "security": 0.7},
)

GENERAL_PROFILE = CapabilityProfile(
    agent_id="agent_general",
    name="General Agent",
    task_types=["*"],
    tools=["file_read", "file_write", "code_run", "list_dir"],
    self_assessed_skills={"general": 0.7},
)

ALL_PROFILES = {
    "coder": CODER_PROFILE,
    "tester": TESTER_PROFILE,
    "doc": DOC_PROFILE,
    "analyst": ANALYST_PROFILE,
    "reviewer": REVIEWER_PROFILE,
    "general": GENERAL_PROFILE,
}
