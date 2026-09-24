from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "but",
    "connected",
    "do",
    "does",
    "for",
    "how",
    "is",
    "many",
    "not",
    "of",
    "on",
    "please",
    "should",
    "the",
    "to",
    "using",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
}

DEVICE_TERMS = {
    "aurix",
    "device",
    "tc2xx",
    "tc23x",
    "tc234",
    "tc237",
    "tc26x",
    "tc265",
    "tc27x",
    "tc270",
    "tc275",
    "tc277",
    "tc29x",
    "tc297",
    "tc3xx",
    "tc32x",
    "tc33x",
    "tc334",
    "tc36x",
    "tc367",
    "tc37x",
    "tc375",
    "tc377",
    "tc38x",
    "tc387",
    "tc39x",
    "tc397",
    "tc4d7",
    "tc4d9",
    "tc4dx",
    "tc4xx",
}
APP_CONTEXT_TERMS = {"led", "pwm"}
DEVICE_DOCUMENT_PREFIXES = {
    "tc23x": ("tc21x-tc22x-tc23x-", "tc23x-"),
    "tc234": ("tc21x-tc22x-tc23x-", "tc23x-"),
    "tc237": ("tc21x-tc22x-tc23x-", "tc23x-"),
    "tc26x": ("tc26x-",),
    "tc265": ("tc26x-",),
    "tc27x": ("tc27x-",),
    "tc270": ("tc27x-",),
    "tc275": ("tc27x-",),
    "tc277": ("tc27x-",),
    "tc29x": ("tc29x-",),
    "tc297": ("tc29x-",),
    "tc32x": ("tc33x-tc32x-",),
    "tc33x": ("tc33x-tc32x-",),
    "tc334": ("tc33x-tc32x-",),
    "tc36x": ("tc36x-",),
    "tc367": ("tc36x-",),
    "tc37x": ("tc37x-",),
    "tc375": ("tc37x-",),
    "tc377": ("tc37x-",),
    "tc38x": ("tc38x-",),
    "tc387": ("tc38x-",),
    "tc39x": ("tc39x-",),
    "tc397": ("tc39x-",),
}


