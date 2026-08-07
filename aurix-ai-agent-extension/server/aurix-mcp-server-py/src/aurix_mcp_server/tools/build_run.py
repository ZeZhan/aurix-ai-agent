"""MCP tool: build.run

Run a project build command inside a workspace, auto-prepending the AURIX
toolchain (make + tricore-gcc) to PATH. Mirrors src/tools.buildRun.ts.
"""

from __future__ import annotations

import asyncio
import glob
import os
import re
import time
from typing import Any, Optional

from ..context import context_get, load_workspace_context
from ..tooldef import TextContent, ToolContext, ToolResult
from ..utils import LimitedBuffer, ensure_directory

DEFAULT_BUILD_TIMEOUT_MS = 10 * 60 * 1000
DEFAULT_BUILD_COMMAND = "make --output-sync -j20 all"


def _normalize_build_command(command: str, fallback: str = DEFAULT_BUILD_COMMAND) -> str:
    trimmed = command.strip()
    if re.fullmatch(r"build(?:\s+project)?", trimmed, re.IGNORECASE):
        return fallback
    if (re.match(r"^(?:make|mingw32-make|gmake)(?:\.exe)?(?:\s|$)", trimmed, re.IGNORECASE)
            and not re.search(r"(?:^|\s)all(?:\s|$)", trimmed, re.IGNORECASE)):
        return f"{trimmed} all"
    return trimmed


def _resolve_build_cwd(workspace_root: str, cwd: Optional[str]) -> str:
    if not isinstance(cwd, str) or cwd.strip() == "":
        return workspace_root
    resolved = cwd if os.path.isabs(cwd) else os.path.join(workspace_root, cwd)
    return ensure_directory(resolved)


def _find_tricore_gcc_bin(root: str) -> Optional[str]:
    """Locate a tricore-gcc*/bin dir for either ADS or Configuration Studio layout.

    - ADS:                   <root>\\tools\\Compilers\\tricore-gcc*\\bin
    - Configuration Studio:  <root>\\eclipse\\tricore-gcc*\\bin
    - generic:               <root>\\tricore-gcc*\\bin
    """
    parents = [
        os.path.join(root, "tools", "Compilers"),
        os.path.join(root, "eclipse"),
        root,
    ]
    for parent in parents:
        if not os.path.isdir(parent):
            continue
        try:
            gcc_dirs = sorted(
                (d for d in os.listdir(parent) if d.startswith("tricore-gcc")),
                reverse=True,
            )
        except OSError:
            continue
        for d in gcc_dirs:
            bin_dir = os.path.join(parent, d, "bin")
            if os.path.isdir(bin_dir):
                return bin_dir
    return None


def _find_make_dir(root: str) -> Optional[str]:
    """Locate the directory containing make.exe for ADS or Configuration Studio.

    - ADS:                   <root>\\tools\\make\\make.exe
    - Configuration Studio:  <root>\\eclipse\\tools\\make.exe
    """
    for make_dir in (
        os.path.join(root, "tools", "make"),
        os.path.join(root, "eclipse", "tools"),
        os.path.join(root, "tools"),
    ):
        if os.path.isfile(os.path.join(make_dir, "make.exe")):
            return make_dir
    return None


def _detect_toolchain_paths(workspace: Optional[str]) -> list[str]:
    ctx = load_workspace_context(workspace)
    ads_path = (
        context_get(ctx.data, "toolchain", "adsStudioPath")
        or os.environ.get("AURIX_ADS_STUDIO_PATH")
        or os.environ.get("AURIX_IDE_PATH")
    )

    candidates: list[str] = []
    if ads_path:
        p = os.path.abspath(ads_path)
        candidates.append(os.path.dirname(p) if os.path.isfile(p) else p)
    candidates.extend([
        "C:\\Infineon\\ide",
        "C:\\Infineon\\AURIX-Studio",
        os.path.join(os.path.expanduser("~"), "AURIX-Studio"),
    ])
    # Versioned AURIX IDE installs under C:\Infineon (ADS + Configuration Studio).
    for pattern in (
        "C:\\Infineon\\AURIX-Studio*",
        "C:\\Infineon\\AURIX-Configuration-Studio*",
    ):
        candidates.extend(sorted(glob.glob(pattern), reverse=True))

    # Prefer a single install that provides the compiler and take make from the
    # same root so the two halves stay consistent. Fall back to a make-only root.
    fallback: list[str] = []
    seen: set[str] = set()
    for root in candidates:
        norm = os.path.normcase(os.path.abspath(root)) if root else ""
        if not root or norm in seen or not os.path.isdir(root):
            continue
        seen.add(norm)
        gcc_dir = _find_tricore_gcc_bin(root)
        make_dir = _find_make_dir(root)
        if gcc_dir:
            detected: list[str] = []
            if make_dir:
                detected.append(make_dir)
            detected.append(gcc_dir)
            return detected
        if make_dir and not fallback:
            fallback = [make_dir]
    return fallback


