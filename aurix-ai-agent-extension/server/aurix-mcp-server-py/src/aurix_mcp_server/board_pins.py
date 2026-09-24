"""Project-local board pin labels, without inferred electrical properties."""

from __future__ import annotations

import csv
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from .context import context_get, load_workspace_context


BPL_FILENAME = "board_pin_label.bpl"
MAX_BPL_BYTES = 1024 * 1024
BOARD_ALIASES = {
    "TC375 LK": "KIT_A2G_TC375_LITE",
    "TC375 LITE": "KIT_A2G_TC375_LITE",
    "TC375 LITE KIT": "KIT_A2G_TC375_LITE",
    "AURIX TC375 LITE KIT": "KIT_A2G_TC375_LITE",
    "TC4D7 LK": "KIT_A3G_TC4D7_LITE",
    "TC4D7 LITE": "KIT_A3G_TC4D7_LITE",
    "TC4D7 LITE KIT": "KIT_A3G_TC4D7_LITE",
    "AURIX TC4D7 LITE KIT": "KIT_A3G_TC4D7_LITE",
    "TC397 5V TFT": "KIT_A2G_TC397_5V_TFT",
    "TC397 5V TFT KIT": "KIT_A2G_TC397_5V_TFT",
}


def normalize_board(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("board must be a board ID or name")
    cleaned = " ".join(value.strip().upper().split())
    if not cleaned:
        return None
    if cleaned in BOARD_ALIASES:
        return BOARD_ALIASES[cleaned]
    if not re.fullmatch(r"KIT_[A-Z0-9]+(?:[_-][A-Z0-9]+)*", cleaned):
        raise ValueError("board requires a specific KIT_ board ID, not just a device")
    return cleaned


def read_bpl(path: str | Path, *, source_kind: str = "project") -> dict[str, Any]:
    path = Path(path)
    result: dict[str, Any] = {
        "status": "invalid",
        "board": None,
        "boardName": None,
        "hardwareVersion": None,
        "device": None,
        "package": None,
        "declaredPinCount": None,
        "totalPins": 0,
        "pins": [],
        "warnings": [],
        "source": {"path": str(path.resolve()), "kind": source_kind},
        "electricalProperties": "not_provided",
    }
    try:
        with path.open("rb") as source:
            data = source.read(MAX_BPL_BYTES + 1)
        if len(data) > MAX_BPL_BYTES:
            raise ValueError("BPL exceeds the 1 MiB size limit")
        result["source"]["sha256"] = hashlib.sha256(data).hexdigest()
        text = data.decode("utf-8-sig")
        positions: set[str] = set()
        for line_number, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("//"):
                comment = line[2:].strip()
                device = re.fullmatch(
                    r"Device:\s*([^,]+),\s*Package:\s*([^,]+),\s*Pin number:\s*(\d+)",
                    comment, re.IGNORECASE,
                )
                if device:
                    result.update(device=device[1].strip(), package=device[2].strip(), declaredPinCount=int(device[3]))
                elif not comment.lower().startswith("generated with"):
                    board_id = re.search(r"\bKIT_[A-Z0-9]+(?:[_-][A-Z0-9]+)*", comment, re.IGNORECASE)
                    board_name = re.sub(r"\s+V\d+(?:\.[\dX]+)*\s*$", "", comment, flags=re.IGNORECASE)
                    declared_board = board_id[0].upper() if board_id else BOARD_ALIASES.get(board_name.upper())
                    if declared_board:
                        if result["board"] and result["board"] != declared_board:
                            raise ValueError("BPL declares multiple boards")
                        result["board"] = declared_board
                    if declared_board or "kit" in comment.casefold() or "board" in comment.casefold():
                        result["boardName"] = comment
                        revision = re.search(r"\bV(\d+(?:\.[\dX]+)*)\b", comment, re.IGNORECASE)
                        result["hardwareVersion"] = revision[1] if revision else None
                continue
            fields = next(csv.reader([line], skipinitialspace=True, strict=True))
            if len(fields) != 2:
                raise ValueError(f"Line {line_number}: expected position and pin labels")
            position, labels = (field.strip() for field in fields)
            position = position.upper()
            if not re.fullmatch(r"(?:[A-Z]{1,2})?[1-9]\d*", position) or position in positions:
                raise ValueError(f"Line {line_number}: invalid or duplicate pin position")
            aliases = [label.strip() for label in labels.split("/")]
            if not all(aliases):
                raise ValueError(f"Line {line_number}: empty pin label")
            positions.add(position)
            pin = aliases[0]
            gpio = re.fullmatch(r"P(\d{1,2})\.(\d{1,2})", pin, re.IGNORECASE)
            if gpio:
                pin = f"P{int(gpio[1]):02d}.{int(gpio[2])}"
            if len(aliases) > 1:
                result["pins"].append({
                    "position": position, "pin": pin, "aliases": aliases[1:],
                    "line": line_number, "raw": raw,
                })
        if not positions:
            raise ValueError("BPL contains no pin records")
        result["totalPins"] = len(positions)
        if result["declaredPinCount"] is not None and result["declaredPinCount"] != len(positions):
            result["warnings"].append("Record count differs from declared pin count; extra package pads may be included")
        result["status"] = "detected"
    except (OSError, UnicodeError, ValueError, csv.Error) as error:
        result["pins"] = []
        result["reason"] = str(error)
    return result


def selected_board(board: str | None, project_path: str | None = None, device: str | None = None) -> str | None:
    if board is not None:
        return normalize_board(board)
    if device and (device.upper().startswith("KIT_") or device.upper() in BOARD_ALIASES):
        return normalize_board(device)
    context = load_workspace_context(project_path)
    configured = context_get(context.data, "board")
    if configured:
        return normalize_board(configured)
    candidate = context_get(context.data, "device") or os.environ.get("AURIX_SELECTED_DEVICE", "")
    if isinstance(candidate, str) and (candidate.upper().startswith("KIT_") or candidate.upper() in BOARD_ALIASES):
        return normalize_board(candidate)
    return None


def _version_key(path: Path) -> tuple:
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in re.split(r"(\d+)", path.name))