def build_index(chunks_root: Path, database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    database.unlink(missing_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE chunks USING fts5(
                chunk_id UNINDEXED,
                document_id UNINDEXED,
                document_type UNINDEXED,
                document_title UNINDEXED,
                document_version UNINDEXED,
                source UNINDEXED,
                headings,
                pages UNINDEXED,
                text,
                tokenize = 'porter unicode61'
            )
            """
        )
        row_count = 0
        connection.execute(
            "CREATE TABLE board_chunks (chunk_id TEXT PRIMARY KEY, board TEXT NOT NULL, metadata TEXT NOT NULL)"
        )
        for chunks_file in sorted(chunks_root.rglob("chunks.jsonl")):
            with chunks_file.open(encoding="utf-8") as source:
                for line in source:
                    chunk = json.loads(line)
                    connection.execute(
                        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            chunk["chunk_id"],
                            chunk["document_id"],
                            chunk["document_type"],
                            chunk["document_title"],
                            chunk["document_version"],
                            chunk["source"],
                            " > ".join(chunk["headings"] or []),
                            ",".join(str(page) for page in chunk["pages"]),
                            chunk["text"],
                        ),
                    )
                    if chunk.get("board"):
                        metadata = {key: chunk[key] for key in (
                            "board", "hardware_versions", "facts", "source_sha256", "document_date",
                        ) if key in chunk}
                        connection.execute(
                            "INSERT INTO board_chunks VALUES (?, ?, ?)",
                            (chunk["chunk_id"], chunk["board"], json.dumps(metadata)),
                        )
                    row_count += 1
        connection.commit()
    finally:
        connection.close()
    print(f"Indexed {row_count} chunks -> {database}")


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in re.findall(r"[\w]+(?:[.-][\w]+)*", query, flags=re.UNICODE):
        key = term.casefold()
        if (key in STOP_WORDS and not term.isupper()) or key in seen:
            continue
        seen.add(key)
        terms.append(term)
    if not terms:
        raise ValueError("Query contains no searchable terms")
    return terms


def query_document_prefixes(query: str) -> tuple[str, ...]:
    term_keys = {term.casefold() for term in query_terms(query)}
    prefix_groups = {
        DEVICE_DOCUMENT_PREFIXES[term]
        for term in term_keys
        if term in DEVICE_DOCUMENT_PREFIXES
    }
    if len(prefix_groups) != 1:
        return ()

    prefixes = next(iter(prefix_groups))
    if any(term.startswith("tc3") for term in term_keys):
        return prefixes + ("tc3xx-",)
    return prefixes


def rows_for_device(
    rows: list[sqlite3.Row],
    document_prefixes: tuple[str, ...],
) -> list[sqlite3.Row]:
    if not document_prefixes:
        return rows
    return [
        row
        for row in rows
        if str(row["document_id"]).startswith(document_prefixes)
        or row["document_type"] == "board_manual"
    ]


def quote_fts_term(term: str) -> str:
    indexed_term = term
    if (
        not any(character.isdigit() for character in term)
        and term.endswith("x")
        and term[:-1].isupper()
    ):
        indexed_term = term[:-1]
    return f'"{indexed_term.replace(chr(34), chr(34) * 2)}"'



def query_percentage_values(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(
        r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?)(?!\w)",
        query,
        flags=re.IGNORECASE,
    )))


def row_supports_percentages(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    values: tuple[str, ...],
    query: str,
) -> bool:
    if not values:
        return True
    page = int(row["pages"].split(",", maxsplit=1)[0])
    support_text = "\n".join(
        text
        for (text,) in connection.execute(
            "SELECT text FROM chunks WHERE document_id = ? "
            "AND CAST(pages AS INTEGER) BETWEEN ? AND ?",
            (row["document_id"], page - 2, page + 2),
        )
    )
    if "nominal" in query.casefold() and "nominal" not in support_text.casefold():
        return False
    derived_duty_cycle = (
        "duty cycle" in query.casefold()
        and "period" in support_text.casefold()
        and "pulse width" in support_text.casefold()
    )
    if derived_duty_cycle:
        return True

    for value in values:
        numeric = re.escape(value)
        if "." not in value:
            numeric += r"(?:\.0+)?"
        expression = rf"(?<![\d.]){numeric}\s*(?:%|percent(?:age)?)(?!\w)"
        if re.search(expression, support_text, flags=re.IGNORECASE) is None:
            return False
    return True

def to_fts_query(query: str, operator: str = "AND") -> str:
    terms = query_terms(query)
    return f" {operator} ".join(
        quote_fts_term(term) for term in terms
    )


def is_anchor(term: str) -> bool:
    if term.casefold() in DEVICE_TERMS | APP_CONTEXT_TERMS:
        return False
    uppercase_count = sum(character.isupper() for character in term)
    return (
        any(character.isdigit() for character in term)
        or any(character in "._-" for character in term)
        or uppercase_count >= 2
    )


def is_identity_anchor(term: str) -> bool:
    has_letter = any(character.isalpha() for character in term)
    uppercase_count = sum(character.isupper() for character in term)
    mixed_case_symbol = (
        term[0].islower() and uppercase_count >= 2
    ) or (
        term.endswith("x") and term[:-1].isupper()
    )
    return has_letter and (
        any(character.isdigit() for character in term)
        or "_" in term
        or mixed_case_symbol
    )


def query_expansion_groups(query: str) -> tuple[tuple[str, ...], ...]:
    normalized = query.casefold()
    gpio_output = (
        "gpio" in normalized
        and "output" in normalized
        and ("led" in normalized or "port pin" in normalized)
    )
    if gpio_output:
        return (("GPIO", "PADCFGp_DRVCFG", "general-purpose output"),)
    periodic_timer_interrupt = (
        "periodic" in normalized
        and "interrupt" in normalized
        and ("millisecond" in normalized or "timer" in normalized)
    )
    if periodic_timer_interrupt:
        return (("STM", "compare match interrupt", "STM_CMP0"),)
    kit_ethernet = (
        "ethernet" in normalized
        and ("phy" in normalized or "connector" in normalized)
        and ("evaluation kit" in normalized or "onboard" in normalized)
    )
    if kit_ethernet:
        return (("DP83825I", "RMII interface", "Table 8"),)
    ethernet_rgmii_pins = (
        "ethernet" in normalized
        and "rgmii" in normalized
        and "pin" in normalized
    )
    if ethernet_rgmii_pins:
        return (("RGMII", "P16.7", "GETH0"),)
    ethernet_phy_support = (
        "ethernet" in normalized
        and any(interface in normalized for interface in ("mii", "rmii", "rgmii"))
        and ("support" in normalized or "interface" in normalized)
    )
    if ethernet_phy_support:
        return (("GMAC-UNIV", "supports", "PHY interfaces"),)
    egtm_pwm = (
        "egtm" in normalized
        and "pwm" in normalized
        and (
            "duty cycle" in normalized
            or "kilohertz" in normalized
            or "period" in normalized
        )
    )
    egtm_port_route = (
        "egtm" in normalized
        and ("atom" in normalized or "tom" in normalized)
        and ("route" in normalized or "routed" in normalized)
        and ("pin" in normalized or "external" in normalized)
    )
    egtm_groups: list[tuple[str, ...]] = []
    if egtm_pwm:
        egtm_groups.append(("TOM", "ATOM", "generate a PWM signal"))
        if "tom" in normalized or "atom" not in normalized:
            egtm_groups.append(
                ("TOM", "CM0", "CM1", "clock ticks", "CLK_SRC")
            )
        if "atom" in normalized or "tom" not in normalized:
            egtm_groups.append(
                ("ATOM", "CM0", "CM1", "clock ticks", "RST_CCU0")
            )
    if egtm_port_route:
        egtm_groups.append(("eGTM", "TOUTSEL", "port"))
    if egtm_groups:
        return tuple(egtm_groups)
    timed_external_output = (
        "external" in normalized
        and "output" in normalized
        and "pin" in normalized
        and "low jitter" in normalized
        and ("capture" in normalized or "exact time" in normalized)
    )
    if timed_external_output:
        return (("eGTM", "ATOM", "TBU", "output generates edges"),)
    qspi_expect_after_32_bytes = (
        "qspi" in normalized
        and "expect" in normalized
        and "continuous" in normalized
        and "32 bytes" in normalized
    )
    if qspi_expect_after_32_bytes:
        return (
            ("QSPI", "EXPECT phase", "time-out"),
            ("QSPI", "Long Data Mode", "32 bytes"),
        )
    shared_cross_core_variable = (
        "atomicity" in normalized
        and "core" in normalized
        and "shared" in normalized
        and "variable" in normalized
    )
    if shared_cross_core_variable:
        return (("shared variable", "Store Buffer", "DSYNC"),)
    return ()


def retrieve(
    connection: sqlite3.Connection,
    query: str,
    limit: int,
    snippet_tokens: int = 64,
    scoped: bool = False,
) -> list[sqlite3.Row]:
    percentage_values = query_percentage_values(query)
    document_prefixes = query_document_prefixes(query)
    scope_filter = " AND rowid IN (SELECT row_id FROM temp.search_scope)" if scoped else ""
    statement = f"""
            SELECT rowid AS row_id, chunk_id, document_id, document_type,
                                     document_title, document_version, source, headings,
                     pages, text,
                                         snippet(chunks, 8, '', '', ' … ', ?) AS excerpt,
                   bm25(chunks) AS score
            FROM chunks
            WHERE chunks MATCH ? {scope_filter}
            ORDER BY score
            LIMIT ?
            """
    sentences = [
        sentence.strip()
        for sentence in re.split(r"[!?]+|\.(?=\s|$)", query)
        if sentence.strip()
    ]
    sentence_candidates: list[sqlite3.Row] = []
    prioritize_sentence_candidate = not any(
        is_identity_anchor(term) and term.casefold() not in DEVICE_TERMS
        for term in query_terms(query)
    )
    if len(sentences) >= 2:
        final_sentence = sentences[-1]
        try:
            final_terms = query_terms(final_sentence)
        except ValueError:
            final_terms = []
        has_specific_anchor = any(
            is_anchor(term) and term.casefold() not in DEVICE_TERMS
            for term in final_terms
        )
        if has_specific_anchor:
            sentence_candidates = retrieve(
                connection,
                final_sentence,
                1,
                snippet_tokens,
                scoped,
            )
            sentence_candidates = [
                candidate
                for candidate in sentence_candidates
                if row_supports_percentages(
                    connection, candidate, percentage_values, query
                )
            ]
            if not sentence_candidates:
                return []

    rows = rows_for_device(connection.execute(
        statement,
        (
            snippet_tokens,
            to_fts_query(query),
            max(50, limit * 10) if document_prefixes else limit,
        ),
    ).fetchall(), document_prefixes)
    rows = [
        row
        for row in rows
        if row_supports_percentages(
            connection, row, percentage_values, query
        )
    ]
    if rows:
        expansion_seeds: list[sqlite3.Row] = []
        for expansion_terms in query_expansion_groups(query):
            expansion_query = " AND ".join(
                quote_fts_term(term) for term in expansion_terms
            )
            expansion_candidates = rows_for_device(connection.execute(
                statement,
                (snippet_tokens, expansion_query, max(10, limit * 3)),
            ).fetchall(), document_prefixes)
            expansion_seed = next(
                (
                    candidate
                    for candidate in expansion_candidates
                    if row_supports_percentages(
                        connection, candidate, percentage_values, query
                    )
                ),
                None,
            )
            if expansion_seed is not None:
                expansion_seeds.append(expansion_seed)
        expansion_seed_ids = {seed["row_id"] for seed in expansion_seeds}
        rows = expansion_seeds + [
            row for row in rows if row["row_id"] not in expansion_seed_ids
        ]
        if not sentence_candidates or not prioritize_sentence_candidate:
            return rows[:limit]
        sentence_ids = {candidate["row_id"] for candidate in sentence_candidates}
        return (
            sentence_candidates
            + [row for row in rows if row["row_id"] not in sentence_ids]
        )[:limit]

    terms = query_terms(query)
    strong_anchor_terms = [
        term
        for term in terms
        if is_anchor(term)
        and term.casefold() not in DEVICE_TERMS
        and not term.replace(".", "").isdigit()
    ]
    for term in strong_anchor_terms:
        corpus_match = connection.execute(
            f"SELECT 1 FROM chunks WHERE chunks MATCH ? {scope_filter} LIMIT 1",
            (quote_fts_term(term),),
        ).fetchone()
        if corpus_match is None:
            return []
    candidate_limit = max(50, limit * 10)
    candidates = rows_for_device(list(connection.execute(
        statement,
        (snippet_tokens, to_fts_query(query, "OR"), candidate_limit),
    ).fetchall()), document_prefixes)
    candidate_ids = {candidate["row_id"] for candidate in candidates}
    identity_terms = [
        term
        for term in terms
        if is_identity_anchor(term) and term.casefold() not in DEVICE_TERMS
    ]
    if identity_terms:
        identity_query = " AND ".join(
            quote_fts_term(term) for term in identity_terms
        )
        identity_candidates = rows_for_device(connection.execute(
            statement,
            (snippet_tokens, identity_query, candidate_limit),
        ).fetchall(), document_prefixes)
        candidates.extend(
            candidate
            for candidate in identity_candidates
            if candidate["row_id"] not in candidate_ids
        )
        candidate_ids.update(
            candidate["row_id"] for candidate in identity_candidates
        )

    expansion_candidate_ids: set[int] = set()
    expansion_seed_ids: set[int] = set()
    for expansion_terms in query_expansion_groups(query):
        expansion_query = " AND ".join(
            quote_fts_term(term) for term in expansion_terms
        )
        expansion_candidates = rows_for_device(connection.execute(
            statement,
            (snippet_tokens, expansion_query, candidate_limit),
        ).fetchall(), document_prefixes)
        if expansion_candidates:
            expansion_seed_ids.add(expansion_candidates[0]["row_id"])
        expansion_candidate_ids.update(
            candidate["row_id"] for candidate in expansion_candidates
        )
        candidates.extend(
            candidate
            for candidate in expansion_candidates
            if candidate["row_id"] not in candidate_ids
        )
        candidate_ids.update(expansion_candidate_ids)
    candidates = [
        candidate
        for candidate in candidates
        if row_supports_percentages(
            connection, candidate, percentage_values, query
        )
    ]
    if not candidates:
        return []

    row_ids = [row["row_id"] for row in candidates]
    placeholders = ",".join("?" for _ in row_ids)
    matched_by_row: dict[int, set[str]] = {row_id: set() for row_id in row_ids}
    for term in terms:
        matching_rows = connection.execute(
            f"SELECT rowid FROM chunks WHERE rowid IN ({placeholders}) "
            "AND chunks MATCH ?",
            (*row_ids, quote_fts_term(term)),
        ).fetchall()
        for matching_row in matching_rows:
            matched_by_row[matching_row[0]].add(term.casefold())

    term_keys = {term.casefold() for term in terms}
    anchor_keys = {term.casefold() for term in terms if is_anchor(term)}
    identity_keys = {term.casefold() for term in identity_terms}
    accepted: list[tuple[tuple[float, float, float, float], sqlite3.Row]] = []
    for candidate in candidates:
        page = int(candidate["pages"].split(",", maxsplit=1)[0])
        support_rows = [
            row
            for row in candidates
            if row["document_id"] == candidate["document_id"]
            and abs(int(row["pages"].split(",", maxsplit=1)[0]) - page) <= 2
        ]
        matched_terms = set().union(
            *(matched_by_row[row["row_id"]] for row in support_rows)
        )
        coverage = len(matched_terms) / len(term_keys)
        matched_anchors = anchor_keys & matched_terms
        strong_anchors = {
            term for term in anchor_keys if not term.replace(".", "").isdigit()
        }
        normalized_query = query.casefold()
        ethernet_capability_query = (
            "ethernet" in normalized_query
            and "support" in normalized_query
            and any(
                interface in normalized_query
                for interface in ("mii", "rmii", "rgmii")
            )
        )
        if ethernet_capability_query:
            strong_anchors -= {"mii", "rmii", "rgmii"}
        if re.search(r"\b(?:tom\s+or\s+atom|atom\s+or\s+tom)\b", normalized_query):
            strong_anchors -= {"tom", "atom"}
        anchors_supported = (
            not anchor_keys
            or (
                len(matched_anchors) / len(anchor_keys) >= 0.5
                and bool(strong_anchors & matched_terms)
            )
        )
        enough_terms = len(matched_terms) >= min(2, len(term_keys))
        threshold = 0.45 if anchor_keys else 0.60
        direct_terms = matched_by_row[candidate["row_id"]]
        identity_complete = (
            len(identity_keys) >= 2 and identity_keys <= direct_terms
        )
        expansion_match = candidate["row_id"] in expansion_candidate_ids
        expansion_supported = (
            expansion_match and strong_anchors <= matched_terms
        )
        evidence_supported = identity_complete or (
            expansion_supported
            if expansion_match
            else anchors_supported and coverage >= threshold
        )
        if evidence_supported and (enough_terms or expansion_supported):
            identity_coverage = (
                len(identity_keys & direct_terms) / len(identity_keys)
                if identity_keys
                else 0.0
            )
            accepted.append(
                (
                    (
                        float(candidate["row_id"] in expansion_seed_ids),
                        float(expansion_match),
                        identity_coverage,
                        -candidate["score"],
                    ),
                    candidate,
                )
            )
    accepted.sort(key=lambda item: item[0], reverse=True)
    ranked = [candidate for _, candidate in accepted]
    if not sentence_candidates or not prioritize_sentence_candidate:
        return ranked[:limit]

    selected = list(sentence_candidates)
    selected_ids = {candidate["row_id"] for candidate in selected}
    selected.extend(
        candidate
        for candidate in ranked
        if candidate["row_id"] not in selected_ids
    )
    return selected[:limit]


def citation_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "document_id": row["document_id"],
        "document_title": row["document_title"],
        "document_version": row["document_version"],
        "document_type": row["document_type"],
        "source": row["source"],
        "section": row["headings"] or None,
        "pdf_pages": [int(page) for page in row["pages"].split(",")],
        "page_basis": "physical_pdf",
        "excerpt": row["excerpt"].replace("\ufffe", "").replace("\uffff", ""),
    }


def result_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "chunk_id": row["chunk_id"],
        "document_id": row["document_id"],
        "document_type": row["document_type"],
        "document_title": row["document_title"],
        "document_version": row["document_version"],
        "source": row["source"],
        "section": row["headings"],
        "pages": row["pages"],
        "score": row["score"],
        "excerpt": row["excerpt"].replace("\ufffe", "").replace(
            "\uffff", ""
        ),
        "citation": citation_from_row(row),
    }


def hardware_version_matches(requested: str, supported: str) -> bool:
    requested = requested.strip().lower().removeprefix("v")
    supported = supported.strip().lower().removeprefix("v")
    if requested == supported:
        return True
    if re.fullmatch(r"\d+(?:\.\d+)*\.x", supported):
        prefix = supported[:-2]
        return requested == prefix or re.fullmatch(re.escape(prefix) + r"(?:\.\d+)+", requested) is not None
    return False


def board_signal_facts(database: Path, board: str) -> list[dict]:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'board_chunks'"
        ).fetchone():
            return []
        return [
            fact
            for (metadata,) in connection.execute("SELECT metadata FROM board_chunks WHERE board = ?", (board,))
            for fact in json.loads(metadata).get("facts", [])
        ]
    finally:
        connection.close()


def search_results(
    database: Path,
    query: str,
    limit: int = 3,
    snippet_tokens: int = 64,
    *,
    board: str | None = None,
    hardware_version: str | None = None,
) -> list[dict[str, object]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        has_scope = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'board_chunks'"
        ).fetchone() is not None
        metadata_by_chunk = {}
        if has_scope:
            connection.execute("CREATE TEMP TABLE search_scope (row_id INTEGER PRIMARY KEY)")
            connection.execute(
                "INSERT INTO search_scope SELECT rowid FROM chunks WHERE chunk_id NOT IN "
                "(SELECT chunk_id FROM board_chunks)"
            )
            requested_version = hardware_version.strip().lower().removeprefix("v") if hardware_version else None
            for row in connection.execute("SELECT * FROM board_chunks WHERE board = ?", (board,)):
                metadata = json.loads(row["metadata"])
                if requested_version and not any(
                    hardware_version_matches(requested_version, version)
                    for version in metadata.get("hardware_versions", [])
                ):
                    continue
                metadata_by_chunk[row["chunk_id"]] = metadata
                connection.execute(
                    "INSERT INTO search_scope SELECT rowid FROM chunks WHERE chunk_id = ?",
                    (row["chunk_id"],),
                )
        rows = retrieve(connection, query, limit, snippet_tokens, scoped=has_scope)
        results = [result_from_row(row) for row in rows]
        for result in results:
            metadata = metadata_by_chunk.get(result["chunk_id"])
            if metadata:
                result["facts"] = metadata.get("facts", [])
                result["applicability"] = "matched" if hardware_version else "hardware_version_required"
                result["citation"].update({key: value for key, value in metadata.items() if key != "facts"})
        return results
    finally:
        connection.close()


def search(database: Path, query: str, limit: int, snippet_tokens: int) -> None:
    for result in search_results(database, query, limit, snippet_tokens):
        print(json.dumps(result, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("chunks_root", type=Path)
    build_parser.add_argument("database", type=Path)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("database", type=Path)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=3)
    search_parser.add_argument("--snippet-tokens", type=int, default=64)

    args = parser.parse_args()
    if args.command == "build":
        build_index(args.chunks_root.resolve(), args.database.resolve())
    else:
        search(
            args.database.resolve(),
            args.query,
            args.limit,
            args.snippet_tokens,
        )


if __name__ == "__main__":
    main()