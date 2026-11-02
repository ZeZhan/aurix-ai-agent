"""Local copies of downloaded code examples, so importing an example again needs no network.

An entry holds exactly the manifest's files of one example and is only used when complete. Entries are
refreshed after MAX_AGE_SECONDS, so upstream fixes to an example still arrive.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from typing import Any, Optional

CACHE_ROOT = Path.home() / ".aurix-agent" / "example_cache"
ENVIRONMENT_VARIABLE = "AURIX_EXAMPLE_CACHE"
MAX_ENTRIES = 8
MAX_AGE_SECONDS = 30 * 24 * 3600
COPY_WORKERS = 8
COMPLETE_MARKER = ".complete"
TEMPORARY_PREFIX = ".tmp-"
STALE_TEMPORARY_SECONDS = 24 * 3600


def enabled() -> bool:
    return os.environ.get(ENVIRONMENT_VARIABLE, "1").strip().lower() not in {"0", "false", "no", "off"}


def _safe(relative: str) -> bool:
    path = PurePosixPath(relative)
    return bool(relative) and not path.is_absolute() and ".." not in path.parts and ":" not in relative


def entry_key(example_id: str, source: str, files: list[str]) -> Optional[str]:
    """Key for one example from one source revision and file list; None if the list cannot be cached safely."""
    if not files or not all(_safe(relative) for relative in files):
        return None
    digest = hashlib.sha256(json.dumps([source, sorted(files)], separators=(",", ":")).encode()).hexdigest()
    return f"{re.sub(r'[^A-Za-z0-9_.-]', '_', example_id)[:80]}-{digest[:16]}"


def _created(entry: Path) -> Optional[float]:
    try:
        return float(json.loads((entry / COMPLETE_MARKER).read_text(encoding="utf-8"))["created"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def lookup(key: str, files: list[str]) -> Optional[Path]:
    """The complete, fresh entry for ``key`` holding every file, or None."""
    entry = CACHE_ROOT / key
    created = _created(entry)
    if created is None or time.time() - created > MAX_AGE_SECONDS:
        return None
    if not all((entry / relative).is_file() for relative in files):
        return None
    return entry


def _copy_files(pairs: list[tuple[str, str]]) -> list[Optional[str]]:
    """Copy (source, destination) pairs; one error message or None per pair.

    Per-file latency (antivirus scanning of each new file) dominates, so files are copied in parallel:
    847 example files took about 3 s with eight workers instead of 8-28 s one by one.
    """
    def copy(pair: tuple[str, str]) -> Optional[str]:
        source, destination = pair
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            # copyfile, not copy2: copied files get the current time, as a download would.
            shutil.copyfile(source, destination)
            return None
        except OSError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=COPY_WORKERS, thread_name_prefix="aurix-example-cache") as pool:
        return list(pool.map(copy, pairs))


def copy_into(entry: Path, files: list[str], target: str, overwrite: bool) -> dict[str, Any]:
    """Copy an entry into a project with the same skip/overwrite rules as a download."""
    skipped: list[str] = []
    pending: list[str] = []
    for relative in files:
        if not overwrite and os.path.exists(os.path.join(target, *relative.split("/"))):
            skipped.append(relative)
        else:
            pending.append(relative)
    outcomes = _copy_files([
        (str(entry / relative), os.path.join(target, *relative.split("/"))) for relative in pending
    ])
    downloaded = [relative for relative, error in zip(pending, outcomes) if error is None]
    errors = [f"{relative}: {error}" for relative, error in zip(pending, outcomes) if error is not None]
    try:
        os.utime(entry / COMPLETE_MARKER)
    except OSError:
        pass
    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


def store(key: str, files: list[str], source: str) -> dict[str, Any]:
    """Keep a copy of freshly downloaded files; never affects the import itself."""
    entry = CACHE_ROOT / key
    temporary = CACHE_ROOT / f"{TEMPORARY_PREFIX}{key}-{uuid.uuid4().hex[:8]}"
    try:
        temporary.mkdir(parents=True)
        errors = [error for error in _copy_files([
            (os.path.join(source, *relative.split("/")), str(temporary / relative)) for relative in files
        ]) if error is not None]
        if errors:
            raise OSError(f"{len(errors)} file(s) not copied: {errors[0]}")
        # Written before the rename, so an entry is complete as soon as it exists.
        (temporary / COMPLETE_MARKER).write_text(
            json.dumps({"created": time.time(), "files": len(files)}), encoding="utf-8",
        )
        if entry.exists():
            shutil.rmtree(entry, ignore_errors=True)
        try:
            os.rename(temporary, entry)
        except OSError:
            if _created(entry) is None:
                raise
            # Another server stored the same example meanwhile.
        return {"status": "stored", "path": str(entry), "pruned": prune(keep=entry)}
    except Exception as error:
        return {"status": "store_failed", "reason": str(error)}
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def prune(keep: Optional[Path] = None) -> list[str]:
    """Keep the MAX_ENTRIES most recently used entries and drop abandoned temporary folders."""
    try:
        children = [path for path in CACHE_ROOT.iterdir() if path.is_dir()]
    except OSError:
        return []
    removed = []
    now = time.time()
    for path in children:
        if path.name.startswith(TEMPORARY_PREFIX):
            try:
                if now - path.stat().st_mtime > STALE_TEMPORARY_SECONDS:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass

    def last_used(path: Path) -> float:
        try:
            return (path / COMPLETE_MARKER).stat().st_mtime
        except OSError:
            return 0.0

    entries = sorted(
        (path for path in children if not path.name.startswith(TEMPORARY_PREFIX)), key=last_used, reverse=True,
    )
    for path in entries[MAX_ENTRIES:]:
        if keep is not None and path == keep:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed.append(path.name)
    return removed