def find_installed_bpl(studio_dir: str, board: str) -> Path | None:
    board = normalize_board(board)
    if board is None:
        return None
    studio = Path(studio_dir).resolve()
    for base in (studio, studio.parent):
        pack = base / "libstore/DeviceFeatures/pack"
        roots = sorted((path for path in pack.glob("*") if path.is_dir()), key=_version_key, reverse=True)
        initializer = base / "build_system/bundled-artefacts-repo/project-initializer"
        for family in sorted(initializer.glob("tricore-*")):
            roots.extend(sorted((path for path in family.glob("*") if path.is_dir()), key=_version_key, reverse=True))
        for root in roots:
            bsp = root / "BSP"
            for candidate in bsp.glob("*/board_pin_label.bpl"):
                if candidate.parent.name.upper() == board:
                    return candidate
    return None


def resolve_board_pins(
    project_path: str | None, board: str | None = None, studio_dir: str | None = None,
) -> dict[str, Any]:
    board = normalize_board(board)
    path = Path(project_path) / BPL_FILENAME if project_path else None
    source_kind = "project"
    if path is None or not path.exists():
        if board is None:
            return {"status": "not_found", "requestedBoard": None, "pins": [], "reason": "No project BPL; select a specific board for installation lookup"}
        source_kind = "installation"
        try:
            if studio_dir is None:
                from .tools.ads_create_project import resolve_studio_dir

                studio_dir = resolve_studio_dir(project_path)
            path = find_installed_bpl(studio_dir, board)
        except (OSError, ValueError) as error:
            return {"status": "unavailable", "requestedBoard": board, "pins": [], "reason": str(error)}
        if path is None:
            return {"status": "not_found", "requestedBoard": board, "pins": [], "reason": "No matching BSP board_pin_label.bpl in the selected ADS/ACS installation"}
    result = read_bpl(path, source_kind=source_kind)
    result["requestedBoard"] = board
    if result["status"] != "detected":
        return result
    if result["board"] and board and result["board"] != board:
        result.update(status="conflict", pins=[], reason="BPL declares a different board; no fallback was used")
        return result
    if source_kind == "installation":
        result["board"] = board
        result["boardIdentitySource"] = "bsp_directory"
    elif result["board"]:
        result["boardIdentitySource"] = "file_header"
    else:
        result["boardIdentitySource"] = "unknown"
        result["warnings"].append("Project BPL board identity could not be verified; labels are project declarations, not confirmed hardware wiring")
    return result


def deploy_board_pins(workspace: str, board: str | None, studio_dir: str) -> dict[str, Any]:
    result = resolve_board_pins(workspace, board, studio_dir)
    result["deployment"] = "not_copied"
    if result.get("source", {}).get("kind") == "project":
        result["deployment"] = "preserved"
    elif result["status"] == "detected":
        source_path = Path(result["source"]["path"])
        try:
            data = source_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != result["source"]["sha256"]:
                raise ValueError("BPL source changed before deployment")
            with (Path(workspace) / BPL_FILENAME).open("xb") as target:
                target.write(data)
        except FileExistsError:
            result = resolve_board_pins(workspace, board, studio_dir)
            result["deployment"] = "preserved"
        except (OSError, ValueError) as error:
            result.update(status="unavailable", pins=[], reason=str(error))
        else:
            origin = result["source"]
            result = resolve_board_pins(workspace, board, studio_dir)
            result["source"]["copiedFrom"] = origin["path"]
            result["board"] = board
            result["boardIdentitySource"] = "bsp_directory"
            result["deployment"] = "copied"
    return result


def format_board_pins(result: dict[str, Any]) -> str:
    if result["status"] != "detected":
        return f"Board pin labels: {result['status']} ({result.get('reason', 'no evidence')})"
    source = result["source"]
    return (
        f"Board pin labels: {result.get('board') or 'unverified board'}, "
        f"{len(result['pins'])} annotated pins ({source['kind']}: {source['path']}); "
        "electrical properties are not provided by BPL"
    )