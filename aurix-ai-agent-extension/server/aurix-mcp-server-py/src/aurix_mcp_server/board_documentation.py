"""Scoped, reviewed board facts exposed through documentation.search."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .board_pins import BOARD_ALIASES, normalize_board, resolve_board_pins, selected_board
from .documentation_retrieval import board_signal_facts, hardware_version_matches, search_results


BOARD_INDEX = Path(__file__).parent / "data" / "board_manuals" / "boards.sqlite"
SIGNAL_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:leds?\d*|buttons?\d*|[ds]\d+|reset|wake)(?![a-z0-9])"
    r"|P\d{1,2}\.\d{1,2}(?!\d)|\u6309\u94ae|\u6309\u952e|\u706f|\u590d\u4f4d|\u5524\u9192",
    re.IGNORECASE,
)
UNREVIEWED_PATTERN = re.compile(
    r"\b(?:voltage|current|resistors?|resistance|debounce|pull[- ]?ups?|pwm|frequency)\b"
    r"|\u7535\u538b|\u7535\u6d41|\u7535\u963b|\u6d88\u6296|\u4e0a\u62c9|\u9891\u7387",
    re.IGNORECASE,
)


def _board_in_text(text: str) -> str | None:
    upper = text.upper()
    boards = set(re.findall(r"\bKIT_[A-Z0-9]+(?:[_-][A-Z0-9]+)*", upper))
    for alias, board in BOARD_ALIASES.items():
        expression = r"(?<![A-Z0-9])" + r"[\s_-]+".join(map(re.escape, alias.split())) + r"(?![A-Z0-9])"
        if re.search(expression, upper):
            boards.add(board)
    if len(boards) > 1:
        raise ValueError("Board documentation query refers to multiple boards")
    return next(iter(boards), None)


def _hardware_version(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[vV]?\d+(?:\.\d+)*(?:\.[xX])?", value.strip()):
        raise ValueError("hardwareVersion must be an explicit hardware revision such as V2, not a document revision")
    return value.strip().lower().removeprefix("v")


def _signal_query(query: str, facts: list[dict]) -> str:
    explicit = re.findall(r"(?<![a-z0-9])(?:led|button|[ds])\s*\d+(?![a-z0-9])", query, re.IGNORECASE)
    ports = re.findall(r"P(\d{1,2})\.(\d{1,2})(?!\d)", query, re.IGNORECASE)
    terms = [re.sub(r"\s+", "", signal).upper() for signal in explicit]
    terms.extend(f"P{int(port):02d}.{int(pin)}" for port, pin in ports)
    terms.extend(f"BUTTON{number}" for number in re.findall(r"(?:\u6309\u94ae|\u6309\u952e)\s*(\d+)", query))
    terms.extend(f"LED{number}" for number in re.findall(r"\u706f\s*(\d+)", query))
    for fact in facts:
        for alias in fact.get("aliases", []):
            if re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", query, re.IGNORECASE):
                terms.append(fact["signal"])
    kinds = {
        "led": r"(?<![a-z0-9])leds?(?![a-z0-9])|\u706f",
        "button": r"(?<![a-z0-9])(?:push\s+)?buttons?(?![a-z0-9])|\u6309\u94ae|\u6309\u952e",
    }
    for kind, expression in kinds.items():
        signals = {fact["signal"] for fact in facts if fact.get("kind", "led" if fact["signal"].startswith("LED") else "button") == kind}
        prefixes = ("LED", "D") if kind == "led" else ("BUTTON", "S")
        if re.search(expression, query, re.IGNORECASE) and not any(term.startswith(prefixes) for term in terms):
            terms.extend(sorted(signals))
    return " ".join(dict.fromkeys(terms))


def board_evidence(args: dict[str, Any], query: str, top_k: int) -> dict[str, Any] | None:
    if not SIGNAL_PATTERN.search(query):
        return None
    chip_configuration = re.search(r"\b(?:gpio|registers?|padcfg\w*|gtm|egtm|pwm)\b", query, re.IGNORECASE)
    board_specific = re.search(
        r"(?:led|button|[ds])\s*\d+|reset|wake|polarity|active|\u590d\u4f4d|\u5524\u9192|\u6709\u6548\u7535\u5e73|\u6781\u6027", query, re.IGNORECASE,
    )
    if chip_configuration and not board_specific:
        return None
    query_board = _board_in_text(query)
    explicit_board = normalize_board(args.get("board"))
    device_board = _board_in_text(args.get("device") or "")
    requested = {value for value in (query_board, explicit_board, device_board) if value}
    if len(requested) > 1:
        raise ValueError("board, device and query refer to different boards")
    board = next(iter(requested), None)
    if board is None:
        board = selected_board(None, args.get("projectPath"))
    chips = set(re.findall(r"(?<![A-Z0-9])TC(?:\d{3}|4[A-Z]\d)(?![A-Z0-9])", (query + " " + (args.get("device") or "")).upper()))
    if board and chips and chips != set(re.findall(r"TC(?:\d{3}|4[A-Z]\d)", board)):
        if requested:
            raise ValueError("Selected board and requested device do not match")
        board = None
    hardware_version = _hardware_version(args.get("hardwareVersion"))
    query_versions = {version.lower() for version in re.findall(
        r"(?<![a-z0-9])(?:v|hw|hardware\s+version)\s*(\d+(?:\.\d+)*(?:\.x)?)(?![a-z0-9.])", query, re.IGNORECASE,
    )}
    if len(query_versions) > 1 or (hardware_version and query_versions and hardware_version not in query_versions):
        raise ValueError("hardwareVersion and query refer to different hardware revisions")
    hardware_version = hardware_version or next(iter(query_versions), None)
    pins = None
    if args.get("projectPath"):
        pins = resolve_board_pins(args["projectPath"], board)
        board = board or pins.get("board")
        if board and chips and chips != set(re.findall(r"TC(?:\d{3}|4[A-Z]\d)", board)):
            raise ValueError("Project BPL board and requested device do not match")
        declared_version = pins.get("hardwareVersion")
        if declared_version and hardware_version and not (
            hardware_version_matches(hardware_version, declared_version)
            or hardware_version_matches(declared_version, hardware_version)
        ):
            pins = {**pins, "status": "conflict", "reason": "BPL and requested hardware revisions differ"}
        elif declared_version and (not hardware_version or hardware_version.endswith(".x")):
            hardware_version = _hardware_version(declared_version)
    payload = {
        "scope": "board", "board": board, "hardwareVersion": hardware_version,
        "supportedFields": ["pin", "active_level"], "results": [],
        "requiresConfirmation": False,
    }
    if pins is not None:
        payload["boardPins"] = pins
    if not board:
        payload["reason"] = "specific_board_required"
        return payload
    if UNREVIEWED_PATTERN.search(query):
        payload["reason"] = "outside_reviewed_pin_and_active_level_scope"
        return payload
    if pins and pins["status"] in {"invalid", "conflict"}:
        payload["reason"] = "project_bpl_" + pins["status"]
        return payload
    database = Path(args["indexPath"]).expanduser().resolve() if args.get("indexPath") else BOARD_INDEX
    if not database.is_file():
        raise FileNotFoundError(f"Board documentation index not found: {database}")
    signal_query = _signal_query(query, board_signal_facts(database, board))
    results = search_results(
        database, signal_query, limit=top_k, board=board, hardware_version=hardware_version,
    ) if signal_query else []
    results = [result for result in results if result["citation"].get("board") == board]
    for result in results:
        non_gpio = any(fact.get("gpio") is False for fact in result["facts"])
        result["bplCheck"] = "not_checked" if pins is None else pins["status"]
        if non_gpio:
            result["usageRestriction"] = "not_a_gpio"
            result["bplCheck"] = "not_applicable"
        elif pins and pins["status"] != "detected":
            result["applicability"] = "bpl_verification_required"
        if not non_gpio and pins and pins["status"] == "detected":
            conflicts = []
            missing = []
            for fact in result["facts"]:
                labels = {label.upper() for label in [fact["signal"], *fact.get("aliases", [])]}
                matches = [pin for pin in pins["pins"] if labels.intersection(alias.upper() for alias in pin["aliases"])]
                if not matches:
                    missing.append(fact["signal"])
                elif any(pin["pin"] != fact["pin"] or "NC" in [alias.upper() for alias in pin["aliases"]] for pin in matches):
                    conflicts.append({"signal": fact["signal"], "manual_pin": fact["pin"], "bpl_pins": matches})
            if conflicts or not pins.get("board"):
                result["applicability"] = "pin_conflict" if conflicts else "board_identity_required"
                result["conflicts"] = conflicts
                result["facts"] = []
            elif missing:
                result["applicability"] = "bpl_mapping_required"
                result["missingSignals"] = missing
            result["bplCheck"] = "conflict" if conflicts else ("matched" if pins.get("board") else "board_identity_required")
            if missing and not conflicts:
                result["bplCheck"] = "not_mapped"
        result["usableForCodeGeneration"] = result["applicability"] == "matched" and not non_gpio
    payload["results"] = results
    payload["requiresConfirmation"] = any(not result["usableForCodeGeneration"] for result in results)
    if not results:
        payload["reason"] = "no_supported_board_evidence"
    return payload