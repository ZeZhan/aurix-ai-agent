"""MCP tool: flash.program

Program an ELF image via aurixflasher.exe (resolves device id via lsmcdd when
available). Also supports an arbitrary shell command mode.

Mirrors src/tools.flashProgram.ts.
"""

from __future__ import annotations

import asyncio
import csv
import glob
import io
import os
import re
import sys
from typing import Any, Optional

from ..context import context_get, load_workspace_context, resolve_workspace_root
from ..tooldef import TextContent, ToolContext, ToolResult
from ..utils import LimitedBuffer, ensure_directory, safe_error_message

DEFAULT_TIMEOUT_MS = 180_000


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def _parse_input(args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ValueError("flash.program requires an object argument")
    return args


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _resolve_image_path(workspace_root: str, image: str) -> str:
    replaced = image.replace("${workspaceFolder}", workspace_root).replace("${workspaceRoot}", workspace_root)
    return replaced if os.path.isabs(replaced) else os.path.abspath(os.path.join(workspace_root, replaced))


def _resolve_optional_path(workspace_root: str, value: Optional[str]) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    replaced = value.replace("${workspaceFolder}", workspace_root).replace("${workspaceRoot}", workspace_root)
    return replaced if os.path.isabs(replaced) else os.path.abspath(os.path.join(workspace_root, replaced))


def _first_existing_file(candidates: list[str]) -> Optional[str]:
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _autodiscover_image(workspace_root: str) -> Optional[str]:
    """Find the most recently built .elf when the caller did not pass one.

    Looks in <workspace>/build first (the ADS/MTB default output dir), then the
    workspace root, then recursively under build/. Returns the newest match.
    """
    candidates: list[str] = []
    for directory in (os.path.join(workspace_root, "build"), workspace_root):
        if not os.path.isdir(directory):
            continue
        try:
            for entry in os.scandir(directory):
                if entry.is_file() and entry.name.lower().endswith(".elf"):
                    candidates.append(entry.path)
        except OSError:
            continue
        if candidates:
            break
    if not candidates:
        build_dir = os.path.join(workspace_root, "build")
        if os.path.isdir(build_dir):
            candidates = glob.glob(os.path.join(build_dir, "**", "*.elf"), recursive=True)
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return os.path.abspath(candidates[0])


# ---------------------------------------------------------------------------
# Flasher/lsmcdd location probing
# ---------------------------------------------------------------------------

def _studio_tool_dir_globs(root: str) -> list[str]:
    return [
        os.path.join(root, "tools", "AurixFlasherSoftwareTool_*"),
        os.path.join(root, "eclipse", "plugins", "com.ifx.ads2.flash_*", "AurixFlasherSoftwareTool_*"),
        os.path.join(root, "plugins", "com.ifx.ads2.flash_*", "AurixFlasherSoftwareTool_*"),
        os.path.join(root, "plugins", "com.rt.hightec.tcf.agent.launcher_*"),
        os.path.join(root, "eclipse", "plugins", "com.rt.hightec.tcf.agent.launcher_*"),
        os.path.join(root, "tools", "*"),
        os.path.join(root, "tools"),
    ]


def _configured_studio_roots(context_data: Optional[dict[str, Any]]) -> list[str]:
    configured = (
        context_get(context_data, "toolchain", "adsStudioPath")
        or os.environ.get("AURIX_ADS_STUDIO_PATH")
        or os.environ.get("AURIX_IDE_PATH")
    )
    if not isinstance(configured, str) or not configured.strip():
        return []
    path = os.path.abspath(configured.strip())
    return [os.path.dirname(path) if os.path.isfile(path) else path]


def _probe_known_flasher_locations(
    file_names: list[str], preferred_roots: Optional[list[str]] = None
) -> Optional[str]:
    if sys.platform != "win32":
        return None

    # Prefer the IDE selected in extension settings/context. This avoids mixing
    # compiler and flasher versions when multiple Infineon studios are installed.
    tool_dir_globs: list[str] = []
    for root in preferred_roots or []:
        tool_dir_globs.extend(_studio_tool_dir_globs(root))

    # Fall back to AURIX IDE install trees under C:\Infineon:
    #    - AurixFlasher (AURIX Development Studio):   <root>\tools\AurixFlasherSoftwareTool_*\
    #    - AurixFlasher (AURIX Configuration Studio): <root>\eclipse\plugins\com.ifx.ads2.flash_*\AurixFlasherSoftwareTool_*\
    #    - lsmcdd (both studios): <root>[\eclipse]\plugins\com.rt.hightec.tcf.agent.launcher_*\res\
    tool_dir_globs.extend([
        "C:\\Infineon\\*\\tools\\AurixFlasherSoftwareTool_*",
        "C:\\Infineon\\*\\eclipse\\plugins\\com.ifx.ads2.flash_*\\AurixFlasherSoftwareTool_*",
        "C:\\Infineon\\*\\plugins\\com.rt.hightec.tcf.agent.launcher_*",
        "C:\\Infineon\\*\\eclipse\\plugins\\com.rt.hightec.tcf.agent.launcher_*",
        "C:\\Infineon\\*\\tools\\*",
        "C:\\Infineon\\*\\tools",
    ])
    for pattern in tool_dir_globs:
        for tool_dir in glob.glob(pattern):
            if not os.path.isdir(tool_dir):
                continue
            for sub in (".", "bin", "res"):
                for name in file_names:
                    candidate = os.path.join(tool_dir, sub, name)
                    if os.path.isfile(candidate):
                        return os.path.abspath(candidate)
    return None


# ---------------------------------------------------------------------------
# lsmcdd device enumeration
# ---------------------------------------------------------------------------

def _parse_csv_line(line: str) -> list[str]:
    """Parse a single CSV line (handles quoted fields)."""
    reader = csv.reader(io.StringIO(line))
    for row in reader:
        return [f.strip() for f in row]
    return []


async def _list_lsmcdd_devices(lsmcdd_path: str) -> list[dict[str, str]]:
    proc = await asyncio.create_subprocess_exec(
        lsmcdd_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise ValueError("lsmcdd timed out")

    output = (stdout_bytes or stderr_bytes or b"").decode("utf-8", errors="replace")
    devices: list[dict[str, str]] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fields = _parse_csv_line(line)
        dev_id = fields[0] if len(fields) > 0 else ""
        name = fields[1] if len(fields) > 1 else ""
        if dev_id and name:
            devices.append({"id": dev_id, "name": name})
    return devices


def _extract_part_number(device: str) -> Optional[str]:
    m = re.search(r"TC\d{3}", device, re.IGNORECASE)
    return m.group(0).upper() if m else None


async def _resolve_device_id(device: Optional[str], lsmcdd_path: str) -> Optional[str]:
    if not device or not device.strip():
        return None
    raw = device.strip()
    if re.fullmatch(r"\d+", raw):
        return raw

    devices = await _list_lsmcdd_devices(lsmcdd_path)
    raw_lower = raw.lower()

    # Exact match
    exact = next((d for d in devices if d["name"].lower() == raw_lower), None)
    if exact:
        return exact["id"]

    # Fuzzy by part number
    part = _extract_part_number(raw)
    if part:
        part_lower = part.lower()
        part_match = next((d for d in devices if part_lower in d["name"].lower()), None)
        if part_match:
            return part_match["id"]

    # Single device → use it
    if len(devices) == 1:
        return devices[0]["id"]

    available = ", ".join(d["name"] for d in devices)
    raise ValueError(f"Device '{raw}' not found in lsmcdd list. Available: {available}")


# ---------------------------------------------------------------------------
# Flash via shell command
# ---------------------------------------------------------------------------

async def _run_flash_command(
    workspace_root: str,
    args: dict[str, Any],
    timeout_ms: int,
    ctx: ToolContext,
) -> ToolResult:
    command = args["command"].strip()
    cwd = ensure_directory(_resolve_optional_path(workspace_root, args.get("cwd")) or workspace_root)

    stdout_buf = LimitedBuffer()
    stderr_buf = LimitedBuffer()
    timed_out = False

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def pump(stream: asyncio.StreamReader, buf: LimitedBuffer, kind: str) -> None:
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

    stdout = stdout_buf.text()
    stderr = stderr_buf.text()
    ok = (not timed_out) and exit_code == 0

    text = (
        f"flash.program command succeeded (exitCode={exit_code})"
        if ok else
        f"flash.program command failed (exitCode={exit_code}, timedOut={str(timed_out).lower()})"
    )

    return ToolResult(
        content=[TextContent(text=text)],
        is_error=not ok,
        structured_content={
            "ok": ok,
            "mode": "command",
            "command": command,
            "cwd": cwd,
            "timedOut": timed_out,
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
    )


# ---------------------------------------------------------------------------
# Flash via aurixflasher
# ---------------------------------------------------------------------------

async def _run_flash_aurixflasher(
    workspace_root: str,
    args: dict[str, Any],
    timeout_ms: int,
    ctx: ToolContext,
) -> ToolResult:
    image = args["image"].strip()
    image_path = _resolve_image_path(workspace_root, image)
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    context = load_workspace_context(args.get("workspace"))
    preferred_studio_roots = _configured_studio_roots(context.data)

    flasher_path = _first_existing_file([
        _resolve_optional_path(workspace_root, args.get("flasherPath")) or "",
        context_get(context.data, "toolchain", "flasherPath") or "",
        os.path.join(workspace_root, "bin", "aurixflasher", "aurixflasher.exe"),
        os.path.join(os.getcwd(), "bin", "aurixflasher", "aurixflasher.exe"),
    ]) or _probe_known_flasher_locations(
        ["AURIXFlasher.exe", "aurixflasher.exe"], preferred_studio_roots
    )
    if not flasher_path:
        raise FileNotFoundError(
            "aurixflasher.exe not found. Set flasherPath in input or context.toolchain.flasherPath"
        )

    lsmcdd_path = _first_existing_file([
        _resolve_optional_path(workspace_root, args.get("lsmcddPath")) or "",
        context_get(context.data, "toolchain", "lsmcddPath") or "",
        os.path.join(workspace_root, "bin", "lsmcdd.exe"),
        os.path.join(os.getcwd(), "bin", "lsmcdd.exe"),
    ]) or _probe_known_flasher_locations(["lsmcdd.exe"], preferred_studio_roots)

    device_name = (
        args.get("device")
        or context_get(context.data, "device", "name")
        or context_get(context.data, "debug", "targetDevice")
    )

    flasher_args: list[str] = []
    warnings: list[str] = []

    if device_name and lsmcdd_path:
        try:
            resolved_id = await _resolve_device_id(device_name, lsmcdd_path)
            if resolved_id:
                flasher_args.extend(["-id", resolved_id])
        except Exception as error:
            warnings.append(
                f"Device id lookup skipped: {safe_error_message(error)}. "
                "Falling back to aurixflasher -elf without -id."
            )
    elif device_name and re.fullmatch(r"\d+", device_name.strip()):
        flasher_args.extend(["-id", device_name.strip()])

    flasher_args.extend(["-elf", image_path])

    proc = await asyncio.create_subprocess_exec(
        flasher_path,
        *flasher_args,
        cwd=os.path.dirname(flasher_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    communicate_task = asyncio.create_task(proc.communicate())
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            asyncio.shield(communicate_task), timeout=timeout_ms / 1000
        )
    except asyncio.TimeoutError:
        timed_out = True
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        stdout_bytes, stderr_bytes = await communicate_task

    exit_code = None if timed_out else proc.returncode
    stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr_parts = [s for s in [
        (stderr_bytes or b"").decode("utf-8", errors="replace"),
        "flash.program timed out" if timed_out else "",
    ] if s.strip()]

    ok = exit_code == 0
    stderr_text = "\n".join([*warnings, *stderr_parts]).strip()

    text = (
        "flash.program completed successfully."
        if ok else
        f"flash.program failed with code {'null' if exit_code is None else exit_code}"
    )

    return ToolResult(
        content=[TextContent(text=text)],
        is_error=not ok,
        structured_content={
            "ok": ok,
            "mode": "aurixflasher",
            "workspaceRoot": workspace_root,
            "flasherPath": flasher_path,
            "imagePath": image_path,
            "args": flasher_args,
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr_text,
            "warnings": warnings,
        },
    )


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

async def _run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        args = _parse_input(args or {})
        context = load_workspace_context(args.get("workspace"))
        workspace_root = resolve_workspace_root(args.get("workspace") or context_get(context.data, "workspace"))

        timeout_ms_arg = args.get("timeoutMs")
        if isinstance(timeout_ms_arg, (int, float)) and timeout_ms_arg == timeout_ms_arg:
            timeout_ms = max(5000, int(timeout_ms_arg))
        else:
            timeout_ms = DEFAULT_TIMEOUT_MS

        if isinstance(args.get("command"), str) and args["command"].strip():
            return await _run_flash_command(workspace_root, args, timeout_ms, ctx)

        if not (isinstance(args.get("image"), str) and args["image"].strip()):
            discovered = _autodiscover_image(workspace_root)
            if not discovered:
                raise ValueError(
                    "flash.program requires image or command: no .elf found under "
                    f"{os.path.join(workspace_root, 'build')} or {workspace_root}. "
                    "Build the project first or pass image explicitly."
                )
            args["image"] = discovered

        return await _run_flash_aurixflasher(workspace_root, args, timeout_ms, ctx)
    except Exception as error:  # noqa: BLE001
        return ToolResult.text(f"flash.program error: {safe_error_message(error)}", is_error=True)



