"""Reuse compiled iLLD and configuration objects across projects with identical inputs.

A fresh project spends minutes compiling the same ~200 iLLD sources (on Windows mostly
process start-up). The objects depend only on the toolchain, the compile settings in the
generated Makefile and the content of the iLLD/configuration sources and headers, so they
are compiled once per distinct combination in ``~/.aurix-agent/build_cache/<key>`` and
copied into the project's empty ``build/`` directory. The key is a content hash: a new
extension version, IDE, compiler, flag or source change always selects a different entry,
and any failure falls back to a normal full build.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

CACHE_FORMAT = "1"
CACHE_ROOT = Path.home() / ".aurix-agent" / "build_cache"
MAX_ENTRIES = 4
CACHE_TARGET = "illd-objs"
ENVIRONMENT_VARIABLE = "AURIX_BUILD_CACHE"
CACHED_TREES = ("Libraries", "Configurations")
HEADER_SUFFIXES = {".h", ".inc"}
SOURCE_SUFFIXES = {".c", ".h", ".inc", ".s", ".S"}
SKIPPED_DIRS = {"build", ".git", ".vscode", ".github", ".settings", ".ads", "node_modules"}
COMPLETE_MARKER = ".complete"
LAST_USED_MARKER = ".last_used"
DEPENDENCY_MANIFEST = "external-dependencies.json"
STALE_SECONDS = 24 * 3600


def enabled() -> bool:
    return os.environ.get(ENVIRONMENT_VARIABLE, "1").strip().lower() not in {"0", "false", "no", "off"}


def _logical_lines(text: str) -> list[str]:
    return re.sub(r"\\\r?\n", " ", text).splitlines()


def _makefile_settings(makefile: str) -> Optional[str]:
    """Makefile content that affects library objects, or None for Makefiles without the cache target."""
    lines = _logical_lines(makefile)
    if not any(line.startswith(f"{CACHE_TARGET}:") for line in lines):
        return None
    # Application sources do not affect library objects; keep them out of the key.
    kept = [line for line in lines if not re.match(r"\s*(?:USER_SRCS|EXTRA_SRCS)\s*[:+]?=", line)]
    return "\n".join(kept)


def _compiler_identity(makefile: str) -> Optional[str]:
    match = re.search(r"^CROSS_COMPILE\s*[:]?=\s*(\S+)\s*$", makefile, re.MULTILINE)
    if not match:
        return None
    for candidate in (match.group(1) + "gcc.exe", match.group(1) + "gcc"):
        if os.path.isfile(candidate):
            stat = os.stat(candidate)
            return f"{os.path.normcase(os.path.abspath(candidate))}|{stat.st_size}|{int(stat.st_mtime)}"
    return None


def _walk(root: Path) -> list[Path]:
    files = []
    for directory, subdirs, names in os.walk(root):
        relative = Path(directory).relative_to(root)
        if relative == Path("."):
            subdirs[:] = [name for name in subdirs if name not in SKIPPED_DIRS]
        files.extend(relative / name for name in names)
    return sorted(files, key=lambda path: path.as_posix())


def _in_tree(relative: Path) -> bool:
    return bool(relative.parts) and relative.parts[0] in CACHED_TREES


def _tree_files(files: list[Path]) -> list[Path]:
    return [path for path in files if _in_tree(path) and path.suffix in SOURCE_SUFFIXES]


def _outside_headers(files: list[Path]) -> list[Path]:
    return [path for path in files if not _in_tree(path) and path.suffix in HEADER_SUFFIXES]


def _shadowing_headers(files: list[Path]) -> list[Path]:
    """Project headers outside the cached trees that could shadow an iLLD header of the same name."""
    tree_names = {path.name.lower() for path in _tree_files(files) if path.suffix in HEADER_SUFFIXES}
    return [path for path in _outside_headers(files) if path.name.lower() in tree_names]


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(project: str | os.PathLike[str]) -> Optional[str]:
    root = Path(project)
    makefile_path = root / "Makefile"
    if not makefile_path.is_file():
        return None
    makefile = makefile_path.read_text(encoding="utf-8", errors="replace")
    settings = _makefile_settings(makefile)
    compiler = _compiler_identity(makefile)
    if settings is None or compiler is None:
        return None
    files = _walk(root)
    digest = hashlib.sha256()
    for part in (CACHE_FORMAT, compiler, settings):
        digest.update(part.encode("utf-8") + b"\0")
    for relative in _tree_files(files) + _shadowing_headers(files):
        digest.update(relative.as_posix().encode("utf-8") + b"\0")
        digest.update(bytes.fromhex(_hash_file(root / relative)))
    return digest.hexdigest()[:32]


def _copy_inputs(project: Path, destination: Path) -> None:
    shutil.copy2(project / "Makefile", destination / "Makefile")
    files = _walk(project)
    for relative in _tree_files(files) + _outside_headers(files):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / relative, target)


def _external_dependencies(source: Path) -> dict[str, str]:
    """Headers outside the cached trees that library objects actually include, with content hashes."""
    dependencies: set[str] = set()
    for dep_file in (source / "build").rglob("*.d"):
        text = dep_file.read_text(encoding="utf-8", errors="replace").replace("\\\n", " ")
        for token in text.split():
            if token.endswith(":") or os.path.isabs(token):
                continue
            relative = Path(token)
            if not _in_tree(relative):
                dependencies.add(relative.as_posix())
    return {path: _hash_file(source / path) for path in sorted(dependencies) if (source / path).is_file()}


def _entries() -> list[Path]:
    if not CACHE_ROOT.is_dir():
        return []
    return [path for path in CACHE_ROOT.iterdir() if (path / COMPLETE_MARKER).is_file()]


def _last_used(entry: Path) -> float:
    marker = entry / LAST_USED_MARKER
    return marker.stat().st_mtime if marker.exists() else (entry / COMPLETE_MARKER).stat().st_mtime


def prune(keep: Optional[Path] = None) -> list[str]:
    removed = []
    entries = sorted(_entries(), key=_last_used, reverse=True)
    for entry in entries[MAX_ENTRIES:]:
        if keep is not None and entry == keep:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry.name)
    # Leftovers of interrupted cache builds (no completion marker, no live lock).
    for stale in CACHE_ROOT.iterdir() if CACHE_ROOT.is_dir() else []:
        old = time.time() - stale.stat().st_mtime > STALE_SECONDS
        if stale.is_dir() and not (stale / COMPLETE_MARKER).exists() and old and not _locked(stale.name):
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.suffix == ".log" and old:
            stale.unlink(missing_ok=True)
    return removed


def _lock_path(key: str) -> Path:
    return CACHE_ROOT / f"{key}.lock"


def _locked(key: str) -> bool:
    lock = _lock_path(key)
    return lock.exists() and time.time() - lock.stat().st_mtime < STALE_SECONDS


def _acquire(key: str) -> bool:
    lock = _lock_path(key)
    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            if _locked(key):
                return False
            lock.unlink(missing_ok=True)
    return False


def _build_entry(project: Path, key: str, env: dict[str, str], timeout_s: float) -> tuple[Optional[Path], str]:
    """Compile the library objects in their final cache directory, so debug paths stay valid."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if not _acquire(key):
        return None, "another build is creating this cache entry"
    entry = CACHE_ROOT / key
    try:
        if (entry / COMPLETE_MARKER).is_file():
            return entry, ""
        shutil.rmtree(entry, ignore_errors=True)
        source = entry / "src"
        source.mkdir(parents=True)
        _copy_inputs(project, source)
        completed = subprocess.run(
            f"make --output-sync -j20 {CACHE_TARGET}", cwd=source, env=env, shell=True,
            capture_output=True, timeout=timeout_s,
        )
        if completed.returncode != 0:
            log = CACHE_ROOT / f"{key}.failed.log"
            log.write_bytes(completed.stdout + b"\n" + completed.stderr)
            raise RuntimeError(f"cache build failed (exit {completed.returncode}); see {log}")
        (entry / DEPENDENCY_MANIFEST).write_text(
            json.dumps(_external_dependencies(source), indent=1), encoding="utf-8",
        )
        # Written last: an entry without it is never used.
        (entry / COMPLETE_MARKER).write_text(key, encoding="utf-8")
        return entry, ""
    except Exception as error:
        shutil.rmtree(entry, ignore_errors=True)
        return None, str(error)
    finally:
        _lock_path(key).unlink(missing_ok=True)


