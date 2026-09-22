"""MCP tool: project.scan

Recursively scans a project directory and returns a structured inventory:
source files (.c), assembly (.S/.s/.src), include directories (containing .h),
linker scripts (.ld/.lsl), and detected device/toolchain hints.

Mirrors src/tools.scanProject.ts.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

from ..context import load_workspace_context, context_get
from ..illd_version import VERSION_HEADER, detect_illd_version, format_illd_version
from ..tooldef import ToolContext, ToolResult
from ..utils import safe_error_message

SOURCE_EXTENSIONS = {".c"}
ASM_EXTENSIONS = {".s", ".src"}  # .S handled case-insensitively
HEADER_EXTENSIONS = {".h"}
LINKER_EXTENSIONS = {".ld", ".lsl"}

ALWAYS_SKIP = {
    ".git", ".svn", ".hg", "node_modules", ".vscode", ".settings",
    ".metadata", "Debug", "Release", ".aurix-ai",
}

DEFAULT_MAX_FILES = 5000


def _scan_directory(
    root_dir: str,
    current_dir: str,
    exclude_set: set[str],
    c_sources: list[str],
    asm_sources: list[str],
    header_dirs: set[str],
    linker_scripts: list[str],
    max_files: int,
    counter: list[int],
    version_headers: list[str],
) -> None:
    if counter[0] >= max_files:
        return
    try:
        entries = list(os.scandir(current_dir))
    except OSError:
        return

    rel_dir = os.path.relpath(current_dir, root_dir).replace("\\", "/")
    if rel_dir == ".":
        rel_dir = ""

    for entry in entries:
        if counter[0] >= max_files:
            return

        if entry.is_dir():
            dir_name = entry.name
            if dir_name in ALWAYS_SKIP:
                continue
            rel_child_dir = f"{rel_dir}/{dir_name}" if rel_dir else dir_name
            if rel_child_dir in exclude_set or dir_name in exclude_set:
                continue
            excluded = False
            for ex in exclude_set:
                if rel_child_dir.startswith(ex + "/") or rel_child_dir == ex:
                    excluded = True
                    break
            if excluded:
                continue
            _scan_directory(
                root_dir, entry.path, exclude_set, c_sources, asm_sources,
                header_dirs, linker_scripts, max_files, counter, version_headers,
            )
        elif entry.is_file():
            ext = os.path.splitext(entry.name)[1].lower()
            rel_file = f"{rel_dir}/{entry.name}" if rel_dir else entry.name

            if ext in SOURCE_EXTENSIONS:
                c_sources.append(rel_file)
                counter[0] += 1
            elif ext in ASM_EXTENSIONS or entry.name.endswith(".S"):
                asm_sources.append(rel_file)
                counter[0] += 1
            elif ext in HEADER_EXTENSIONS:
                header_dirs.add(rel_dir or ".")
                counter[0] += 1
                if entry.name == VERSION_HEADER:
                    version_headers.append(rel_file)
            elif ext in LINKER_EXTENSIONS:
                linker_scripts.append(rel_file)
                counter[0] += 1


def _detect_device(c_sources: list[str], include_dirs: list[str]) -> tuple[str, str]:
    all_paths = c_sources + include_dirs
    illd_pattern = re.compile(r"(?:^|/)?iLLD/(TC\w+)/", re.IGNORECASE)

    illd_dirs: dict[str, int] = {}
    for p in all_paths:
        m = illd_pattern.search(p)
        if m:
            d = m.group(1)
            illd_dirs[d] = illd_dirs.get(d, 0) + 1

    if not illd_dirs:
        return "", ""

    best_dir = ""
    best_count = 0
    generic_re = re.compile(r"^TC[34]xx$", re.IGNORECASE)
    for d, count in illd_dirs.items():
        is_generic = bool(generic_re.match(d))
        current_is_generic = bool(generic_re.match(best_dir))
        if (not best_dir
                or (not is_generic and current_is_generic)
                or (count > best_count and is_generic == current_is_generic)):
            best_dir = d
            best_count = count

    code = best_dir.upper()
    device = ""
    if code.startswith("TC4"):
        device = "TC4xx"
    elif code.startswith("TC38"):
        device = "TC38x"
    elif code.startswith("TC39"):
        device = "TC39x"
    elif code.startswith("TC37"):
        device = "TC37x"
    elif code.startswith("TC36"):
        device = "TC36x"
    elif code.startswith("TC3"):
        device = "TC3xx"

    return device, best_dir


def _scan_project(project_path: str, exclude_dirs: list[str], max_files: int) -> dict[str, Any]:
    if not os.path.isdir(project_path):
        raise ValueError(f"Project path does not exist or is not a directory: {project_path}")

    exclude_set = {
        d.replace("\\", "/").rstrip("/") for d in exclude_dirs
    }
    c_sources: list[str] = []
    asm_sources: list[str] = []
    header_dirs: set[str] = set()
    linker_scripts: list[str] = []
    counter = [0]
    version_headers: list[str] = []

    _scan_directory(
        project_path, project_path, exclude_set, c_sources, asm_sources,
        header_dirs, linker_scripts, max_files, counter, version_headers,
    )

    c_sources.sort()
    asm_sources.sort()
    linker_scripts.sort()
    include_dirs = sorted(header_dirs)

    device, illd_dir = _detect_device(c_sources, include_dirs)

    return {
        "projectRoot": project_path,
        "cSources": c_sources,
        "asmSources": asm_sources,
        "includeDirs": include_dirs,
        "linkerScripts": linker_scripts,
        "detectedDevice": device,
        "detectedIlldDir": illd_dir,
        "illdVersion": detect_illd_version(
            project_path, version_headers, scan_complete=counter[0] < max_files,
        ),
        "excludedDirs": exclude_dirs,
        "stats": {
            "totalCFiles": len(c_sources),
            "totalAsmFiles": len(asm_sources),
            "totalIncludeDirs": len(include_dirs),
            "totalLinkerScripts": len(linker_scripts),
        },
    }


async def _run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    try:
        args = args or {}
        project_path_arg: Optional[str] = args.get("projectPath")
        context = load_workspace_context(project_path_arg)
        if project_path_arg and project_path_arg.strip():
            project_path = os.path.abspath(project_path_arg)
        else:
            ctx_workspace = context_get(context.data, "workspace")
            if ctx_workspace and str(ctx_workspace).strip():
                project_path = os.path.abspath(str(ctx_workspace))
            else:
                project_path = context.workspace_root

        exclude_dirs = [str(d) for d in args.get("excludeDirs", [])] if isinstance(args.get("excludeDirs"), list) else []
        max_files = int(args.get("maxFiles") or DEFAULT_MAX_FILES)

        result = _scan_project(project_path, exclude_dirs, max_files)

        stats = result["stats"]
        lines = [
            f"Project scan: {stats['totalCFiles']} C files, {stats['totalAsmFiles']} ASM files, "
            f"{stats['totalIncludeDirs']} include dirs, {stats['totalLinkerScripts']} linker scripts",
        ]
        if result["detectedDevice"]:
            lines.append(f"Detected device: {result['detectedDevice']} (iLLD dir: {result['detectedIlldDir']})")
        lines.append(format_illd_version(result["illdVersion"]))
        if result["excludedDirs"]:
            lines.append(f"Excluded: {', '.join(result['excludedDirs'])}")
        if result["linkerScripts"]:
            lines.append(f"Linker scripts: {', '.join(result['linkerScripts'])}")

        import json
        text = "\n".join(lines) + "\n\n" + json.dumps(result, indent=2)
        return ToolResult.text(text, structured={"scan": result})
    except Exception as error:  # noqa: BLE001
        return ToolResult.text(f"project.scan failed: {safe_error_message(error)}", is_error=True)



