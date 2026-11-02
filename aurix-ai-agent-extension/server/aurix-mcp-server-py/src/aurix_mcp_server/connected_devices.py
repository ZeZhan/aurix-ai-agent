"""Detect AURIX boards connected through DAS using ``AURIXFlasher -detect all``.

The flasher reports the board hardware revision of each connected kit, for example
``Connected device at id 1... [TC3x] TC37x DHACR2 | BoardHw: AURIX LITE KIT V2.0 (TC375) LK8PIMU6``.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
from typing import Any, Optional

from .context import load_workspace_context

DETECTION_ENVIRONMENT_VARIABLE = "AURIX_DEVICE_DETECTION"
CACHE_SECONDS = 30.0
DETECT_TIMEOUT_SECONDS = 15.0
# AURIXFlasher reports board hardware with "-detect all" from 3.1 on.
MIN_DETECT_VERSION = (3, 1)
LAST_FLASHER_FILE = os.path.join(os.path.expanduser("~"), ".aurix-agent", "detect-flasher.json")

_LINE = re.compile(
    r"Connected device at id\s+(?P<id>\d+)\.*\s*\[(?P<generation>[^\]]+)\]\s*(?P<family>\S+)\s+(?P<chip_id>\S+)"
    r"(?:\s*\|\s*BoardHw:\s*(?P<board_hw>.+?))?\s*$",
    re.IGNORECASE,
)
_BOARD_HW = re.compile(
    r"^(?P<kit>.+?)\s+V(?P<version>\d+(?:\.\d+)*)\s*(?:\((?P<part>TC\w+)\))?\s*(?P<serial>\S+)?$", re.IGNORECASE,
)
_MULTI_DEVICE_SUMMARY = re.compile(r"Detected\s+\d+\s+connected\s+device|Connected device at id\s+\d+", re.IGNORECASE)
# Printed by AURIXFlasher 3.x "-detect all" instead of the summary when no kit is connected.
_NO_DEVICES = re.compile(r"No connected devices found", re.IGNORECASE)
# The board ID of TC4x kits does not identify the kit revision: a TC4D7 lite Kit V2.1 reports
# "AURIX LITE KIT V1.0 (TC4D7)". Their board documentation is used for every revision instead.
TC4X_REVISION_NOTE = "not reported for TC4x kits; board documentation applies to every revision"
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
            if _revision_not_reported(device):
                device.update(hardwareVersion=None, hardwareVersionNote=TC4X_REVISION_NOTE)
        devices.append(device)
    return devices


def _revision_not_reported(device: dict[str, Any]) -> bool:
    return (device["part"] or "").startswith("TC4") or device["generation"].upper().startswith("TC4")


def _flasher_version(path: str) -> tuple[int, ...]:
    # The version is the tool directory name: ...\AurixFlasherSoftwareTool_v3.0.10\ or ...\AurixFlasherSoftwareTool\3.1.0.0\
    return tuple(int(part) for part in re.findall(r"\d+", os.path.basename(os.path.dirname(path))))


def _supports_detection(path: str) -> bool:
    version = _flasher_version(path)
    return not version or version >= MIN_DETECT_VERSION


def _remembered_flasher() -> Optional[str]:
    try:
        with open(LAST_FLASHER_FILE, "r", encoding="utf-8") as fh:
            path = json.load(fh).get("flasherPath")
    except (OSError, ValueError, AttributeError):
        return None
    return path if isinstance(path, str) and os.path.isfile(path) else None


def _remember_flasher(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(LAST_FLASHER_FILE), exist_ok=True)
        with open(LAST_FLASHER_FILE, "w", encoding="utf-8") as fh:
            json.dump({"flasherPath": path}, fh)
    except OSError:
        pass


def find_flashers() -> list[str]:
    """Flashers that can report boards (3.1+): last working one, configured studio's, then newest first.

    Each AURIXFlasher start costs several seconds, so versions known not to report boards are skipped.
    """
    from .tools.flash_program import _configured_studio_roots, _probe_known_flasher_locations

    context = load_workspace_context(None)
    preferred = _probe_known_flasher_locations(["AURIXFlasher.exe", "aurixflasher.exe"], _configured_studio_roots(context.data))
    found = {os.path.normcase(os.path.abspath(path)): os.path.abspath(path) for pattern in _FLASHER_GLOBS for path in glob.glob(pattern)}
    ordered = [_remembered_flasher(), preferred, *sorted(found.values(), key=_flasher_version, reverse=True)]
    candidates: list[str] = []
    for path in ordered:
        if path and _supports_detection(path) and all(os.path.normcase(path) != os.path.normcase(seen) for seen in candidates):
            candidates.append(path)
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
    if _NO_DEVICES.search(output) and not _MULTI_DEVICE_SUMMARY.search(output):
        return {"ok": True, "flasherPath": path, "devices": []}
    if not _MULTI_DEVICE_SUMMARY.search(output):
        banner = re.search(r"AURIX Flasher Software Tool\s+v?(\d+(?:\.\d+)+)", output, re.IGNORECASE)
        version = tuple(int(part) for part in banner[1].split(".")) if banner else _flasher_version(path)
        if version and version < MIN_DETECT_VERSION:
            # Flashers before 3.1 print a single "Connected to device..." line without board hardware.
            error = "this AURIXFlasher version does not report connected boards (3.1 or newer required)"
        else:
            tail = " | ".join(line.strip(" :") for line in output.strip().splitlines()[-4:] if line.strip())
            error = f"AURIXFlasher -detect all returned no device list: {tail or 'no output'}"
        return {"ok": False, "flasherPath": path, "devices": [], "error": error}
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
            if not flasher_path:
                _remember_flasher(path)
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
