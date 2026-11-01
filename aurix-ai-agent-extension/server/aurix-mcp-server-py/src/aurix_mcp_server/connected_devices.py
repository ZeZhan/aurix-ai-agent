"""Detect AURIX boards connected through DAS using ``AURIXFlasher -detect all``.

The flasher reports the board hardware revision of each connected kit, for example
``Connected device at id 1... [TC3x] TC37x DHACR2 | BoardHw: AURIX LITE KIT V2.0 (TC375) LK8PIMU6``.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import time
from typing import Any, Optional

from .context import load_workspace_context

DETECTION_ENVIRONMENT_VARIABLE = "AURIX_DEVICE_DETECTION"
CACHE_SECONDS = 30.0
DETECT_TIMEOUT_SECONDS = 15.0

_LINE = re.compile(
    r"Connected device at id\s+(?P<id>\d+)\.*\s*\[(?P<generation>[^\]]+)\]\s*(?P<family>\S+)\s+(?P<chip_id>\S+)"
    r"(?:\s*\|\s*BoardHw:\s*(?P<board_hw>.+?))?\s*$",
    re.IGNORECASE,
)
_BOARD_HW = re.compile(
    r"^(?P<kit>.+?)\s+V(?P<version>\d+(?:\.\d+)*)\s*(?:\((?P<part>TC\w+)\))?\s*(?P<serial>\S+)?$", re.IGNORECASE,
)
_MULTI_DEVICE_SUMMARY = re.compile(r"Detected\s+\d+\s+connected\s+device|Connected device at id\s+\d+", re.IGNORECASE)
_FLASHER_GLOBS = (
    "C:\\Infineon\\*\\eclipse\\plugins\\com.ifx.ads2.flash_*\\AurixFlasherSoftwareTool\\*\\AURIXFlasher.exe",
    "C:\\Infineon\\*\\plugins\\com.ifx.ads2.flash_*\\AurixFlasherSoftwareTool\\*\\AURIXFlasher.exe",
    "C:\\Infineon\\*\\eclipse\\plugins\\com.ifx.ads2.flash_*\\AurixFlasherSoftwareTool_*\\AURIXFlasher.exe",
    "C:\\Infineon\\*\\tools\\AurixFlasherSoftwareTool_*\\AURIXFlasher.exe",
)
# Board hardware name (as reported by the flasher) + part -> extension board ID.
_KIT_BOARDS = {
    ("AURIX LITE KIT", "TC375"): "KIT_A2G_TC375_LITE",
    ("AURIX LITE KIT", "TC334"): "KIT_A2G_TC334_LITE",
    ("AURIX LITE KIT", "TC4D7"): "KIT_A3G_TC4D7_LITE",
    ("AURIX LITE KIT", "TC275"): "KIT_AURIX_TC275_LITE",
}

_cache: dict[str, Any] = {}


def parse_detect_output(output: str) -> list[dict[str, Any]]:
    devices = []
    for raw in output.splitlines():
        match = _LINE.search(raw.strip().lstrip(":"))
        if not match:
            continue
        device: dict[str, Any] = {
            "id": int(match["id"]), "generation": match["generation"].strip(),
            "family": match["family"], "chipId": match["chip_id"],
            "boardHardware": (match["board_hw"] or "").strip() or None,
            "board": None, "hardwareVersion": None, "part": None, "serial": None,
        }
        board = _BOARD_HW.match(device["boardHardware"] or "")
        if board:
            part = (board["part"] or "").upper() or None
            device.update(
                hardwareVersion=board["version"], part=part, serial=board["serial"],
                board=_KIT_BOARDS.get((" ".join(board["kit"].upper().split()), part or "")),
            )
        devices.append(device)
    return devices


def find_flashers() -> list[str]:
    """Flasher candidates: the configured studio's first, then every installed one, newest version first."""
    from .tools.flash_program import _configured_studio_roots, _probe_known_flasher_locations

    context = load_workspace_context(None)
    preferred = _probe_known_flasher_locations(["AURIXFlasher.exe", "aurixflasher.exe"], _configured_studio_roots(context.data))
    found = {os.path.normcase(os.path.abspath(path)): os.path.abspath(path) for pattern in _FLASHER_GLOBS for path in glob.glob(pattern)}
    version = lambda path: tuple(int(part) for part in re.findall(r"\d+", os.path.basename(os.path.dirname(path))))
    candidates = sorted(found.values(), key=version, reverse=True)
    if preferred:
        candidates = [preferred] + [path for path in candidates if os.path.normcase(path) != os.path.normcase(preferred)]
    return candidates


def _run_detect(path: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [path, "-detect", "all"], cwd=os.path.dirname(path), capture_output=True,
            timeout=DETECT_TIMEOUT_SECONDS, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "flasherPath": path, "devices": [], "error": str(error)}
    output = completed.stdout.decode("utf-8", errors="replace") + completed.stderr.decode("utf-8", errors="replace")
    # Flashers before 3.1 print a single "Connected to device..." line without board hardware.
    if not _MULTI_DEVICE_SUMMARY.search(output):
        return {"ok": False, "flasherPath": path, "devices": [],
                "error": "this AURIXFlasher version does not report connected boards (3.1 or newer required)"}
    return {"ok": True, "flasherPath": path, "devices": parse_detect_output(output)}


def detect_connected_devices(flasher_path: Optional[str] = None, *, use_cache: bool = True) -> dict[str, Any]:
    """Run ``AURIXFlasher -detect all``; results are cached briefly because boards rarely change mid-task."""
    now = time.monotonic()
    if use_cache and _cache and now - _cache["at"] < CACHE_SECONDS and _cache["flasher"] == flasher_path:
        return _cache["result"]
    candidates = [flasher_path] if flasher_path else find_flashers()
    result: dict[str, Any] = {"ok": False, "devices": [], "error": "AURIXFlasher.exe not found"}
    for path in candidates:
        result = _run_detect(path)
        if result["ok"]:
            break
    _cache.update(at=now, flasher=flasher_path, result=result)
    return result


def detection_enabled() -> bool:
    return os.environ.get(DETECTION_ENVIRONMENT_VARIABLE, "").strip().lower() in {"1", "true", "yes", "on"}


def detected_hardware_version(board: Optional[str]) -> Optional[dict[str, Any]]:
    """Hardware revision of the single connected kit matching ``board``; None when absent or ambiguous."""
    if not board or not detection_enabled():
        return None
    matches = [device for device in detect_connected_devices()["devices"] if device["board"] == board]
    if len(matches) != 1 or not matches[0]["hardwareVersion"]:
        return None
    device = matches[0]
    return {
        "hardwareVersion": device["hardwareVersion"], "source": "AURIXFlasher -detect all",
        "boardHardware": device["boardHardware"], "deviceId": device["id"],
    }
