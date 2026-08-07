"""MCP tool: illd.provision

List or copy iLLD library modules from the GitHub-cloned cache into the
project workspace. Mirrors src/tools.illdProvision.ts.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Optional

from ..tooldef import TextContent, ToolContext, ToolResult
from ..utils import ensure_directory, safe_error_message

# Shared iLLD cache directory (~/.aurix-agent/illd_cache/)
ILLD_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".aurix-agent", "illd_cache")

SKIP_DIR_NAMES = {".git", ".svn", ".hg", "node_modules"}
MAX_TREE_DEPTH = 6


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def _parse_input(args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("illd.provision requires an object argument")
    action = args.get("action")
    if action not in ("list", "copy"):
        raise ValueError('illd.provision requires action: "list" or "copy"')
    device = args.get("device")
    if not isinstance(device, str) or not device.strip():
        raise ValueError("illd.provision requires device")
    if action == "copy":
        sources = args.get("sources")
        if not isinstance(sources, list) or len(sources) == 0:
            raise ValueError("illd.provision copy requires non-empty sources array")
        destination = args.get("destination")
        if not isinstance(destination, str) or not destination.strip():
            raise ValueError("illd.provision copy requires destination")
    return args


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_family(device: str) -> str:
    d = device.strip().lower()
    if "tc2" in d:
        return "tc2"
    if "tc3" in d:
        return "tc3"
    if "tc4" in d:
        return "tc4"
    return "unknown"


def _get_cache_root(family: str) -> Optional[str]:
    clone_dir = os.path.join(ILLD_CACHE_DIR, f"illd_release_{family}x")
    if os.path.isdir(os.path.join(clone_dir, ".git")):
        return clone_dir
    return None


def _build_tree(root: str, subdir: Optional[str] = None, max_depth: int = MAX_TREE_DEPTH) -> str:
    base = os.path.join(root, subdir) if subdir else root
    if not os.path.exists(base):
        return f"(directory not found: {subdir or root})"

    lines: list[str] = []

    def walk(directory: str, prefix: str, depth: int) -> None:
        if depth > max_depth:
            lines.append(f"{prefix}... (depth limit)")
            return
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return

        dirs = sorted(
            [e for e in entries if e.is_dir() and e.name not in SKIP_DIR_NAMES],
            key=lambda e: e.name,
        )
        files = sorted(
            [e for e in entries if e.is_file()],
            key=lambda e: e.name,
        )

        for d in dirs:
            lines.append(f"{prefix}{d.name}/")
            walk(d.path, prefix + "  ", depth + 1)

        # Only show relevant source/header files near leaf level
        if depth >= max_depth - 1:
            relevant = [f for f in files if re.search(r"\.(h|c|hpp|cpp|ld|lsl)$", f.name, re.IGNORECASE)]
            for f in relevant:
                lines.append(f"{prefix}{f.name}")

    rel_label = subdir or os.path.basename(root)
    lines.append(f"{rel_label}/")
    walk(base, "  ", 1)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Copy logic — copies source directories/files from cache to workspace
# ---------------------------------------------------------------------------

def _validate_and_resolve_paths(
    cache_root: str,
    workspace_root: str,
    sources: list[str],
    destination: str,
) -> tuple[list[str], str]:
    """Returns (resolved_sources, resolved_dest)."""
    resolved_dest = os.path.normpath(os.path.join(workspace_root, destination))
    norm_workspace = os.path.normpath(workspace_root)

    # Path traversal check for destination
    lhs_dest = resolved_dest.lower() if sys.platform == "win32" else resolved_dest
    rhs_ws = norm_workspace.lower() if sys.platform == "win32" else norm_workspace
    if lhs_dest != rhs_ws and not lhs_dest.startswith(rhs_ws + os.sep):
        raise ValueError("destination escapes workspace root")

    # Resolve and validate each source
    norm_cache = os.path.normpath(cache_root)
    lhs_cache = norm_cache.lower() if sys.platform == "win32" else norm_cache

    resolved_sources: list[str] = []
    for src in sources:
        resolved = os.path.normpath(os.path.join(cache_root, src))
        lhs_src = resolved.lower() if sys.platform == "win32" else resolved
        if lhs_src != lhs_cache and not lhs_src.startswith(lhs_cache + os.sep):
            raise ValueError(f"source path escapes iLLD cache: {src}")
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"source not found in iLLD cache: {src}")
        resolved_sources.append(resolved)

    return resolved_sources, resolved_dest


def _copy_recursive(src: str, dest: str) -> int:
    """Copy src to dest recursively. Returns number of files copied."""
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(src, dest)
        return 1
    if not os.path.isdir(src):
        return 0

    os.makedirs(dest, exist_ok=True)
    count = 0
    for entry in os.scandir(src):
        if entry.name in SKIP_DIR_NAMES:
            continue
        count += _copy_recursive(entry.path, os.path.join(dest, entry.name))
    return count


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

async def _handle_list(args: dict[str, Any]) -> ToolResult:
    family = _infer_family(args["device"])
    if family == "unknown":
        return ToolResult.text(
            f'Cannot infer device family from "{args["device"]}". Expected TC2xx/TC3xx/TC4xx.',
            is_error=True,
        )

    cache_root = _get_cache_root(family)
    if not cache_root:
        return ToolResult.text(
            f"No cached iLLD found for family {family}x. "
            f"Clone the iLLD repo to {ILLD_CACHE_DIR} or use ads.create_project to provision iLLD.",
            is_error=True,
        )

    subdir = args.get("subdir")
    tree = _build_tree(cache_root, subdir)
    return ToolResult(
        content=[TextContent(text=f"iLLD cache for {family}x ({cache_root}):\n\n{tree}")],
        structured_content={"family": family, "cacheRoot": cache_root, "subdir": subdir or None},
    )


async def _handle_copy(args: dict[str, Any]) -> ToolResult:
    family = _infer_family(args["device"])
    if family == "unknown":
        return ToolResult.text(
            f'Cannot infer device family from "{args["device"]}".',
            is_error=True,
        )

    cache_root = _get_cache_root(family)
    if not cache_root:
        return ToolResult.text(f"No cached iLLD found for family {family}x.", is_error=True)

    workspace_root = ensure_directory(args.get("workspace") or os.getcwd())
    sources: list[str] = args["sources"]
    destination: str = args["destination"]

    resolved_sources, resolved_dest = _validate_and_resolve_paths(
        cache_root, workspace_root, sources, destination
    )

    total_files = 0
    copied_entries: list[str] = []
    for i, src in enumerate(resolved_sources):
        count = _copy_recursive(src, resolved_dest)
        total_files += count
        rel_dest = os.path.relpath(resolved_dest, workspace_root)
        copied_entries.append(f"{sources[i]} → {rel_dest} ({count} files)")

    return ToolResult(
        content=[TextContent(
            text=f"Copied {total_files} files from {family}x iLLD cache to workspace:\n"
                 + "\n".join(copied_entries),
        )],
        structured_content={"family": family, "totalFiles": total_files, "entries": copied_entries},
    )


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def _run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    try:
        args = _parse_input(args or {})
        if args["action"] == "list":
            return await _handle_list(args)
        return await _handle_copy(args)
    except Exception as error:  # noqa: BLE001
        return ToolResult.text(f"illd.provision error: {safe_error_message(error)}", is_error=True)



