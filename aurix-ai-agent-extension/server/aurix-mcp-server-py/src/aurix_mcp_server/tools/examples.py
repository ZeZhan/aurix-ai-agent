"""MCP tools: examples.search, examples.import, examples.read_source

Search, import (download), and read AURIX code examples from the indexed
catalog. Supports: local filesystem, zip archives (via Python zipfile), and
GitHub repository sources (API + git sparse-checkout fallback).

Mirrors src/tools.examples.ts.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import shutil
import zipfile
from typing import Any, Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import httpx

from .ads_create_project import regenerate_makefile_for_workspace
from ..tooldef import TextContent, ToolContext, ToolResult
from ..utils import safe_error_message

DEFAULT_LIMIT = 10
MAX_LIMIT = 50

# Cache for loaded index
_index_cache: dict[str, Any] = {}
# Cache for loaded manifest
_manifest_cache: Optional[dict[str, list[str]]] = None

EXAMPLE_GIT_CACHE = os.path.join(os.path.expanduser("~"), ".aurix-agent", "example_repo_cache")


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------

def _resolve_examples_index_path(input_path: Optional[str] = None) -> str:
    # __file__ is tools/examples.py → package root is 4 levels up from __file__
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _package_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    # tools/ → aurix_mcp_server/ → src/ → aurix-mcp-server-py/
    _pkg_root = os.path.normpath(os.path.join(_this_dir, "..", "..", ".."))

    candidates = [
        input_path,
        os.environ.get("AURIX_EXAMPLES_INDEX"),
        # Installed wheel data (aurix_mcp_server/examples.index.json)
        os.path.join(_package_dir, "examples.index.json"),
        # Package root (aurix-mcp-server-py/examples.index.json)
        os.path.join(_pkg_root, "examples.index.json"),
        # CWD-based (workspace or repo root)
        os.path.join(os.getcwd(), "examples.index.json"),
        os.path.join(os.getcwd(), "..", "examples.index.json"),
        # Repo root relative to package
        os.path.join(_pkg_root, "..", "examples.index.json"),
    ]
    for c in candidates:
        if c and c.strip():
            resolved = os.path.abspath(c)
            if os.path.isfile(resolved):
                return resolved
    raise FileNotFoundError("examples.index.json was not found. Generate it first or pass indexPath.")


def _load_examples_index(index_path: Optional[str] = None) -> tuple[str, dict[str, Any]]:
    resolved = _resolve_examples_index_path(index_path)
    if resolved in _index_cache:
        return resolved, _index_cache[resolved]
    with open(resolved, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data.get("examples"), list):
        raise ValueError("examples.index.json is invalid: missing examples array")
    _index_cache[resolved] = data
    return resolved, data


def _load_manifest() -> dict[str, list[str]]:
    """Load the gzipped file manifest (examples.manifest.json.gz)."""
    global _manifest_cache
    if _manifest_cache is not None:
        return _manifest_cache
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _package_dir = os.path.normpath(os.path.join(_this_dir, ".."))
    _pkg_root = os.path.normpath(os.path.join(_this_dir, "..", "..", ".."))
    candidates = [
        os.path.join(_package_dir, "examples.manifest.json.gz"),
        os.path.join(_pkg_root, "examples.manifest.json.gz"),
        os.path.join(os.path.normpath(os.path.join(_pkg_root, "..")), "examples.manifest.json.gz"),
        os.path.join(os.getcwd(), "examples.manifest.json.gz"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                _manifest_cache = json.load(f)
            return _manifest_cache
    _manifest_cache = {}
    return _manifest_cache


# ---------------------------------------------------------------------------
# Search scoring
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    return value.strip().lower()


def _summarize_text(value: str, max_chars: int) -> str:
    trimmed = re.sub(r"\s+", " ", value).strip()
    if len(trimmed) <= max_chars:
        return trimmed
    return trimmed[: max_chars - 3].strip() + "..."


def _family_to_regex(family: str) -> re.Pattern[str]:
    escaped = re.escape(family)
    pattern = re.sub(r"x", r"\\w", escaped, flags=re.IGNORECASE)
    return re.compile(pattern, re.IGNORECASE)


def _score_example(example: dict[str, Any], query: str, board: str, family: str, keyword: str) -> int:
    score = 0
    haystacks = [
        _normalize(example.get("id", "")),
        _normalize(example.get("name", "")),
        _normalize(example.get("title", "")),
        _normalize(example.get("abstract", "")),
        _normalize(example.get("description", "")),
        *[_normalize(b) for b in example.get("boards", [])],
        *[_normalize(k) for k in example.get("keywords", [])],
        *[_normalize(d) for d in example.get("documents", [])],
    ]
    identity = [
        _normalize(example.get("id", "")),
        _normalize(example.get("name", "")),
        *[_normalize(b) for b in example.get("boards", [])],
    ]

    if query:
        if any(v == query for v in haystacks):
            score += 60
        if any(query in v for v in haystacks):
            score += 30
        for token in query.split():
            if token and any(token in v for v in haystacks):
                score += 8

    if keyword and any(keyword in _normalize(k) for k in example.get("keywords", [])):
        score += 20

    if board and any(board in v for v in identity):
        score += 25

    if family:
        family_re = _family_to_regex(family)
        if any(family_re.search(v) for v in identity):
            score += 12

    return score


def _build_match_reasons(example: dict[str, Any], query: str, board: str, keyword: str) -> list[str]:
    reasons: list[str] = []
    if query:
        if query in _normalize(example.get("title", "")):
            reasons.append(f"title: {example.get('title', '')}")
        elif query in _normalize(example.get("abstract", "")):
            reasons.append(f"abstract: {_summarize_text(example.get('abstract', ''), 120)}")
        else:
            for kw in example.get("keywords", []):
                if query in _normalize(kw):
                    reasons.append(f"keyword: {kw}")
                    break
    if keyword:
        for kw in example.get("keywords", []):
            if keyword in _normalize(kw):
                reasons.append(f"keyword: {kw}")
                break
    if board:
        identity_fields = [example.get("id", ""), example.get("name", ""), *example.get("boards", [])]
        for f in identity_fields:
            if board in _normalize(f):
                reasons.append(f"board: {f}")
                break
    return list(dict.fromkeys(reasons))[:3]


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _github_headers() -> dict[str, str]:
    h = {"User-Agent": "aurix-mcp-server"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"token {token}"
    return h


def _resolve_github_source_root(source_root: str) -> Optional[dict[str, str]]:
    m = re.match(
        r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/tree/([^/]+)(?:/(.*))?)?$",
        source_root, re.IGNORECASE,
    )
    if not m:
        return None
    return {
        "owner": m.group(1),
        "repo": m.group(2),
        "branch": m.group(3) or "master",
        "pathPrefix": (m.group(4) or "").rstrip("/"),
    }


def _https_get(url: str, binary: bool = False) -> tuple[int, bytes]:
    req = Request(url, headers=_github_headers())
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except HTTPError as e:
        return e.code, e.read()
    except (URLError, OSError) as e:
        raise ConnectionError(f"HTTP request failed: {e}") from e


def _fetch_github_raw(owner: str, repo: str, branch: str, file_path: str) -> str:
    normalized = file_path.replace("\\", "/").replace("//", "/").lstrip("/")
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{normalized}"
    status, body = _https_get(url)
    if status != 200:
        raise ConnectionError(f"GitHub raw fetch failed ({status}): {url}")
    return body.decode("utf-8", errors="replace")


async def _fetch_github_tree(owner: str, repo: str, branch: str, dir_path: str) -> list[dict[str, Any]]:
    normalized_dir = dir_path.replace("\\", "/").replace("//", "/").strip("/")

    ref_url = f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch}"
    status, body = await asyncio.to_thread(_https_get, ref_url)
    if status != 200:
        raise ConnectionError(f"GitHub ref API failed ({status})")
    ref_data = json.loads(body)
    commit_sha = ref_data.get("object", {}).get("sha")
    if not commit_sha:
        raise ValueError("Could not resolve branch commit SHA")

    tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
    status, body = await asyncio.to_thread(_https_get, tree_url)
    if status != 200:
        raise ConnectionError(f"GitHub tree API failed ({status})")
    tree_data = json.loads(body)
    all_entries = tree_data.get("tree", [])

    prefix = f"{normalized_dir}/" if normalized_dir else ""
    return [
        {**e, "path": e["path"][len(prefix):]}
        for e in all_entries
        if e["path"].startswith(prefix) and e["path"] != normalized_dir
    ]


async def _download_via_manifest(
    owner: str, repo: str, branch: str,
    remote_dir: str, local_dir: str, overwrite: bool,
    file_list: list[str],
) -> dict[str, list[str]]:
    """Download files from raw.githubusercontent.com using a pre-built manifest.

    No GitHub API calls, no git clone — just direct CDN downloads.
    """
    return await _download_raw_files(
        owner, repo, branch, remote_dir, local_dir, overwrite, file_list
    )


async def _download_raw_files(
    owner: str, repo: str, branch: str,
    remote_dir: str, local_dir: str, overwrite: bool,
    file_list: list[str],
) -> dict[str, list[str]]:
    normalized_remote = remote_dir.replace("\\", "/").strip("/")
    downloaded: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    semaphore = asyncio.Semaphore(12)

    async def download_one(
        client: httpx.AsyncClient, rel_path: str
    ) -> tuple[str, str, Optional[str]]:
        local_path = os.path.join(local_dir, *rel_path.split("/"))
        if not overwrite and os.path.exists(local_path):
            return "skipped", rel_path, None
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{normalized_remote}/{rel_path}"
        try:
            async with semaphore:
                response = await client.get(raw_url)
            if response.status_code != 200:
                return "error", rel_path, f"{rel_path}: HTTP {response.status_code}"
            with open(local_path, "wb") as fh:
                fh.write(response.content)
            return "downloaded", rel_path, None
        except Exception as e:
            return "error", rel_path, f"{rel_path}: {e}"

    limits = httpx.Limits(max_connections=12, max_keepalive_connections=12)
    async with httpx.AsyncClient(
        headers=_github_headers(),
        timeout=30,
        follow_redirects=True,
        limits=limits,
    ) as client:
        results = await asyncio.gather(
            *(download_one(client, rel_path) for rel_path in file_list)
        )
    for status, rel_path, error in results:
        if status == "downloaded":
            downloaded.append(rel_path)
        elif status == "skipped":
            skipped.append(rel_path)
        elif error is not None:
            errors.append(error)

    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


async def _download_github_directory(
    owner: str, repo: str, branch: str,
    remote_dir: str, local_dir: str, overwrite: bool,
    file_list: Optional[list[str]] = None,
) -> dict[str, list[str]]:
    """Download a directory from its manifest, with API/git as legacy fallbacks."""
    if file_list:
        return await _download_via_manifest(
            owner, repo, branch, remote_dir, local_dir, overwrite, file_list
        )

    try:
        entries = await _fetch_github_tree(owner, repo, branch, remote_dir)
        result = await _download_from_entries(owner, repo, branch, remote_dir, entries, local_dir, overwrite)
        if not result["downloaded"] and not result["errors"]:
            raise ConnectionError("Tree API returned 0 files")
        return result
    except Exception as tree_err:
        try:
            return await _download_via_git_sparse_checkout(owner, repo, branch, remote_dir, local_dir, overwrite)
        except Exception as git_err:
            raise ConnectionError(
                f"GitHub API failed: {tree_err} | Git fallback also failed: {git_err} "
                f"| Hint: set GITHUB_TOKEN env var for higher API limits, or ensure git is installed."
            ) from git_err


async def _download_from_entries(
    owner: str, repo: str, branch: str,
    remote_dir: str, entries: list[dict[str, Any]],
    local_dir: str, overwrite: bool,
) -> dict[str, list[str]]:
    normalized_remote = remote_dir.replace("\\", "/").strip("/")
    blobs = [e for e in entries if e.get("type") == "blob"]
    return await _download_raw_files(
        owner, repo, branch, normalized_remote, local_dir, overwrite,
        [blob["path"] for blob in blobs],
    )


# ---------------------------------------------------------------------------
# Git sparse-checkout fallback
# ---------------------------------------------------------------------------

async def _run_git(cwd: str, args: list[str], timeout: float = 120) -> tuple[str, str, int]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.communicate()
        raise TimeoutError(f"git {args[0]} timed out")
    return (
        (stdout or b"").decode("utf-8", errors="replace"),
        (stderr or b"").decode("utf-8", errors="replace"),
        proc.returncode if proc.returncode is not None else 1,
    )


async def _ensure_git_repo_cache(owner: str, repo: str, branch: str) -> str:
    cache_dir = EXAMPLE_GIT_CACHE
    git_dir = os.path.join(cache_dir, ".git")

    if os.path.isdir(git_dir):
        return cache_dir

    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir, ignore_errors=True)

    parent = os.path.dirname(cache_dir)
    os.makedirs(parent, exist_ok=True)

    repo_url = f"https://github.com/{owner}/{repo}.git"
    _, stderr, code = await _run_git(parent, [
        "clone", "--no-checkout", "--depth", "1", "--filter=blob:none",
        "--branch", branch, "--sparse",
        repo_url, os.path.basename(cache_dir),
    ], timeout=180)

    if code != 0:
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir, ignore_errors=True)
        raise RuntimeError(f"git clone failed (code {code}): {stderr[:500]}")

    return cache_dir


async def _download_via_git_sparse_checkout(
    owner: str, repo: str, branch: str,
    remote_dir: str, local_dir: str, overwrite: bool,
) -> dict[str, list[str]]:
    cache_dir = await _ensure_git_repo_cache(owner, repo, branch)
    normalized_dir = remote_dir.replace("\\", "/").strip("/")

    _, stderr, code = await _run_git(cache_dir, ["sparse-checkout", "add", normalized_dir], timeout=30)
    if code != 0:
        raise RuntimeError(f"git sparse-checkout add failed: {stderr[:300]}")

    _, stderr, code = await _run_git(cache_dir, ["checkout"], timeout=180)
    if code != 0:
        raise RuntimeError(f"git checkout failed: {stderr[:300]}")

    src_dir = os.path.join(cache_dir, normalized_dir)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f"Directory not found after git checkout: {normalized_dir}")

    return _copy_directory_recursive(src_dir, local_dir, overwrite)


def _copy_directory_recursive(src: str, dest: str, overwrite: bool) -> dict[str, list[str]]:
    downloaded: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []
    os.makedirs(dest, exist_ok=True)

    def walk(src_path: str, dest_path: str, base_src: str) -> None:
        try:
            entries = list(os.scandir(src_path))
        except OSError:
            return
        for entry in entries:
            if entry.name == ".git":
                continue
            s = entry.path
            d = os.path.join(dest_path, entry.name)
            rel = os.path.relpath(s, base_src).replace("\\", "/")
            if entry.is_dir():
                os.makedirs(d, exist_ok=True)
                walk(s, d, base_src)
            elif entry.is_file():
                if not overwrite and os.path.exists(d):
                    skipped.append(rel)
                    continue
                try:
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    shutil.copy2(s, d)
                    downloaded.append(rel)
                except Exception as e:
                    errors.append(f"{rel}: {e}")

    walk(src, dest, src)
    return {"downloaded": downloaded, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Zip source helpers
# ---------------------------------------------------------------------------

def _resolve_zip_source_root(source_root: str) -> Optional[tuple[str, str]]:
    """Returns (zip_path, inner_prefix) or None."""
    marker = ".zip::"
    idx = source_root.lower().find(marker)
    if idx < 0:
        return None
    zip_path = source_root[: idx + 4]
    inner_prefix = source_root[idx + len(marker):].replace("\\", "/").strip("/")
    return zip_path, inner_prefix


def _read_text_from_zip(zip_path: str, internal_path: str) -> Optional[str]:
    if not os.path.isfile(zip_path):
        return None
    normalized = internal_path.replace("\\", "/").lstrip("/")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            # Try exact, then suffix match
            for name in zf.namelist():
                if name == normalized or name.endswith(f"/{normalized}") or name.endswith(normalized):
                    return zf.read(name).decode("utf-8", errors="replace")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# examples.search
# ---------------------------------------------------------------------------

async def _search_run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    index_path_arg = args.get("indexPath")
    resolved_path, data = _load_examples_index(index_path_arg)

    query = _normalize(args.get("query", "") or "")
    board = _normalize(args.get("board", "") or "")
    family = _normalize(args.get("family", "") or "")
    keyword = _normalize(args.get("keyword", "") or "")
    limit_raw = args.get("limit")
    limit = max(1, min(MAX_LIMIT, int(limit_raw) if isinstance(limit_raw, (int, float)) else DEFAULT_LIMIT))

    scored = []
    for ex in data["examples"]:
        s = _score_example(ex, query, board, family, keyword)
        if s > 0 or (not query and not board and not family and not keyword):
            scored.append((ex, s, _build_match_reasons(ex, query, board, keyword)))

    scored.sort(key=lambda x: (-x[1], x[0].get("id", "")))
    results = scored[:limit]

    output = {
        "indexPath": resolved_path,
        "count": len(results),
        "results": [
            {
                "id": ex.get("id", ""),
                "title": ex.get("title", ""),
                "abstract": ex.get("abstract", ""),
                "boards": ex.get("boards", []),
                "keywords": ex.get("keywords", []),
                "score": score,
                "matches": matches,
                "rootPath": ex.get("rootPath", ""),
            }
            for ex, score, matches in results
        ],
    }
    return ToolResult(
        content=[TextContent(text=json.dumps(output, indent=2))],
        structured_content=output,
    )


# ---------------------------------------------------------------------------
# examples.import
# ---------------------------------------------------------------------------

async def _import_run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    example_id = args.get("id", "").strip()
    target_dir = args.get("targetDir", "").strip()
    if not example_id:
        raise ValueError("examples.import requires id")
    if not target_dir:
        raise ValueError("examples.import requires targetDir")

    index_path_arg = args.get("indexPath")
    _, data = _load_examples_index(index_path_arg)
    example = next((e for e in data["examples"] if _normalize(e.get("id", "")) == _normalize(example_id)), None)
    if not example:
        raise ValueError(f"Example not found: {example_id}")

    source_root = data.get("sourceRoot", "")
    overwrite = args.get("overwrite") is True
    target = os.path.abspath(target_dir)
    os.makedirs(target, exist_ok=True)

    gh = _resolve_github_source_root(source_root)
    zip_src = _resolve_zip_source_root(source_root)

    if gh:
        remote_path = f"{gh['pathPrefix']}/{example['rootPath']}" if gh["pathPrefix"] else example["rootPath"]
        manifest = _load_manifest()
        file_list = manifest.get(example.get("rootPath", ""))
        download_task = asyncio.create_task(
            _download_github_directory(
                gh["owner"], gh["repo"], gh["branch"], remote_path, target, overwrite, file_list
            )
        )
        elapsed_seconds = 0
        await _ctx.send_progress(
            f"examples.import: downloading {example['id']} to {target}", "stdout"
        )
        while not download_task.done():
            done, _ = await asyncio.wait({download_task}, timeout=10)
            if download_task in done:
                break
            elapsed_seconds += 10
            await _ctx.send_progress(
                f"examples.import: still downloading {example['id']} ({elapsed_seconds}s elapsed)",
                "stdout",
            )
        result = await download_task
        ok = not result["errors"] and bool(result["downloaded"])
        error_detail = ("\nErrors:\n" + "\n".join(result["errors"])) if result["errors"] else ""
        regen_msg = regenerate_makefile_for_workspace(target) if ok else None
        text = (
            f"examples.import succeeded: {len(result['downloaded'])} file(s) downloaded to {target}"
            f"{f'{chr(10)}{regen_msg}' if regen_msg else ''}"
            if ok else
            f"examples.import failed: {len(result['downloaded'])} downloaded, {len(result['errors'])} error(s).{error_detail}"
            f"{'\nHint: This is likely a GitHub API rate limit (60 req/hr unauthenticated). Try again later or download manually from https://github.com/Infineon/AURIX_code_examples.' if not result['downloaded'] else ''}"
        )
        return ToolResult(
            content=[TextContent(text=text)],
            is_error=not ok,
            structured_content={
                "ok": ok,
                "exampleId": example["id"],
                "sourceRoot": source_root,
                "targetDir": target,
                "downloaded": result["downloaded"],
                "skipped": result["skipped"],
                "errors": result["errors"],
            },
        )

    if zip_src:
        zip_path, inner_prefix = zip_src
        if not os.path.isfile(zip_path):
            raise FileNotFoundError(f"Zip file not found: {zip_path}")
        prefix = f"{inner_prefix}/{example['rootPath']}/".replace("\\", "/").replace("//", "/")
        downloaded: list[str] = []
        skipped_files: list[str] = []
        errors: list[str] = []
        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                rel = name[len(prefix):]
                local_path = os.path.join(target, *rel.split("/"))
                if not overwrite and os.path.exists(local_path):
                    skipped_files.append(rel)
                    continue
                try:
                    os.makedirs(os.path.dirname(local_path), exist_ok=True)
                    with zf.open(name) as src, open(local_path, "wb") as dst:
                        dst.write(src.read())
                    downloaded.append(rel)
                except Exception as e:
                    errors.append(f"{rel}: {e}")

        ok = not errors and bool(downloaded)
        error_detail = ("\nErrors:\n" + "\n".join(errors)) if errors else ""
        regen_msg = regenerate_makefile_for_workspace(target) if ok else None
        text = (
            f"examples.import succeeded: {len(downloaded)} file(s) extracted to {target}"
            f"{f'{chr(10)}{regen_msg}' if regen_msg else ''}"
            if ok else
            f"examples.import failed: {len(downloaded)} extracted, {len(errors)} error(s).{error_detail}"
        )
        return ToolResult(
            content=[TextContent(text=text)],
            is_error=not ok,
            structured_content={"ok": ok, "exampleId": example["id"], "sourceRoot": source_root, "targetDir": target, "downloaded": downloaded, "skipped": skipped_files, "errors": errors},
        )

    # Local filesystem
    local_root = source_root.split("::", 1)[0] if "::" in source_root else source_root
    example_dir = os.path.join(local_root, example["rootPath"])
    if not os.path.isdir(example_dir):
        raise FileNotFoundError(f"Example source directory not found: {example_dir}")
    result = _copy_directory_recursive(example_dir, target, overwrite)
    regen_msg = regenerate_makefile_for_workspace(target)
    regen_suffix = f"\n{regen_msg}" if regen_msg else ""
    return ToolResult(
        content=[TextContent(text=f"examples.import succeeded: {len(result['downloaded'])} file(s) copied to {target}{regen_suffix}")],
        structured_content={"ok": True, "exampleId": example["id"], "sourceRoot": source_root, "targetDir": target, **result},
    )


# ---------------------------------------------------------------------------
# examples.read_source
# ---------------------------------------------------------------------------

async def _read_source_run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    example_id = (args.get("id") or "").strip()
    if not example_id:
        raise ValueError("examples.read_source requires id")

    index_path_arg = args.get("indexPath")
    _, data = _load_examples_index(index_path_arg)
    example = next((e for e in data["examples"] if _normalize(e.get("id", "")) == _normalize(example_id)), None)
    if not example:
        raise ValueError(f"Example not found: {example_id}")

    source_root = data.get("sourceRoot", "")
    gh = _resolve_github_source_root(source_root)

    requested_files = args.get("files") if isinstance(args.get("files"), list) and args["files"] else (example.get("cpuMainFiles") or ["Cpu0_Main.c"])

    results: list[dict[str, str]] = []
    for rel_file in requested_files:
        rel_file = str(rel_file)
        try:
            content: Optional[str] = None
            if gh:
                file_path = f"{gh['pathPrefix']}/{example['rootPath']}/{rel_file}".replace("\\", "/").replace("//", "/")
                content = await asyncio.to_thread(
                    _fetch_github_raw, gh["owner"], gh["repo"], gh["branch"], file_path
                )

            if content is None:
                # Try zip
                zip_src = _resolve_zip_source_root(source_root)
                if zip_src:
                    internal = f"{zip_src[1]}/{example['rootPath']}/{rel_file}".replace("\\", "/").replace("//", "/")
                    content = _read_text_from_zip(zip_src[0], internal)

            if content is None:
                # Local filesystem
                local_root = source_root.split("::", 1)[0] if "::" in source_root else source_root
                local_path = os.path.join(local_root, example["rootPath"], rel_file)
                if os.path.isfile(local_path):
                    with open(local_path, "r", encoding="utf-8", errors="replace") as fh:
                        content = fh.read()

            if content is not None:
                results.append({"file": rel_file, "content": content})
            else:
                results.append({"file": rel_file, "content": "", "error": "File not found"})
        except Exception as e:
            results.append({"file": rel_file, "content": "", "error": str(e)})

    success_count = sum(1 for r in results if "error" not in r)
    total_chars = sum(len(r["content"]) for r in results)
    text = "\n\n".join(
        f"=== {r['file']} ===\n{'ERROR: ' + r['error'] if 'error' in r else r['content']}"
        for r in results
    )

    return ToolResult(
        content=[TextContent(text=text)],
        structured_content={
            "exampleId": example.get("id", ""),
            "title": example.get("title", ""),
            "rootPath": example.get("rootPath", ""),
            "filesRead": success_count,
            "totalFiles": len(results),
            "totalChars": total_chars,
            "files": [
                {"file": result["file"], "chars": len(result["content"]), "content": result["content"],
                 **({"error": result["error"]} if "error" in result else {})}
                for result in results
            ],
        },
    )

