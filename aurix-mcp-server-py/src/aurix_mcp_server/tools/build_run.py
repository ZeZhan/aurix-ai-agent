"""MCP tool: build.run

Run a project build command inside a workspace, auto-prepending the AURIX
toolchain (make + tricore-gcc) to PATH. Mirrors src/tools.buildRun.ts.
"""

from __future__ import annotations

import asyncio
import codecs
import glob
import os
import re
import tempfile
import time
from collections import deque
from typing import Any, Optional

from ..context import context_get, load_workspace_context
from ..tooldef import TextContent, ToolContext, ToolResult
from ..utils import ensure_directory

DEFAULT_BUILD_TIMEOUT_MS = 10 * 60 * 1000
DEFAULT_BUILD_COMMAND = "make --output-sync -j20 all"

TAIL_LINES = 120
MAX_ERROR_LINES = 200
MAX_WARNING_LINES = 20
SUCCESS_TAIL_LINES = 8
MAX_LINE_CHARS = 1000
MAX_TAIL_CHARS = 4000
MAX_ERROR_CHARS = 6000
MAX_WARNING_CHARS = 2000

_ERROR_RE = re.compile(
    r"(?i)(?:\berror\s*:|\*\*\*|undefined reference|no rule to make target"
    r"|ld(?:\.exe)? returned|recipe for target .* failed|cannot find)"
)
_WARNING_RE = re.compile(r"(?i)\bwarnings?\b")


class BuildLog:
    """Bounded diagnostic preview; complete streams are retained in log files."""

    def __init__(self) -> None:
        self._pending = ""
        self._tail: deque[str] = deque(maxlen=TAIL_LINES)
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.error_count = 0
        self.warning_count = 0
        self.line_count = 0
        self._text_truncated = False

    def feed(self, text: str) -> None:
        self._pending += text
        *complete, self._pending = self._pending.split("\n")
        for line in complete:
            self._add(line.rstrip("\r"))
        self._pending = self._limit_line(self._pending)

    def close(self) -> None:
        if self._pending:
            self._add(self._pending.rstrip("\r"))
            self._pending = ""

    def _limit_line(self, line: str) -> str:
        if len(line) > MAX_LINE_CHARS:
            self._text_truncated = True
            return line[:MAX_LINE_CHARS - 3] + "..."
        return line

    def _add(self, line: str) -> None:
        self.line_count += 1
        self._tail.append(self._limit_line(line))
        stripped = line.strip()
        if not stripped:
            return
        if _WARNING_RE.search(stripped):
            self.warning_count += 1
            preview = self._limit_line(stripped)
            if (len(self.warnings) < MAX_WARNING_LINES
                    and sum(map(len, self.warnings)) + len(preview) <= MAX_WARNING_CHARS):
                self.warnings.append(preview)
        elif _ERROR_RE.search(stripped):
            self.error_count += 1
            preview = self._limit_line(stripped)
            if (len(self.errors) < MAX_ERROR_LINES
                    and sum(map(len, self.errors)) + len(preview) <= MAX_ERROR_CHARS):
                self.errors.append(preview)

    @property
    def truncated(self) -> bool:
        return (self._text_truncated or self.line_count > len(self._tail)
                or len("\n".join(self._tail)) > MAX_TAIL_CHARS
                or self.error_count > len(self.errors)
                or self.warning_count > len(self.warnings))

    def tail_text(self, count: int = TAIL_LINES) -> str:
        return "\n".join(list(self._tail)[-count:])[-MAX_TAIL_CHARS:]


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

    stdout_log = BuildLog()
    stderr_log = BuildLog()
    log_files: dict[str, str] = {}
    log_file_errors: dict[str, str] = {}

    subprocess_factory = asyncio.create_subprocess_shell if shell else asyncio.create_subprocess_exec
    proc = await subprocess_factory(
        command, cwd=cwd, env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )

    async def pump(stream: asyncio.StreamReader, log: BuildLog,
                   kind: str) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        full_log = None
        try:
            try:
                full_log = tempfile.NamedTemporaryFile(
                    mode="wb", prefix=f"aurix-build-{kind}-", suffix=".log", delete=False,
                )
                log_files[kind] = full_log.name
            except OSError as error:
                log_file_errors[kind] = str(error)
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    log.feed(decoder.decode(b"", final=True))
                    break
                if full_log is not None and kind not in log_file_errors:
                    try:
                        full_log.write(chunk)
                    except OSError as error:
                        log_file_errors[kind] = str(error)
                text = decoder.decode(chunk)
                log.feed(text)
                try:
                    await ctx.send_progress(text, kind)  # type: ignore[arg-type]
                except Exception:
                    pass
        finally:
            if full_log is not None:
                try:
                    full_log.close()
                except OSError as error:
                    log_file_errors[kind] = str(error)

    pumps = asyncio.gather(
        pump(proc.stdout, stdout_log, "stdout"),  # type: ignore[arg-type]
        pump(proc.stderr, stderr_log, "stderr"),  # type: ignore[arg-type]
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
    stdout_log.close()
    stderr_log.close()
    ok = (not timed_out) and exit_code == 0

    errors = stderr_log.errors + stdout_log.errors
    warnings = stderr_log.warnings + stdout_log.warnings
    error_count = stderr_log.error_count + stdout_log.error_count
    warning_count = stderr_log.warning_count + stdout_log.warning_count
    tail_count = SUCCESS_TAIL_LINES if ok else TAIL_LINES
    stdout = stdout_log.tail_text(tail_count)
    stderr = stderr_log.tail_text(tail_count)
    log_truncated = (stdout_log.truncated or stderr_log.truncated
                     or stdout_log.line_count > tail_count or stderr_log.line_count > tail_count)

    headline = (
        f"build.run succeeded (exitCode={exit_code}, durationMs={duration_ms})"
        if ok else
        f"build.run failed (exitCode={exit_code}, timedOut={str(timed_out).lower()}, durationMs={duration_ms})"
    )
    sections = [headline]
    if ok:
        sections.append(stdout)
    else:
        if errors:
            shown = errors[:MAX_WARNING_LINES]
            sections.append(f"Errors ({error_count} line(s), showing {len(shown)}):")
            sections.extend(shown)
        for kind, tail in (("stdout", stdout), ("stderr", stderr)):
            if tail:
                sections.append(f"--- {kind} tail ---\n{tail}")
    if warning_count:
        sections.append(f"Warnings ({warning_count} line(s), showing {len(warnings[:5])}):")
        sections.extend(warnings[:5])
    if log_truncated:
        sections.append("Output preview truncated; read logFiles for complete diagnostic context.")
    for kind, path in log_files.items():
        sections.append(f"{kind} log: {path}")
    for kind, error in log_file_errors.items():
        sections.append(f"{kind} full log unavailable or incomplete: {error}")
    text = "\n".join(section for section in sections if section)

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
            "errorCount": error_count,
            "warningCount": warning_count,
            "errors": errors,
            "warnings": warnings,
            "logTruncated": log_truncated,
            "logFiles": log_files,
            "logFileErrors": log_file_errors,
            "stdout": stdout,
            "stderr": stderr,
        },
    )



