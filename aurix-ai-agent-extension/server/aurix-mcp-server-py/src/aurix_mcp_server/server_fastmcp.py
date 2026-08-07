"""AURIX MCP server — high-level FastMCP implementation.

Design:
- Input schemas are generated automatically from each tool function's typed
  signature — no hand-written JSON Schema.
- Business logic is 100% reused: every tool delegates to the existing
  ``_run`` / ``*_run`` coroutine in ``tools/*.py``.
- Output fidelity is preserved by returning ``CallToolResult`` directly, which
  FastMCP passes through verbatim (content + structuredContent + isError).

Run:
    python -m aurix_mcp_server            # stdio server
    python -m aurix_mcp_server doctor     # health report JSON
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal, Optional

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent as MCPTextContent, ToolAnnotations

from . import SERVER_NAME, SERVER_VERSION
from .tooldef import RiskLevel, ToolContext, ToolResult
from .tools.ads_create_project import _run as ads_create_project_run
from .tools.build_run import _run as build_run_run
from .tools.examples import _import_run, _read_source_run, _search_run
from .tools.flash_program import _run as flash_program_run
from .tools.illd_provision import _run as illd_provision_run
from .tools.scan_project import _run as scan_project_run


# ---------------------------------------------------------------------------
# Dynamic instructions (ported from the low-level server)
# ---------------------------------------------------------------------------

def _read_context_json(cwd: str) -> Optional[dict[str, Any]]:
    candidate = os.path.join(cwd, ".aurix-ai", "context.json")
    try:
        if not os.path.exists(candidate):
            return None
        with open(candidate, "r", encoding="utf-8") as fh:
            parsed = json.load(fh)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def build_instructions() -> str:
    cwd = os.getcwd()
    ctx = _read_context_json(cwd) or {}

    def _str(value: Any) -> str:
        return value if isinstance(value, str) and value else ""

    board = (
        _str(ctx.get("selectedBoard"))
        or _str(ctx.get("board"))
        or _str(ctx.get("device"))
        or "(not selected)"
    )
    build_cmd = _str(ctx.get("defaultBuildCommand"))
    build_cwd = _str(ctx.get("defaultBuildCwd"))
    flash_cmd = _str(ctx.get("defaultFlashCommand"))
    ide_path = _str(ctx.get("idePath"))

    lines = [
        "You are assisting on an Infineon AURIX microcontroller project.",
        f"Workspace: {cwd}",
        f"Selected board / device: {board}",
        f"MCP server runtime: Python ({SERVER_VERSION})",
        "",
        "PREFERRED WORKFLOW — always use the AURIX MCP tools instead of raw shell commands:",
        "  • Build  → call the `build_run` tool (auto-prepends tricore-gcc and make to PATH).",
        "  • Flash  → call the `flash_program` tool with the produced .elf. It auto-locates "
        "aurixflasher.exe from your AURIX IDE install under C:\\\\Infineon (AURIX Development Studio / "
        "Configuration Studio), C:\\\\Infineon\\\\ide\\\\tools\\\\, or context.json. Just pass the image path.",
        "  • Project scan / examples / iLLD provisioning → use the `*_scan`, `examples_*`, `illd_*` tools.",
        "",
        "DO NOT recursively search C:\\Infineon for make.exe / aurixflasher.exe — the MCP tools already know "
        "the canonical paths.",
        "DO NOT shell out to `make` directly unless `build_run` has failed; if you must, prepend these to PATH:",
        "  C:\\Infineon\\ide\\tools\\make",
        "  C:\\Infineon\\ide\\tools\\Compilers\\tricore-gcc11\\bin",
    ]

    if build_cmd or build_cwd:
        lines.append("")
        lines.append("Project build hints (from .aurix-ai/context.json):")
        if build_cmd:
            lines.append(f"  defaultBuildCommand: {build_cmd}")
        if build_cwd:
            lines.append(f"  defaultBuildCwd:     {build_cwd}")
    if flash_cmd:
        lines.append(f"  defaultFlashCommand: {flash_cmd}")
    if ide_path:
        lines.append(f"  idePath:             {ide_path}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Adapters: bridge existing ToolResult / ToolContext to FastMCP
# ---------------------------------------------------------------------------

def _ann(risk: RiskLevel) -> ToolAnnotations:
    """Mirror the low-level server's risk -> annotations mapping."""
    return ToolAnnotations(
        readOnlyHint=risk == "read",
        destructiveHint=risk == "destructive",
        openWorldHint=risk != "read",
    )


def _to_call_result(result: ToolResult) -> CallToolResult:
    """Pass ToolResult through with full fidelity (FastMCP returns it verbatim)."""
    return CallToolResult(
        content=[MCPTextContent(type="text", text=c.text) for c in result.content],
        structuredContent=result.structured_content,
        isError=result.is_error,
    )


