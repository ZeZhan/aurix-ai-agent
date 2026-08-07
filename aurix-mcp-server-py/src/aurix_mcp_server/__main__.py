"""CLI entry point. Mirrors the CLI surface of src/index.ts.

Usage:
  aurix-mcp-server             Start stdio MCP server
  aurix-mcp-server --stdio     Start stdio MCP server
  aurix-mcp-server doctor      Print health report JSON
  aurix-mcp-server --doctor    Print health report JSON
  aurix-mcp-server --version   Print version
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys

from . import PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION
from .server_fastmcp import mcp


def main() -> None:
    sub = sys.argv[1] if len(sys.argv) > 1 else ""

    if sub in ("--help", "-h"):
        sys.stdout.write(
            "\n".join([
                "AURIX MCP Server",
                "",
                "Usage:",
                "  aurix-mcp-server             Start stdio MCP server",
                "  aurix-mcp-server --stdio     Start stdio MCP server",
                "  aurix-mcp-server doctor      Print health report JSON",
                "  aurix-mcp-server --doctor    Print health report JSON",
                "  aurix-mcp-server --version   Print version",
                "",
            ])
        )
        return

    if sub in ("--version", "-v"):
        sys.stdout.write(SERVER_VERSION + "\n")
        return

    if sub in ("doctor", "--doctor"):
        tool_names = [t.name for t in asyncio.run(mcp.list_tools())]
        report = {
            "ok": True,
            "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "protocolVersion": PROTOCOL_VERSION,
            "toolCount": len(tool_names),
            "tools": tool_names,
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "machine": platform.machine(),
        }
        sys.stdout.write(json.dumps(report, indent=2) + "\n")
        return

    mcp.run()


if __name__ == "__main__":
    main()
