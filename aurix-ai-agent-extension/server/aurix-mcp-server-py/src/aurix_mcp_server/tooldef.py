"""Tool definition primitives shared by all AURIX MCP tools.

Mirrors the `ToolDefinition` / `ToolResult` contract from the original
TypeScript implementation (src/types.ts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

RiskLevel = Literal["read", "write", "destructive"]


@dataclass
class TextContent:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ToolResult:
    """Result returned by a tool, mirroring the MCP CallToolResult shape."""

    content: list[TextContent]
    is_error: bool = False
    structured_content: Optional[dict[str, Any]] = None

    @staticmethod
    def text(text: str, *, is_error: bool = False,
             structured: Optional[dict[str, Any]] = None) -> "ToolResult":
        return ToolResult(
            content=[TextContent(text=text)],
            is_error=is_error,
            structured_content=structured,
        )


# A progress callback: send_progress(chunk, stream)
ProgressCallback = Callable[[str, Literal["stdout", "stderr"]], Awaitable[None]]


@dataclass
class ToolContext:
    """Per-call context passed to a tool's run function.

    Provides a best-effort progress streaming hook. When no MCP session is
    active (unit tests, smoke runs) the callback is a no-op.
    """

    send_progress: ProgressCallback
