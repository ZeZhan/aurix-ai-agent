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
import os
import platform
import subprocess
import sys

from . import PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION


def main() -> None:
    cwd = os.environ.get("AURIX_MCP_CWD")
    if cwd is not None:
        if not os.path.isabs(cwd):
            sys.stderr.write("AURIX_MCP_CWD must be an absolute directory path.\n")
            raise SystemExit(1)
        try:
            os.chdir(cwd)
        except OSError as exc:
            sys.stderr.write(f"Cannot use AURIX_MCP_CWD {cwd!r}: {exc}\n")
            raise SystemExit(1) from exc

    sub = sys.argv[1] if len(sys.argv) > 1 else ""

    if sub == "--python-args":
        if len(sys.argv) < 3:
            sys.stderr.write("--python-args requires Python interpreter arguments.\n")
            raise SystemExit(1)
        try:
            # Inherit stdio unchanged so custom MCP entry points keep their transport.
            result = subprocess.run([sys.executable, *sys.argv[2:]], check=False)
        except OSError as exc:
            sys.stderr.write(f"Cannot start custom MCP entry point: {exc}\n")
            raise SystemExit(1) from exc
        raise SystemExit(result.returncode)

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

    # FastMCP builds workspace instructions at import time.
    from .server_fastmcp import mcp

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
