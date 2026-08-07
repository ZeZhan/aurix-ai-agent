"""Workspace context loading. Mirrors src/context.ts."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_CONTEXT_RELATIVE_PATH = os.path.join(".aurix-ai", "context.json")


def resolve_workspace_root(workspace: Optional[str] = None) -> str:
    if workspace and workspace.strip():
        return os.path.abspath(workspace)
    return os.path.abspath(os.getcwd())


def resolve_context_path(workspace_root: str) -> str:
    return os.path.join(workspace_root, DEFAULT_CONTEXT_RELATIVE_PATH)


@dataclass
class WorkspaceContext:
    workspace_root: str
    context_path: str
    exists: bool
    data: Optional[dict[str, Any]] = None


def load_workspace_context(workspace: Optional[str] = None) -> WorkspaceContext:
    workspace_root = resolve_workspace_root(workspace)
    context_path = resolve_context_path(workspace_root)
    if not os.path.exists(context_path):
        return WorkspaceContext(workspace_root, context_path, exists=False)
    try:
        with open(context_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            data = None
    except Exception:
        data = None
    return WorkspaceContext(workspace_root, context_path, exists=True, data=data)


def context_get(data: Optional[dict[str, Any]], *path: str) -> Any:
    """Safely walk a nested dict path; returns None if any segment is missing."""
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur
