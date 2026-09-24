"""MCP business logic for citation-aware AURIX documentation search."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..board_documentation import board_evidence
from ..documentation_retrieval import search_results
from ..tooldef import ToolContext, ToolResult
from ..utils import safe_error_message

DEFAULT_TOP_K = 3
MAX_TOP_K = 10
INDEX_ENVIRONMENT_VARIABLE = "AURIX_DOCUMENTATION_INDEX"
INDEX_DIRECTORY_ENVIRONMENT_VARIABLE = "AURIX_DOCUMENTATION_INDEX_DIR"
SELECTED_DEVICE_ENVIRONMENT_VARIABLE = "AURIX_SELECTED_DEVICE"
INDEX_FILENAMES = {
	"tc2xx": "aurix-tc2xx.sqlite",
	"tc3xx": "aurix-tc3xx.sqlite",
	"tc4dx": "aurix-tc4dx.sqlite",
}
FAMILY_PATTERNS = {
	"tc2xx": re.compile(r"(?<![a-z0-9])tc2(?:xx|\d{2}[a-z]?)(?![a-z0-9])", re.IGNORECASE),
	"tc3xx": re.compile(r"(?<![a-z0-9])tc3(?:xx|\d{2}[a-z]?)(?![a-z0-9])", re.IGNORECASE),
	"tc4dx": re.compile(r"(?<![a-z0-9])tc4(?:dx|xx|d[79])(?![a-z0-9])", re.IGNORECASE),
}


def _family_from_text(value: str) -> str | None:
	matches = [family for family, pattern in FAMILY_PATTERNS.items() if pattern.search(value)]
	if len(matches) > 1:
		raise ValueError("Documentation search refers to multiple AURIX generations")
	return matches[0] if matches else None


def _resolve_family(args: dict[str, Any], query: str) -> str | None:
	explicit_hints = [args.get("device"), args.get("family"), args.get("board")]
	explicit_families = {
		resolved
		for hint in explicit_hints
		if isinstance(hint, str) and hint.strip()
		if (resolved := _family_from_text(hint)) is not None
	}
	if len(explicit_families) > 1:
		raise ValueError("device and family refer to different AURIX generations")
	if explicit_families:
		return explicit_families.pop()

	query_family = _family_from_text(query)
	if query_family:
		return query_family

	selected_device = os.environ.get(SELECTED_DEVICE_ENVIRONMENT_VARIABLE, "")
	return _family_from_text(selected_device)


def _resolve_index_path(index_path: str | None = None, family: str | None = None) -> Path:
	candidate = index_path or os.environ.get(INDEX_ENVIRONMENT_VARIABLE)
	if not candidate:
		index_directory = os.environ.get(INDEX_DIRECTORY_ENVIRONMENT_VARIABLE)
		if index_directory and family:
			candidate = str(Path(index_directory) / INDEX_FILENAMES[family])
	if not isinstance(candidate, str) or not candidate.strip():
		raise FileNotFoundError(
			"Documentation index was not provided or its AURIX generation could not be "
			"determined. Pass device/family/indexPath or configure "
			f"{INDEX_DIRECTORY_ENVIRONMENT_VARIABLE}."
		)

	resolved = Path(candidate).expanduser().resolve()
	if not resolved.is_file():
		raise FileNotFoundError(f"Documentation index was not found: {resolved}")
	return resolved


def _parse_input(args: dict[str, Any]) -> tuple[str, int, str | None]:
	if not isinstance(args, dict):
		raise ValueError("documentation.search requires an object argument")

	query = args.get("query")
	if not isinstance(query, str) or not query.strip():
		raise ValueError("documentation.search requires a non-empty query")

	top_k = args.get("topK", DEFAULT_TOP_K)
	if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
		raise ValueError("topK must be a positive integer")

	index_path = args.get("indexPath")
	if index_path is not None and not isinstance(index_path, str):
		raise ValueError("indexPath must be a string")
	for key in ("board", "hardwareVersion", "projectPath", "device", "family"):
		if args.get(key) is not None and not isinstance(args[key], str):
			raise ValueError(f"{key} must be a string")
	if args.get("projectPath") and not Path(args["projectPath"]).is_dir():
		raise ValueError("projectPath must be an existing directory")

	clean_query = query.strip()
	family = _resolve_family(args, clean_query)
	return clean_query, min(top_k, MAX_TOP_K), family


def _citation_text(result: dict[str, object]) -> str:
	citation = result["citation"]
	if not isinstance(citation, dict):
		raise ValueError("Documentation result is missing citation metadata")

	pages = citation.get("pdf_pages")
	page_text = ", ".join(str(page) for page in pages) if isinstance(pages, list) else "unknown"
	title = citation.get("document_title") or citation.get("document_id") or "Unknown document"
	section = citation.get("section")
	excerpt = citation.get("excerpt") or result.get("excerpt") or ""
	source = citation.get("source") or result.get("source") or ""

	lines = [f"{title}, physical PDF page(s) {page_text}"]
	if section:
		lines.append(f"Section: {section}")
	if citation.get("board"):
		lines.append(f"Board: {citation['board']}; hardware: {citation['hardware_versions']}; document revision: {citation['document_version']}")
		lines.append(f"Applicability: {result['applicability']}; usable for code generation: {result['usableForCodeGeneration']}")
		lines.append(f"BPL check: {result.get('bplCheck', 'not_checked')}")
		if result.get("usageRestriction"):
			lines.append(f"Usage restriction: {result['usageRestriction']}")
		if result.get("missingSignals"):
			lines.append(f"BPL labels missing: {', '.join(result['missingSignals'])}")
	lines.append(str(excerpt))
	if source:
		lines.append(f"Source: {source}")
	return "\n".join(lines)


async def _run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
	try:
		query, top_k, family = _parse_input(args)
		board_result = board_evidence(args, query, top_k)
		if board_result is not None:
			board_family = _family_from_text(board_result["board"] or "")
			if args.get("family") and board_family and _family_from_text(args["family"]) != board_family:
				raise ValueError("board and family refer to different AURIX generations")
			results = board_result["results"]
		else:
			index_path = _resolve_index_path(args.get("indexPath"), family)
			results = search_results(index_path, query, limit=top_k)
		structured = {
			"query": query,
			"family": family,
			"resultCount": len(results),
			"abstained": not results,
			"results": results,
		}
		if board_result is not None:
			structured.update(board_result)
			structured["abstained"] = not any(result["facts"] for result in results)
			structured["family"] = _family_from_text(board_result["board"] or "") or family
		if not results:
			return ToolResult.text(
				f'No supported documentation evidence found for "{query}". {structured.get("reason", "")}',
				structured=structured,
			)

		text = "\n\n".join(
			f"[{position}] {_citation_text(result)}"
			for position, result in enumerate(results, start=1)
		)
		return ToolResult.text(text, structured=structured)
	except Exception as error:
		return ToolResult.text(
			f"documentation.search error: {safe_error_message(error)}",
			is_error=True,
		)
