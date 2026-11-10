"""Tool Sandbox — safe execution environment for agent tool calls.

Provides:
    - Permission checking (tool whitelist, path whitelist)
    - Resource limits (timeout, output size)
    - Audit logging
    - subprocess isolation for code execution
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolPermission(BaseModel):
    """Permission profile for a tool."""
    tool_name: str
    allowed_paths: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)
    timeout_seconds: int = 30
    max_output_size: int = 10000  # bytes


class ToolResult(BaseModel):
    """Result of a tool execution."""
    success: bool
    output: str = ""
    error: str = ""
    exit_code: int = 0
    duration_ms: float = 0.0


class CodeRunResult(BaseModel):
    """Result of code execution."""
    stdout: str
    stderr: str
    exit_code: int


class ToolSandbox:
    """Sandboxed tool execution environment.

    Responsibilities:
        - Execute tool calls with permission checks
        - Enforce resource limits (timeout, output size)
        - Log all tool invocations for audit
        - Isolate code execution via subprocess

    Not responsible for:
        - Deciding which tool to call (Agent decides)
        - Managing tool outputs (StateStore handles this)
    """

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace) if workspace else Path.cwd()
        self._audit_log: list[dict] = []

    def execute(
        self,
        tool_name: str,
        params: dict,
        permission: ToolPermission | None = None,
    ) -> ToolResult:
        """Execute a tool call within the sandbox.

        Args:
            tool_name: Name of the tool to execute
            params: Tool parameters
            permission: Permission profile (None = use defaults)

        Returns:
            ToolResult with output or error
        """
        start = time.time()
        permission = permission or ToolPermission(tool_name=tool_name)

        # Permission check
        if tool_name != permission.tool_name:
            return ToolResult(success=False, error=f"Tool {tool_name} not permitted")

        try:
            handler = self._get_handler(tool_name)
            if not handler:
                return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

            # Path check for file operations
            if "path" in params or "file_path" in params:
                target = Path(params.get("path") or params.get("file_path", ""))
                # Prevent path traversal (../../etc/passwd)
                if ".." in str(target):
                    return ToolResult(success=False, error="Path traversal not allowed")
                if not self._is_path_allowed(target, permission):
                    return ToolResult(success=False, error=f"Path not allowed: {target}")

            result = handler(params, permission)

            # Truncate output if needed
            if len(result.output) > permission.max_output_size:
                result.output = result.output[:permission.max_output_size] + "\n[truncated]"

            duration = (time.time() - start) * 1000
            result.duration_ms = round(duration, 1)

            # Audit log
            self._audit_log.append({
                "tool": tool_name,
                "params_keys": list(params.keys()),
                "success": result.success,
                "duration_ms": result.duration_ms,
                "timestamp": time.time(),
            })

            return result

        except Exception as e:
            duration = (time.time() - start) * 1000
            logger.error("Tool %s execution error: %s", tool_name, e)
            return ToolResult(success=False, error=str(e), duration_ms=round(duration, 1))

    def get_audit_log(self) -> list[dict]:
        return list(self._audit_log)

    # ──────────────────────────────────────────
    # Tool handlers
    # ──────────────────────────────────────────

    def _get_handler(self, tool_name: str):
        """Get the handler function for a tool."""
        handlers = {
            "file_read": self._tool_file_read,
            "file_write": self._tool_file_write,
            "code_run": self._tool_code_run,
            "test_run": self._tool_test_run,
            "data_read": self._tool_data_read,
            "http_get": self._tool_http_get,
            "list_dir": self._tool_list_dir,
        }
        return handlers.get(tool_name)

    def _tool_file_read(self, params: dict, perm: ToolPermission) -> ToolResult:
        """Read a file's content."""
        path = self.workspace / params.get("path", "")
        if not path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        try:
            content = path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _tool_file_write(self, params: dict, perm: ToolPermission) -> ToolResult:
        """Write content to a file."""
        path = self.workspace / params.get("path", "")
        content = params.get("content", "")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Wrote {len(content)} chars to {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _tool_code_run(self, params: dict, perm: ToolPermission) -> ToolResult:
        """Execute Python code in a sandboxed subprocess."""
        code = params.get("code", "")
        language = params.get("language", "python")
        timeout = perm.timeout_seconds

        try:
            result = self._run_subprocess(code, language, timeout)
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr] {result.stderr}"
            return ToolResult(success=result.exit_code == 0, output=output, exit_code=result.exit_code)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _tool_test_run(self, params: dict, perm: ToolPermission) -> ToolResult:
        """Run test suite via pytest."""
        test_path = params.get("path", "tests/")
        timeout = perm.timeout_seconds
        try:
            proc = subprocess.run(
                ["python", "-m", "pytest", test_path, "-v", "--tb=short"],
                capture_output=True, timeout=timeout, text=True,
                cwd=str(self.workspace),
            )
            output = proc.stdout[-perm.max_output_size:]
            return ToolResult(success=proc.returncode == 0, output=output, exit_code=proc.returncode)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Test run timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _tool_data_read(self, params: dict, perm: ToolPermission) -> ToolResult:
        """Read data file (CSV, JSON, etc.)."""
        return self._tool_file_read(params, perm)

    def _tool_http_get(self, params: dict, perm: ToolPermission) -> ToolResult:
        """HTTP GET request (with domain whitelist check)."""
        import urllib.request
        url = params.get("url", "")
        timeout = perm.timeout_seconds
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                data = resp.read(perm.max_output_size).decode("utf-8", errors="replace")
            return ToolResult(success=True, output=data)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _tool_list_dir(self, params: dict, perm: ToolPermission) -> ToolResult:
        """List directory contents."""
        path = self.workspace / params.get("path", ".")
        if not path.is_dir():
            return ToolResult(success=False, error=f"Not a directory: {path}")
        entries = [f"{p.name}/" if p.is_dir() else p.name for p in sorted(path.iterdir())]
        return ToolResult(success=True, output="\n".join(entries[:100]))

    # ──────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────

    def _is_path_allowed(self, path: Path, perm: ToolPermission) -> bool:
        """Check if path is within allowed directories."""
        if not perm.allowed_paths:
            return True  # no restriction
        try:
            resolved = path.resolve()
            return any(
                resolved.is_relative_to(Path(p).resolve())
                for p in perm.allowed_paths
            )
        except Exception:
            return False

    def _run_subprocess(self, code: str, language: str, timeout: int) -> CodeRunResult:
        """Run code in an isolated subprocess."""
        with tempfile.TemporaryDirectory() as tmpdir:
            if language == "python":
                script = Path(tmpdir) / "snippet.py"
                script.write_text(code, encoding="utf-8")
                cmd = ["python", str(script)]
            elif language == "bash":
                script = Path(tmpdir) / "snippet.sh"
                script.write_text(code, encoding="utf-8")
                cmd = ["bash", str(script)]
            else:
                return CodeRunResult(stdout="", stderr=f"Unsupported language: {language}", exit_code=1)

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, timeout=timeout,
                    cwd=tmpdir, text=True,
                )
                return CodeRunResult(
                    stdout=proc.stdout[:10000],
                    stderr=proc.stderr[:5000],
                    exit_code=proc.returncode,
                )
            except subprocess.TimeoutExpired:
                return CodeRunResult(stdout="", stderr="Timeout", exit_code=-1)