def _seed(entry: Path, project: Path) -> int:
    now = time.time()
    count = 0
    for tree in CACHED_TREES:
        built = entry / "src" / "build" / tree
        for directory, _subdirs, names in os.walk(built):
            relative = Path(directory).relative_to(entry / "src")
            target_dir = project / relative
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                if name.endswith((".o", ".d")):
                    target = target_dir / name
                    shutil.copyfile(Path(directory) / name, target)
                    # Newer than every project source, so make reuses them; later edits still win.
                    os.utime(target, (now, now))
                    count += name.endswith(".o")
    (entry / LAST_USED_MARKER).write_text(str(now), encoding="utf-8")
    return count


def _dependency_mismatch(entry: Path, project: Path) -> Optional[str]:
    manifest = json.loads((entry / DEPENDENCY_MANIFEST).read_text(encoding="utf-8"))
    for path, digest in manifest.items():
        candidate = project / path
        if not candidate.is_file() or _hash_file(candidate) != digest:
            return path
    return None


def prepare(project: str | os.PathLike[str], env: dict[str, str], timeout_s: float) -> dict[str, Any]:
    """Seed an empty build directory from the cache, creating the entry when missing."""
    root = Path(project)
    started = time.monotonic()
    report: dict[str, Any] = {"status": "skipped"}
    if not enabled():
        report["reason"] = f"disabled by {ENVIRONMENT_VARIABLE}"
        return report
    if any((root / "build" / tree).exists() for tree in CACHED_TREES):
        report["reason"] = "library objects already present"
        return report
    key = fingerprint(root)
    if key is None:
        report["reason"] = "Makefile not generated with cache support or compiler not found"
        return report
    entry = CACHE_ROOT / key
    report.update(key=key, entry=str(entry))
    if (entry / COMPLETE_MARKER).is_file():
        report["status"] = "hit"
    else:
        built, error = _build_entry(root, key, env, timeout_s)
        if built is None:
            report.update(status="failed", reason=error)
            report["durationMs"] = int((time.monotonic() - started) * 1000)
            return report
        report["status"] = "created"
    mismatch = _dependency_mismatch(entry, root)
    if mismatch:
        # Library objects include a project header that differs from the cached build: compile normally.
        report.update(status="dependency-mismatch", reason=f"{mismatch} differs from the cached build")
        report["durationMs"] = int((time.monotonic() - started) * 1000)
        return report
    report["seededObjects"] = _seed(entry, root)
    report["pruned"] = prune(keep=entry)
    report["durationMs"] = int((time.monotonic() - started) * 1000)
    return report