def _tool_context(ctx: Optional[Context]) -> ToolContext:
    """Build a ToolContext whose send_progress forwards to FastMCP's Context.

    When no context is available (doctor / tests) it degrades to a no-op.
    """
    counter = {"value": 0.0}

    async def send_progress(chunk: str, stream: str = "stdout") -> None:
        if ctx is None:
            return
        counter["value"] += 1
        try:
            await ctx.report_progress(counter["value"], None, chunk.strip())
        except Exception:
            pass
        try:
            if stream == "stderr":
                await ctx.warning(chunk)
            else:
                await ctx.info(chunk)
        except Exception:
            pass

    return ToolContext(send_progress=send_progress)


def _clean(**kwargs: Any) -> dict[str, Any]:
    """Drop None values so omitted optional params behave like absent JSON keys."""
    return {k: v for k, v in kwargs.items() if v is not None}


# ---------------------------------------------------------------------------
# Server + tools
# ---------------------------------------------------------------------------

mcp = FastMCP(SERVER_NAME, instructions=build_instructions())


@mcp.tool(
    name="ads.create_project",
    description=(
        "Create a device project template from the local ADS installation. "
        "Extracts iLLD libraries, configuration files, linker scripts, and source stubs "
        "for the specified device into a reusable cache directory. "
        "If 'workspace' is provided, deploys the skeleton into that directory."
    ),
    annotations=_ann("write"),
)
async def ads_create_project(device: str, workspace: str | None = None) -> CallToolResult:
    """Create/deploy an ADS device project template.

    Args:
        device: Target device (e.g. TC4D7, TC387, TC397).
        workspace: Target workspace directory to deploy into. If omitted, only caches the template.
    """
    args = _clean(device=device, workspace=workspace)
    return _to_call_result(await ads_create_project_run(args, _tool_context(None)))


@mcp.tool(
    name="build.run",
    description=(
        "Build an AURIX project with auto-detected tricore-gcc and make. "
        "For a normal build, pass workspace only and omit command; command is reserved "
        "for an actual custom shell command."
    ),
    annotations=_ann("write"),
)
async def build_run(
    command: str | None = None,
    workspace: str | None = None,
    cwd: str | None = None,
    pathAdditions: list[str] | None = None,
    timeoutMs: int | None = None,
    shell: bool = True,
    ctx: Context | None = None,
) -> CallToolResult:
    """Run a build command, auto-prepending the AURIX toolchain to PATH.

    Args:
        command: Actual custom shell command. Omit for a normal project build. The aliases
            "build" and "build project" select the default build for compatibility.
        workspace: Workspace folder path. Default: context workspace or current working directory.
        cwd: Working directory for the build. Relative values are resolved against workspace.
        pathAdditions: Directories to prepend to PATH. Auto-detects tricore-gcc/make when omitted.
        timeoutMs: Build timeout in milliseconds.
        shell: Run via shell. Default: true.
    """
    args = _clean(
        command=command, workspace=workspace, cwd=cwd,
        pathAdditions=pathAdditions, timeoutMs=timeoutMs, shell=shell,
    )
    return _to_call_result(await build_run_run(args, _tool_context(ctx)))


@mcp.tool(
    name="examples.import",
    description=(
        "Import (download) a complete AURIX code example from the GitHub repository "
        "into a local target directory."
    ),
    annotations=_ann("write"),
)
async def examples_import(
    id: str,
    targetDir: str,
    indexPath: str | None = None,
    overwrite: bool | None = None,
) -> CallToolResult:
    """Download a full code example into a local directory.

    Args:
        id: Example ID from the examples index.
        targetDir: Local directory to download the example into.
        indexPath: Optional path to a custom examples index.
        overwrite: Overwrite existing files. Default: false.
    """
    args = _clean(id=id, targetDir=targetDir, indexPath=indexPath, overwrite=overwrite)
    return _to_call_result(await _import_run(args, _tool_context(None)))


@mcp.tool(
    name="examples.read_source",
    description=(
        "Read the full source code files of an AURIX code example. "
        "Uses raw.githubusercontent.com (no API rate limit)."
    ),
    annotations=_ann("read"),
)
async def examples_read_source(
    id: str,
    files: list[str] | None = None,
    indexPath: str | None = None,
) -> CallToolResult:
    """Read the source files of a code example.

    Args:
        id: Example ID from the examples index.
        files: Specific files to read. If omitted, reads cpuMainFiles from the index.
        indexPath: Optional path to a custom examples index.
    """
    args = _clean(id=id, files=files, indexPath=indexPath)
    return _to_call_result(await _read_source_run(args, _tool_context(None)))