def _build_path_env(
    path_additions: Optional[list[str]], workspace: Optional[str]
) -> tuple[dict[str, str], list[str]]:
    normalized = [v.strip() for v in path_additions if v.strip()] if isinstance(path_additions, list) else []

    if not normalized:
        normalized = _detect_toolchain_paths(workspace)

    env = dict(os.environ)
    if not normalized:
        return env, []

    current_path = os.environ.get("PATH") or os.environ.get("Path") or ""
    parts = [p for p in (normalized + [current_path]) if p]
    env["PATH"] = os.pathsep.join(parts)
    return env, normalized


async def _run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if not isinstance(args, dict):
        raise ValueError("build.run requires an object argument")

    workspace_arg = args.get("workspace")
    context = load_workspace_context(workspace_arg)
    workspace_candidate = workspace_arg or context_get(context.data, "workspace") or os.getcwd()
    workspace_root = ensure_directory(workspace_candidate)
    cwd = _resolve_build_cwd(workspace_root, args.get("cwd"))

    command_arg = args.get("command")
    ctx_command = context_get(context.data, "toolchain", "buildCommand")
    ctx_command = ctx_command.strip() if isinstance(ctx_command, str) else ""
    default_command = _normalize_build_command(ctx_command or DEFAULT_BUILD_COMMAND)
    if isinstance(command_arg, str) and command_arg.strip():
        command = _normalize_build_command(command_arg, default_command)
    else:
        command = default_command

    timeout_ms_arg = args.get("timeoutMs")
    if isinstance(timeout_ms_arg, (int, float)) and timeout_ms_arg == timeout_ms_arg:  # not NaN
        timeout_ms = max(1000, int(timeout_ms_arg))
    else:
        timeout_ms = DEFAULT_BUILD_TIMEOUT_MS

    path_additions = args.get("pathAdditions")
    env, effective_path_additions = _build_path_env(path_additions, workspace_root)
    shell = args.get("shell") if isinstance(args.get("shell"), bool) else True

    started_at = time.monotonic()
    timed_out = False

    stdout_buf = LimitedBuffer()
    stderr_buf = LimitedBuffer()

    subprocess_factory = asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    proc = await subprocess_factory(
        command, cwd=cwd, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    async def pump(stream: asyncio.StreamReader, buf: LimitedBuffer,
                   kind: str) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            buf.append(chunk)
            try:
                await ctx.send_progress(chunk.decode("utf-8", errors="replace"), kind)  # type: ignore[arg-type]
            except Exception:
                pass

    pumps = asyncio.gather(
        pump(proc.stdout, stdout_buf, "stdout"),  # type: ignore[arg-type]
        pump(proc.stderr, stderr_buf, "stderr"),  # type: ignore[arg-type]
    )

    exit_code: Optional[int]
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_ms / 1000)
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        exit_code = proc.returncode

    try:
        await pumps
    except Exception:
        pass

    duration_ms = int((time.monotonic() - started_at) * 1000)
    stdout = stdout_buf.text()
    stderr = stderr_buf.text()
    ok = (not timed_out) and exit_code == 0

    text = (
        f"build.run succeeded (exitCode={exit_code}, durationMs={duration_ms})"
        if ok else
        f"build.run failed (exitCode={exit_code}, timedOut={str(timed_out).lower()}, durationMs={duration_ms})"
    )

    return ToolResult(
        content=[TextContent(text=text)],
        is_error=not ok,
        structured_content={
            "ok": ok,
            "command": command,
            "workspaceRoot": workspace_root,
            "cwd": cwd,
            "pathAdditions": effective_path_additions,
            "timeoutMs": timeout_ms,
            "timedOut": timed_out,
            "exitCode": exit_code,
            "durationMs": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
        },
    )



