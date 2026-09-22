"""Read the release declared by the iLLD headers in a project."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

VERSION_HEADER = "IfxLldVersion.h"


def _read_version(header: Path) -> Optional[str]:
    try:
        text = header.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return None

    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.DOTALL)
    declarations = re.findall(
        r"^[ \t]*#[ \t]*define[ \t]+IFX_LLD_VERSION_([A-Z_]+)[ \t]+([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    declarations = [(name, value.strip()) for name, value in declarations if name != "H"]
    values: dict[str, str] = {}
    for name, value in declarations:
        literal = re.fullmatch(r"(?:(\d+)[uUlL]*|\([ \t]*(\d+)[uUlL]*[ \t]*\))", value)
        if literal is None:
            return None
        values[name] = str(int(literal.group(1) or literal.group(2)))
    parts = ("MAJOR", "MINOR", "PATCH" if "PATCH" in values else "REVISION")
    if len(declarations) != len(parts) or set(values) != set(parts):
        return None
    return ".".join(values[part] for part in parts)


def detect_illd_version(
    project_path: str, header_paths: Optional[list[str]] = None, *, scan_complete: bool = True,
) -> dict[str, Any]:
    root = Path(project_path)
    if header_paths is None:
        libraries = root / "Libraries"
        try:
            headers = list((libraries / "iLLD").rglob(VERSION_HEADER))
            if (libraries / VERSION_HEADER).is_file():
                headers.append(libraries / VERSION_HEADER)
            header_paths = [header.relative_to(root).as_posix() for header in headers]
        except OSError:
            header_paths = []

    sources = [
        {"path": relative_path, "version": _read_version(root / relative_path)}
        for relative_path in sorted(set(header_paths))
    ]
    versions = {source["version"] for source in sources if source["version"] is not None}
    if len(versions) > 1:
        status = "conflict"
    elif scan_complete and sources and all(source["version"] is not None for source in sources):
        status = "detected"
    else:
        status = "unknown"
    result = {
        "status": status,
        "version": next(iter(versions)) if status == "detected" else None,
        "sources": sources,
    }
    if not scan_complete:
        result["reason"] = "scan_limit"
    return result


def format_illd_version(result: dict[str, Any]) -> str:
    if result["status"] == "detected":
        return f"iLLD version: {result['version']} (declared in project headers)"
    if result["status"] == "conflict":
        versions = sorted({source["version"] for source in result["sources"] if source["version"]})
        return f"iLLD version: conflict ({', '.join(versions)}); check project headers"
    if result.get("reason") == "scan_limit":
        return "iLLD version: unknown (scan limit reached; increase maxFiles)"
    return "iLLD version: unknown (no consistent, readable version declaration)"