@mcp.tool(
    name="examples.search",
    description=(
        "Search the indexed Infineon AURIX code examples catalog by query, board, "
        "family, or keyword."
    ),
    annotations=_ann("read"),
)
async def examples_search(
    query: str | None = None,
    board: str | None = None,
    family: str | None = None,
    keyword: str | None = None,
    limit: int | None = None,
    indexPath: str | None = None,
) -> CallToolResult:
    """Search the code examples catalog.

    Args:
        query: Free-text query.
        board: Filter by board.
        family: Filter by device family.
        keyword: Filter by keyword.
        limit: Maximum number of results.
        indexPath: Optional path to a custom examples index.
    """
    args = _clean(
        query=query, board=board, family=family,
        keyword=keyword, limit=limit, indexPath=indexPath,
    )
    return _to_call_result(await _search_run(args, _tool_context(None)))


@mcp.tool(
    name="flash.program",
    description=(
        "Program an ELF image via aurixflasher.exe (resolves device id via lsmcdd when available). "
        "If image is omitted, the newest .elf under <workspace>/build is auto-selected."
    ),
    annotations=_ann("destructive"),
)
async def flash_program(
    workspace: str | None = None,
    image: str | None = None,
    command: str | None = None,
    cwd: str | None = None,
    flasherPath: str | None = None,
    lsmcddPath: str | None = None,
    device: str | None = None,
    timeoutMs: int | None = None,
    ctx: Context | None = None,
) -> CallToolResult:
    """Program an ELF image onto the target.

    Args:
        workspace: Workspace root path.
        image: ELF image path for aurixflasher mode. Optional — if omitted, the newest
            .elf under <workspace>/build is auto-discovered.
        command: Actual custom shell command for a custom flash flow. Omit for normal
            aurixflasher mode; do not pass "flash" or "program" as an intent label.
        cwd: Working directory for command mode. Relative values are resolved against workspace.
        flasherPath: Path to aurixflasher.exe.
        lsmcddPath: Path to lsmcdd.exe for device name -> id mapping.
        device: Device name or numeric id.
        timeoutMs: Timeout in milliseconds.
    """
    args = _clean(
        workspace=workspace, image=image, command=command, cwd=cwd,
        flasherPath=flasherPath, lsmcddPath=lsmcddPath, device=device, timeoutMs=timeoutMs,
    )
    return _to_call_result(await flash_program_run(args, _tool_context(ctx)))


@mcp.tool(
    name="illd.provision",
    description=(
        "List or copy iLLD library modules from the GitHub-cloned cache into the project workspace. "
        "Use action='list' to browse the cached iLLD directory structure, "
        "action='copy' to copy specific module directories into the project."
    ),
    annotations=_ann("write"),
)
async def illd_provision(
    action: Literal["list", "copy"],
    device: str,
    workspace: str | None = None,
    subdir: str | None = None,
    sources: list[str] | None = None,
    destination: str | None = None,
) -> CallToolResult:
    """List or copy iLLD modules.

    Args:
        action: 'list' to browse cached iLLD structure, 'copy' to copy modules into workspace.
        device: Device hint, e.g. TC37, TC499, TC4D7.
        workspace: Workspace root (defaults to current cwd).
        subdir: For list: subdirectory within iLLD cache to list.
        sources: For copy: paths relative to iLLD cache root to copy.
        destination: For copy: destination directory relative to workspace root.
    """
    args = _clean(
        action=action, device=device, workspace=workspace,
        subdir=subdir, sources=sources, destination=destination,
    )
    return _to_call_result(await illd_provision_run(args, _tool_context(None)))


@mcp.tool(
    name="project.scan",
    description=(
        "Recursively scan a project directory and return all source files (.c), assembly files (.S/.s/.src), "
        "include directories (containing .h files), and linker scripts (.ld/.lsl). "
        "Also detects the device family from iLLD path patterns. "
        "Use this to discover what files exist on disk when generating a Makefile."
    ),
    annotations=_ann("read"),
)
async def project_scan(
    projectPath: str | None = None,
    excludeDirs: list[str] | None = None,
    maxFiles: int | None = None,
) -> CallToolResult:
    """Scan a project directory for sources, includes and linker scripts.

    Args:
        projectPath: Absolute path to the project root. Default: workspace root.
        excludeDirs: Directories to exclude from scanning (relative to project root).
        maxFiles: Max files to scan.
    """
    args = _clean(projectPath=projectPath, excludeDirs=excludeDirs, maxFiles=maxFiles)
    return _to_call_result(await scan_project_run(args, _tool_context(None)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _doctor() -> None:
    import asyncio

    async def _collect() -> list[str]:
        return [t.name for t in await mcp.list_tools()]

    names = asyncio.run(_collect())
    print(json.dumps({
        "ok": True,
        "server": {"name": SERVER_NAME, "version": SERVER_VERSION},
        "api": "FastMCP",
        "toolCount": len(names),
        "tools": names,
    }, indent=2))


def main() -> None:
    import sys

    if len(sys.argv) > 1 and sys.argv[1] in ("--doctor", "doctor"):
        _doctor()
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("--version",):
        print(SERVER_VERSION)
        return
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
