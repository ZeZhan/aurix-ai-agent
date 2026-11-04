"""MCP business logic for citation-aware AURIX documentation search."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..board_documentation import (
	BOARD_TEXT_CITE_PAGE, BOARD_TEXT_GUIDANCE, BOARD_TEXT_INDEX, BOARD_TEXT_VERSION_REQUIRED, board_evidence,
	board_manual_text, board_text_guidance, explicit_board, query_hardware_version, revision_independent,
)
from ..connected_devices import detected_hardware_version
from ..documentation_retrieval import (
	DEVICE_DOCUMENT_PREFIXES, DEVICE_TERMS, EVIDENCE_CHARS_PER_CHUNK, EVIDENCE_TOTAL_CHARS,
	FOLLOW_UP_FILLER, FOLLOW_UP_MAX_RESULTS, MAX_EVIDENCE_NEIGHBORS, ChunkNotFoundError, coverage_hints,
	follow_up_queries, hardware_version_matches, query_document_prefixes, query_terms, read_chunk, search_results,
)
from ..tooldef import ToolContext, ToolResult
from ..utils import safe_error_message

DEFAULT_TOP_K = 3
# Text excerpts (chip manuals, board-manual text) are capped at MAX_TOP_K; reviewed board
# facts are one line each, so a request for all LEDs/buttons of a board may return more.
MAX_TOP_K = 5
BOARD_FACT_MAX_TOP_K = 10
# Compact (default) output: one focused excerpt per result instead of full chunks and neighbors.
COMPACT_RESULT_CHARS = 3000
COMPACT_FOLLOW_UP_CHARS = 2000
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
		family = explicit_families.pop()
		query_family = _family_from_text(query)
		if query_family and family != query_family:
			raise ValueError("device/family and query refer to different AURIX generations")
		return family

	query_family = _family_from_text(query)
	if query_family:
		return query_family

	selected_device = os.environ.get(SELECTED_DEVICE_ENVIRONMENT_VARIABLE, "")
	return _family_from_text(selected_device)


def _retrieval_query(args: dict[str, Any], query: str) -> str:
	pattern = r"(?<![a-z0-9])(?:" + "|".join(DEVICE_DOCUMENT_PREFIXES) + r")(?![a-z0-9])"
	query_devices = set(re.findall(pattern, query, re.IGNORECASE))
	hint = args.get("device") or args.get("board") or ""
	if not hint and not query_devices and not _family_from_text(query):
		selected = os.environ.get(SELECTED_DEVICE_ENVIRONMENT_VARIABLE, "")
		if not args.get("family") or _family_from_text(selected) == _family_from_text(args["family"]):
			hint = selected
	hint_devices = set(re.findall(pattern, hint, re.IGNORECASE))
	if query_devices and hint_devices:
		query_prefixes = set(query_document_prefixes(" ".join(query_devices))) - {"tc3xx-"}
		hint_prefixes = set(query_document_prefixes(" ".join(hint_devices))) - {"tc3xx-"}
		specific_query = {value.casefold() for value in query_devices if not value.lower().endswith("x")}
		specific_hint = {value.casefold() for value in hint_devices if not value.lower().endswith("x")}
		if not query_prefixes.intersection(hint_prefixes) or (
			specific_query and specific_hint and specific_query != specific_hint
		):
			raise ValueError("device/board and query refer to different devices")
	return query if query_devices or not hint_devices else " ".join(sorted(hint_devices)) + " " + query


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
		raise ValueError("documentation_search requires an object argument")

	query = args.get("query")
	if not isinstance(query, str) or not query.strip():
		raise ValueError("documentation_search requires a non-empty query")

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
	if args.get("detail", "compact") not in ("compact", "full"):
		raise ValueError('detail must be "compact" or "full"')

	clean_query = query.strip()
	family = _resolve_family(args, clean_query)
	return clean_query, min(top_k, BOARD_FACT_MAX_TOP_K), family


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
	lines.append(f"Document revision: {citation.get('document_version') or 'unspecified'}")
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


def _evidence_text(result: dict[str, Any]) -> str:
	sections = [_citation_text(result)]
	for evidence in result.get("evidence", []):
		sections.append(
			f'Evidence chunkId={evidence["chunk_id"]}, offset={evidence["offset"]}:\n'
			+ _citation_text({"citation": evidence["citation"]})
		)
		if evidence["truncated"]:
			sections.append(
				f'Truncated: call documentation_read with chunkId="{evidence["chunk_id"]}" '
				f'and offset={evidence["nextOffset"]} to continue.'
			)
	return "\n\n".join(sections)


def _focus_terms(query: str) -> list[str]:
	terms: list[str] = []
	for term in query_terms(query):
		key = term.casefold()
		if key in DEVICE_TERMS or key in FOLLOW_UP_FILLER or len(key) < 2:
			continue
		terms.append(key)
		if "-" in key:
			terms.extend((key.replace("-", " "), key.replace("-", "")))
	return terms


def _focus_window(text: str, terms: list[str], size: int) -> tuple[int, int]:
	"""Window of `size` characters containing the most distinct query terms."""
	if len(text) <= size:
		return 0, len(text)
	lowered = text.casefold()
	hits = [
		(match.start(), term)
		for term in dict.fromkeys(terms)
		for match in list(re.finditer(r"(?<![a-z0-9])" + re.escape(term), lowered))[:40]
	]
	best_start, best_count = 0, 0
	for position, _ in hits:
		start = max(0, position - size // 5)
		count = len({term for hit, term in hits if start <= hit < start + size})
		if count > best_count:
			best_start, best_count = start, count
	line_start = text.rfind("\n", 0, best_start) + 1
	if best_start and best_start - line_start < 200:
		best_start = line_start
	start = min(best_start, len(text) - size)
	return start, start + size


def _compact_result_text(position: int, result: dict[str, Any], terms: list[str], size: int) -> str:
	citation = result["citation"]
	title = citation.get("document_title") or result.get("document_id") or "Unknown document"
	pages = ",".join(str(page) for page in citation.get("pdf_pages") or [])
	revision = citation.get("document_version")
	header = f"[{position}]"
	if result.get("retrievalPass") == "follow_up":
		header += f' (follow-up "{result["followUpQuery"]}")'
	header += f" {title}, p.{pages}"
	if revision and revision != "unspecified":
		header += f", rev {revision}"
	section = citation.get("section") or ""
	if section:
		header += " | " + " > ".join(section.split(" > ")[-2:])[:90]
	lines = [header]
	if citation.get("board"):
		flags = [
			f'board {citation["board"]} hw {",".join(citation.get("hardware_versions") or [])}',
			f'applicability {result.get("applicability")}',
			f'code generation {"yes" if result.get("usableForCodeGeneration") else "no"}',
		]
		if result.get("bplCheck") and result["bplCheck"] != "not_checked":
			flags.append(f'BPL {result["bplCheck"]}')
		if result.get("usageRestriction"):
			flags.append(result["usageRestriction"])
		if result.get("missingSignals"):
			flags.append("BPL labels missing: " + ", ".join(result["missingSignals"]))
		lines.append("; ".join(flags))
	segments = result.get("evidence") or []
	if not segments:
		lines.append(str(citation.get("excerpt") or result.get("excerpt") or "").strip())
		return "\n".join(lines)
	# Pick the stored segment (hit or adjacent page) whose best window covers the most query terms.
	best = None
	for index, segment in enumerate(segments):
		start, end = _focus_window(segment["text"], terms, size)
		window = segment["text"][start:end].casefold()
		score = len({term for term in terms if term in window})
		if best is None or score > best[0]:
			best = (score, index, start, end)
	_, index, start, end = best
	segment = segments[index]
	shown_pages = ",".join(str(page) for page in segment["citation"]["pdf_pages"])
	if index:
		lines.append(f"(text from adjacent p.{shown_pages})")
	body = segment["text"][start:end].strip()
	lines.append(("… " if start else "") + body + (" …" if end < len(segment["text"]) else ""))
	offset = segment["offset"] + start
	if start or end < len(segment["text"]) or segment.get("truncated"):
		lines.append(f'[excerpt; full text: documentation_read chunkId="{segment["chunk_id"]}"'
		             + (f", offset={offset}" if offset else "") + "]")
	return "\n".join(lines)


def _compact_structured(structured: dict[str, Any]) -> dict[str, Any]:
	"""Citation metadata only; the evidence text is already in the text content."""
	keep_result = (
		"chunk_id", "retrievalPass", "followUpQuery", "applicability", "usableForCodeGeneration",
		"facts", "bplCheck", "usageRestriction", "conflicts", "missingSignals",
	)
	keep_citation = (
		"document_id", "document_title", "document_version", "source", "pdf_pages", "page_basis",
		"board", "hardware_versions", "source_sha256",
	)
	compact = {
		key: value for key, value in structured.items()
		if key not in {"results", "evidencePolicy", "evidenceGuidance", "boardTextGuidance", "retrievalQuery"}
	}
	compact["results"] = [
		{
			**{
				key: result[key] for key in keep_result
				# Reviewed board facts are complete and documentation_read cannot open them.
				if key in result and not (key == "chunk_id" and result.get("facts"))
			},
			"citation": {key: result["citation"][key] for key in keep_citation if key in result["citation"]},
		}
		for result in structured["results"]
	]
	return compact


def _compact_text(structured: dict[str, Any], retrieval_query: str, chip_scope: bool) -> str:
	results = structured["results"]
	terms = _focus_terms(retrieval_query)
	header = []
	if chip_scope:
		header.append(
			"Documentation excerpts: candidates, not proof of a complete answer; check device, stepping, "
			"conditions and errata. Results marked follow-up come from automatic per-clause re-search. "
			"If an excerpt is cut, read the rest with documentation_read and its chunkId."
		)
	if structured.get("boardTextGuidance"):
		header.append(structured["boardTextGuidance"])
	if structured.get("hardwareVersionDetected"):
		detected = structured["hardwareVersionDetected"]
		header.append(f'Board hardware version {detected["hardwareVersion"]} detected on the connected kit '
		              f'({detected["boardHardware"]}) via {detected["source"]}; no need to ask the user.')
	if structured.get("hardwareVersionNote"):
		header.append(f'Board hardware revision {structured["hardwareVersionNote"]}; no need to ask the user.')
	blocks = []
	for position, result in enumerate(results, start=1):
		follow_up = result.get("retrievalPass") == "follow_up"
		result_terms = _focus_terms(result["followUpQuery"]) if follow_up else terms
		size = COMPACT_FOLLOW_UP_CHARS if follow_up else COMPACT_RESULT_CHARS
		blocks.append(_compact_result_text(position, result, result_terms or terms, size))
	text = "\n".join(header) + ("\n\n" if header else "") + "\n\n".join(blocks)
	if structured.get("uncoveredTerms"):
		text += "\n\nNot found in the returned text: " + ", ".join(structured["uncoveredTerms"]) + "."
	return text


async def _run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
	try:
		query, requested_top_k, family = _parse_input(args)
		top_k = min(requested_top_k, MAX_TOP_K)
		retrieval_query = _retrieval_query(args, query)
		detected = None
		board_result = board_evidence(args, query, requested_top_k)
		if board_result is not None:
			board_family = _family_from_text(board_result["board"] or "")
			if args.get("family") and board_family and _family_from_text(args["family"]) != board_family:
				raise ValueError("board and family refer to different AURIX generations")
			results = board_result["results"]
		else:
			index_path = _resolve_index_path(args.get("indexPath"), family)
			results = search_results(index_path, retrieval_query, limit=top_k, follow_up=True)
			primary = [result for result in results if result.get("retrievalPass") != "follow_up"]
			follow_ups = [result for result in results if result.get("retrievalPass") == "follow_up"]
			named_board = explicit_board(args, query)
			if named_board:
				# A named board adds its manual text ahead of chip results; it never replaces them entirely.
				hardware_version = None if revision_independent(named_board) else query_hardware_version(args, query)
				detected = None if hardware_version or revision_independent(named_board) else detected_hardware_version(named_board)
				if detected:
					hardware_version = detected["hardwareVersion"]
				board_text = board_manual_text(args, query, max(1, (top_k + 1) // 2), named_board, hardware_version)
				primary = (board_text + primary)[:top_k]
				seen = {result["chunk_id"] for result in primary}
				board_follow_ups = []
				for follow_up in follow_up_queries(retrieval_query):
					# The best page for a clause is often already a primary hit; take the best unseen one.
					candidates = board_manual_text(args, follow_up, len(seen) + 1, named_board, hardware_version)
					result = next((item for item in candidates if item["chunk_id"] not in seen), None)
					if result is not None:
						seen.add(result["chunk_id"])
						board_follow_ups.append({**result, "retrievalPass": "follow_up", "followUpQuery": follow_up})
				# Board-manual clauses first; chip follow-ups only fill the remaining slots.
				follow_ups = (board_follow_ups + [
					result for result in follow_ups if result["chunk_id"] not in seen
				])[:FOLLOW_UP_MAX_RESULTS]
			results = primary + follow_ups
		structured = {
			"query": query,
			"family": family,
			"resultCount": len(results),
			"abstained": not results,
			"results": results,
		}
		if detected:
			structured["hardwareVersionDetected"] = detected
		if board_result is None:
			structured["retrievalQuery"] = retrieval_query
			structured["evidenceStatus"] = "not_assessed" if results else "no_evidence"
			structured["evidencePolicy"] = {
				"maxTotalTextChars": EVIDENCE_TOTAL_CHARS, "maxChunkTextChars": EVIDENCE_CHARS_PER_CHUNK,
				"maxNeighborsPerHit": MAX_EVIDENCE_NEIGHBORS,
				"neighborScope": "same_section_source_version_adjacent_page",
			}
			structured["evidenceGuidance"] = (
			    "Hits and adjacent chunks are evidence candidates, not an assurance of a complete answer. "
			    "Verify device, document revision, silicon stepping, units, conditions and errata. "
			    "Long questions are automatically re-searched per clause with keyword follow-up queries; "
			    "those hits are marked as follow-up results. Do not state facts about uncoveredTerms "
			    "unless the returned text supports them."
			)
			if results:
				structured["followUpQueries"] = follow_up_queries(retrieval_query)
				structured.update(coverage_hints(retrieval_query, results))
		board_guidance = board_text_guidance(results)
		if board_guidance:
			structured["boardTextGuidance"] = board_guidance
		if board_result is not None:
			structured.update(board_result)
			structured["abstained"] = not any(result["facts"] for result in results)
			structured["family"] = _family_from_text(board_result["board"] or "") or family
		if not results:
			if args.get("detail", "compact") == "compact":
				structured = _compact_structured(structured)
			return ToolResult.text(
				f'No supported documentation evidence found for "{query}". {structured.get("reason", "")}',
				structured=structured,
			)
		if args.get("detail", "compact") == "compact":
			text = _compact_text(structured, retrieval_query, board_result is None)
			# VS Code gives the model only structuredContent when present, so the evidence text must be in it too.
			return ToolResult.text(text, structured={**_compact_structured(structured), "text": text})

		text = "\n\n".join(
			(
				f'[{position}] Follow-up query "{result["followUpQuery"]}": {_evidence_text(result)}'
				if result.get("retrievalPass") == "follow_up"
				else f"[{position}] {_evidence_text(result)}"
			)
			for position, result in enumerate(results, start=1)
		)
		if structured.get("uncoveredTerms"):
			text += "\n\nNot found in the returned text: " + ", ".join(structured["uncoveredTerms"]) + "."
		if "boardTextGuidance" in structured:
			text = structured["boardTextGuidance"] + "\n\n" + text
		if board_result is None:
			text = structured["evidenceGuidance"] + "\n\n" + text
		return ToolResult.text(text, structured=structured)
	except Exception as error:
		return ToolResult.text(
			f"documentation_search error: {safe_error_message(error)}",
			is_error=True,
		)


async def _read_run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
	try:
		for key in ("device", "family", "indexPath"):
			if args.get(key) is not None and not isinstance(args[key], str):
				raise ValueError(f"{key} must be a string")
		family = _resolve_family(args, "")
		query = _retrieval_query(args, "")
		databases = []
		try:
			databases.append(_resolve_index_path(args.get("indexPath"), family))
		except FileNotFoundError:
			if args.get("indexPath"):
				raise
		# Board-manual text excerpts carry chunkIds from the separate board-text index.
		if not args.get("indexPath") and BOARD_TEXT_INDEX.is_file():
			databases.append(BOARD_TEXT_INDEX)
		if not databases:
			raise FileNotFoundError("Documentation index was not found; pass device/family or indexPath.")
		evidence = None
		for position, database in enumerate(databases):
			try:
				evidence = read_chunk(
					database, args.get("chunkId"), query, args.get("offset", 0), args.get("maxChars", 8000),
					allow_board_text=True,
				)
				break
			except ChunkNotFoundError:
				if position == len(databases) - 1:
					raise
		board_text = bool(evidence.pop("boardManualText", False))
		citation = {key: value for key, value in evidence["citation"].items() if key != "excerpt"}
		# The chunk text is returned once, in the text content.
		structured = {
			**{key: value for key, value in evidence.items() if key not in ("text", "citation")},
			"citation": citation, "family": family, "evidenceStatus": "not_assessed",
			"applicability": "requires_verification",
		}
		text = "Verify device, stepping, operating conditions and applicable errata.\n\n"
		if board_text:
			versions = citation.get("hardware_versions") or []
			any_revision = revision_independent(citation.get("board"))
			detected = None if any_revision else detected_hardware_version(citation.get("board") or "")
			known = any_revision or (bool(detected) and any(
				hardware_version_matches(detected["hardwareVersion"], version) for version in versions
			))
			structured.update(
				usableForCodeGeneration=known,
				usageRestriction=BOARD_TEXT_CITE_PAGE if known else BOARD_TEXT_VERSION_REQUIRED,
				applicability="board_manual_text" if known else "hardware_version_required",
			)
			if detected:
				structured["hardwareVersionDetected"] = detected
			text = (BOARD_TEXT_GUIDANCE if known else (
				f'Board-manual text for hardware revision {", ".join(versions)}: use it for code generation with a '
				"page citation when the board is that revision (as reported by documentation_search or "
				"flash_list_devices); ask the user only if no matching kit is connected."
			)) + "\n\n"
		text += _citation_text({
			"citation": evidence["citation"], "applicability": structured["applicability"],
			"usableForCodeGeneration": structured.get("usableForCodeGeneration", False),
			"usageRestriction": structured.get("usageRestriction"), "bplCheck": "not_applicable",
		})
		if evidence["truncated"]:
			text += f'\nContinue with offset={evidence["nextOffset"]}.'
		# VS Code gives the model only structuredContent when present, so the chunk text must be in it too.
		structured["text"] = evidence["text"]
		return ToolResult.text(text, structured=structured)
	except Exception as error:
		return ToolResult.text(f"documentation_read error: {safe_error_message(error)}", is_error=True)
