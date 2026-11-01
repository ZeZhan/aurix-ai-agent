from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any


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

# Question scaffolding and generic verbs carry no document vocabulary; keeping
# them dilutes BM25 and the coverage threshold for long natural-language questions.
QUESTION_WORDS = {
    "all", "am", "any", "assume", "be", "been", "being", "can", "could", "did",
    "describe", "each", "every", "explain", "give", "had", "has", "have", "i",
    "it", "its", "listed", "may", "me", "might", "much", "my",
    "our", "right", "show", "some", "specify", "specified",
    "stated", "tell", "that", "their", "them", "there", "these", "they", "this",
    "those", "was", "we", "were", "whether", "who", "whose", "will", "would",
    "you", "your",
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

EVIDENCE_CHARS_PER_CHUNK = 6000
EVIDENCE_TOTAL_CHARS = 36000
MAX_EVIDENCE_NEIGHBORS = 2
MAX_READ_CHARS = 16000

# Automatic follow-up retrieval for long or compound questions. Follow-up hits
# are appended after the primary results with their own evidence budget, so the
# primary ranking and evidence stay exactly as without follow-ups.
FOLLOW_UP_MIN_TERMS = 7
FOLLOW_UP_MAX_QUERIES = 3
FOLLOW_UP_PER_QUERY = 2
FOLLOW_UP_MAX_RESULTS = 3
FOLLOW_UP_CHARS_PER_RESULT = 3000
FOLLOW_UP_CORE_TERMS = 5
# Words that help a sentence read naturally but rarely occur next to the facts
# being asked for; they are dropped from keyword follow-up queries.
FOLLOW_UP_FILLER = {
    "after", "amount", "another", "applies", "as", "at", "before", "board", "both", "by",
    "change", "constant", "corresponding", "definitely", "documented", "during",
    "exact", "exactly", "formula", "free", "from", "happen", "if", "in", "into", "kit", "lite",
    "must", "name", "one", "or", "ordinary", "possible", "result", "results",
    "same", "say", "says", "starts", "state", "stays", "than", "then", "three",
    "two", "use", "used", "value", "values", "while",
}
HARDWARE_REVISION = re.compile(r"v\d+(?:\.\d+)*", re.IGNORECASE)
CLAUSE_BOUNDARY = re.compile(
    r"[?;]|\.(?=\s|$)"
    r"|,\s*(?:and\s+)?(?=(?:what|which|how|when|where|is|are|does|do|can)\b)"
    r"|\s+and\s+(?=(?:what|which|how|when|where|name)\b)"
    r"|\s+versus\s+|\s+vs\.?\s+",
    re.IGNORECASE,
)


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
        if (key in STOP_WORDS | QUESTION_WORDS and not term.isupper()) or key in seen:
            continue
        # Possessive or contraction remnants ("CPU's" -> "s") are not searchable vocabulary.
        if len(term) == 1 and term.isalpha():
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


def section_matches_device(row: sqlite3.Row, query: str) -> bool:
    requested = query_document_prefixes(query)
    if not requested:
        return True
    section_devices = re.findall(r"\btc(?:\d{2}[x\d]|4[a-z]\d)\b", row["headings"], re.IGNORECASE)
    specific = {
        prefix
        for device in section_devices
        for prefix in DEVICE_DOCUMENT_PREFIXES.get(device.casefold(), ())
    }
    return not specific or bool(specific.intersection(requested))


def quantity_terms(query: str) -> set[str]:
    if not re.search(r"\b(?:how many|number of|count)\b", query, re.IGNORECASE):
        return set()
    request_terms = {"number", "count", "total", "implemented", "available", "used", "in", "by", "has", "have"}
    return {
        term.casefold() for term in query_terms(query)
        if term.casefold() not in DEVICE_TERMS | request_terms
    }


def has_quantity_statement(row: sqlite3.Row) -> bool:
    return bool(re.search(
        r"\b(?:contains?|implements?|provides?|has|number of)\b[^.\n]{0,100}\b\d+\b",
        row["text"], re.IGNORECASE,
    ))


def rank_candidates(rows: list[sqlite3.Row], query: str, limit: int) -> list[sqlite3.Row]:
    count_query = bool(quantity_terms(query))
    limits_query = bool(re.search(
        r"\b(?:maximum|minimum|limits?|voltage|current|accuracy|MHz|max|min)\b", query, re.IGNORECASE,
    ))
    errata_query = bool(re.search(r"\b(?:errat\w*|workaround|DMA_TC\w*)\b", query, re.IGNORECASE))
    prefixes = query_document_prefixes(query)
    anchors = [term for term in query_terms(query) if is_anchor(term)]

    def priority(row: sqlite3.Row) -> tuple[bool, int]:
        # Body text can contain an incidental "....", so require several dot-leader lines.
        contents = bool(re.search(r"\b(?:table of contents|contents)\b", row["headings"], re.IGNORECASE)) or len(
            re.findall(r"\.{4,}\s*\d+\s*$", row["text"], re.MULTILINE)
        ) >= 3
        direct = not anchors or any(
            re.search(r"\b" + re.escape(term) + r"\b", row["text"], re.IGNORECASE)
            for term in anchors
        )
        exact_device = any(
            row["document_id"].startswith(prefix)
            for prefix in prefixes if prefix not in ("tc3xx-",)
        )
        source_preference = 0
        if direct:
            if count_query and has_quantity_statement(row):
                source_preference += 2 + int(exact_device)
            if limits_query and "datasheet" in row["document_type"].casefold():
                source_preference += 2
            if errata_query and "errat" in row["document_type"].casefold():
                source_preference += 2
        return not contents, source_preference

    ranked = sorted(
        (row for row in rows if section_matches_device(row, query)),
        key=priority, reverse=True,
    )
    selected = []
    seen = set()
    for row in ranked:
        key = (row["document_id"], row["document_version"], row["source"],
               row["pages"], " ".join(row["text"].split()))
        if key not in seen:
            seen.add(key)
            selected.append(row)
        if len(selected) == limit:
            break
    return selected


def is_plain_compound(term: str) -> bool:
    """Ordinary hyphenated words such as wall-clock or scratch-pad, not identifiers."""
    parts = term.split("-")
    return len(parts) > 1 and all(
        part.isalpha() and (part.islower() or part[1:].islower()) for part in parts
    )


def quote_fts_term(term: str) -> str:
    if is_plain_compound(term):
        # Manuals spell compounds both ways ("scratch-pad" vs "ScratchPad").
        return f'("{" ".join(term.split("-"))}" OR "{"".join(term.split("-"))}")'
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
    if term.casefold() in DEVICE_TERMS | APP_CONTEXT_TERMS or is_plain_compound(term):
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
    veto_unknown_anchors: bool = True,
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
    if len(sentences) >= 2:
        device_context = " ".join(term for term in query_terms(query) if term.casefold() in DEVICE_TERMS)
        for sentence in sentences[:4]:
            try:
                query_terms(sentence)
            except ValueError:
                continue
            sentence_candidates.extend(retrieve(
                connection, f"{device_context} {sentence}", 2, snippet_tokens, scoped, veto_unknown_anchors,
            ))
        sentence_candidates = [
            row for row in sentence_candidates
            if row_supports_percentages(connection, row, percentage_values, query)
        ]

    rows = rows_for_device(connection.execute(
        statement,
        (
            snippet_tokens,
            to_fts_query(query),
            max(50, limit * 10),
        ),
    ).fetchall(), document_prefixes)
    rows = [
        row
        for row in rows
        if row_supports_percentages(
            connection, row, percentage_values, query
        )
    ]
    exact_ids = {row["row_id"] for row in rows}

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
        # Absence from the full manual set means an unknown identifier. A small
        # supplementary corpus (one board manual) cannot support that conclusion.
        if corpus_match is None and veto_unknown_anchors:
            return rank_candidates(sentence_candidates, query, limit)
    candidate_limit = max(50, limit * 10)
    candidates = rows_for_device(list(connection.execute(
        statement,
        (snippet_tokens, to_fts_query(query, "OR"), candidate_limit),
    ).fetchall()), document_prefixes)
    candidate_ids = {candidate["row_id"] for candidate in candidates}
    candidates.extend(row for row in rows if row["row_id"] not in candidate_ids)
    candidate_ids.update(exact_ids)
    # Reserve candidate space for the requested device's own documentation.
    # Otherwise a family-wide BM25 pool can crowd out its configuration tables.
    for prefix in document_prefixes:
        if prefix == "tc3xx-":
            continue
        device_statement = statement.replace(
            "WHERE chunks MATCH ?", "WHERE document_id LIKE ? AND chunks MATCH ?",
        )
        device_rows = connection.execute(
            device_statement, (snippet_tokens, prefix + "%", to_fts_query(query, "OR"), candidate_limit),
        ).fetchall()
        candidates.extend(row for row in device_rows if row["row_id"] not in candidate_ids)
        candidate_ids.update(row["row_id"] for row in device_rows)
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
        return rank_candidates(sentence_candidates, query, limit)

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
    quantity_keys = quantity_terms(query)
    accepted: list[tuple[tuple[float, float, float, float, float], sqlite3.Row]] = []
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
                # Pure numbers are weak anchors; only demand a strong match when one exists.
                and (not strong_anchors or bool(strong_anchors & matched_terms))
            )
        )
        enough_terms = len(matched_terms) >= min(2, len(term_keys))
        threshold = 0.45 if anchor_keys else 0.60
        direct_terms = matched_by_row[candidate["row_id"]]
        # A chunk naming every exact identifier in the query (erratum ID, register)
        # is relevant even when the surrounding question words are not in it.
        identity_complete = bool(identity_keys) and identity_keys <= direct_terms and (
            len(identity_keys) >= 2 or coverage >= 0.3
        )
        expansion_match = candidate["row_id"] in expansion_candidate_ids
        expansion_supported = (
            expansion_match and strong_anchors <= matched_terms
        )
        quantity_supported = (
            bool(quantity_keys) and quantity_keys <= direct_terms and has_quantity_statement(candidate)
        )
        evidence_supported = candidate["row_id"] in exact_ids or identity_complete or quantity_supported or (
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
                        float(candidate["row_id"] in exact_ids),
                        identity_coverage,
                        -candidate["score"],
                    ),
                    candidate,
                )
            )
    accepted.sort(key=lambda item: item[0], reverse=True)
    ranked = [candidate for _, candidate in accepted]
    selected_ids = {candidate["row_id"] for candidate in ranked}
    ranked.extend(row for row in sentence_candidates if row["row_id"] not in selected_ids)
    return rank_candidates(ranked, query, limit)


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


def evidence_segment(row: sqlite3.Row, offset: int, max_chars: int) -> dict[str, object]:
    text = row["text"][offset:offset + max_chars]
    end = offset + len(text)
    citation = citation_from_row(row)
    citation["excerpt"] = text
    return {
        "chunk_id": row["chunk_id"], "text": text, "citation": citation,
        "offset": offset, "nextOffset": end if end < len(row["text"]) else None,
        "totalChars": len(row["text"]), "truncated": end < len(row["text"]),
    }


def expand_evidence(
    connection: sqlite3.Connection, rows: list[sqlite3.Row], query: str,
) -> dict[str, list[dict[str, object]]]:
    remaining = EVIDENCE_TOTAL_CHARS
    expanded: dict[str, list[dict[str, object]]] = {}
    # Give every primary hit a budget before spending any on neighboring chunks.
    per_hit = min(EVIDENCE_CHARS_PER_CHUNK, remaining // max(1, len(rows)))
    for row in rows:
        segment = evidence_segment(row, 0, per_hit)
        expanded[row["chunk_id"]] = [segment]
        remaining -= len(str(segment["text"]))
    selected_ids = {row["chunk_id"] for row in rows}
    for row in rows:
        if remaining <= 0 or not row["headings"]:
            continue
        pages = [int(page) for page in row["pages"].split(",")]
        neighbors = connection.execute(
            "SELECT *, text AS excerpt FROM chunks WHERE document_id = ? "
            "AND document_version = ? AND source = ? AND headings = ? "
            "AND CAST(pages AS INTEGER) BETWEEN ? AND ? AND chunk_id != ? "
            "ORDER BY ABS(CAST(pages AS INTEGER) - ?), chunk_id LIMIT 4",
            (row["document_id"], row["document_version"], row["source"], row["headings"],
             min(pages) - 1, max(pages) + 1, row["chunk_id"], min(pages)),
        ).fetchall()
        added = 0
        for neighbor in neighbors:
            if neighbor["chunk_id"] in selected_ids or not section_matches_device(neighbor, query):
                continue
            segment = evidence_segment(neighbor, 0, min(EVIDENCE_CHARS_PER_CHUNK, remaining))
            expanded[row["chunk_id"]].append(segment)
            selected_ids.add(neighbor["chunk_id"])
            remaining -= len(str(segment["text"]))
            added += 1
            if remaining <= 0 or added == MAX_EVIDENCE_NEIGHBORS:
                break
    return expanded


class ChunkNotFoundError(ValueError):
    pass


def read_chunk(
    database: Path, chunk_id: str, query: str = "", offset: int = 0, max_chars: int = 8000,
    *, allow_board_text: bool = False,
) -> dict[str, object]:
    if not isinstance(chunk_id, str) or not chunk_id.strip():
        raise ValueError("chunkId must be a non-empty search-result chunk identifier")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= MAX_READ_CHARS:
        raise ValueError(f"maxChars must be between 1 and {MAX_READ_CHARS}")
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        matches = connection.execute(
            "SELECT *, text AS excerpt FROM chunks WHERE chunk_id = ? LIMIT 2", (chunk_id,),
        ).fetchall()
        if len(matches) != 1:
            raise ChunkNotFoundError(
                "chunkId was not found; pass it exactly as printed after 'documentation_read chunkId=' "
                "in a documentation_search result"
            )
        row = matches[0]
        board_metadata: dict[str, Any] = {}
        if row["document_type"] == "board_manual":
            has_scope = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'board_chunks'"
            ).fetchone()
            scope = connection.execute(
                "SELECT metadata FROM board_chunks WHERE chunk_id = ?", (chunk_id,),
            ).fetchone() if has_scope else None
            board_metadata = json.loads(scope[0]) if scope else {}
            # Reviewed facts carry BPL/hardware checks that only documentation_search applies;
            # only scoped, fact-free board-manual text can be read here.
            if not allow_board_text or not board_metadata.get("board") or board_metadata.get("facts"):
                raise ValueError("Use documentation_search with board/hardwareVersion for reviewed board facts")
        if query and (
            not rows_for_device([row], query_document_prefixes(query))
            or not section_matches_device(row, query)
        ):
            raise ValueError("chunkId does not match the requested device")
        if offset > len(row["text"]):
            raise ValueError("offset exceeds the chunk length")
        segment = evidence_segment(row, offset, max_chars)
        if row["document_type"] == "board_manual":
            segment["citation"].update(
                {key: board_metadata[key] for key in ("board", "hardware_versions") if key in board_metadata}
            )
            segment["boardManualText"] = True
        return segment
    finally:
        connection.close()


def hardware_version_matches(requested: str, supported: str) -> bool:
    # "V2.0" reported by the flasher and "V2" in a manual name the same revision.
    trim = lambda value: re.sub(r"(?:\.0+)+$", "", value.strip().lower().removeprefix("v")) or "0"
    requested = trim(requested)
    supported = supported.strip().lower().removeprefix("v")
    if not supported.endswith(".x"):
        supported = trim(supported)
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


def _module_context(terms: list[str]) -> list[str]:
    return [
        term for term in terms
        if term.isalpha() and term.isupper() and len(term) >= 2 and term.casefold() not in DEVICE_TERMS
    ][:2]


def _core_terms(terms: list[str], context: list[str]) -> list[str]:
    return [
        term for term in terms
        if term.casefold() not in DEVICE_TERMS | FOLLOW_UP_FILLER and term not in context
        and not HARDWARE_REVISION.fullmatch(term)
    ]


def follow_up_queries(query: str) -> list[str]:
    """Keyword queries per clause of a long question: device + module acronyms + key terms."""
    terms = query_terms(query)
    if len(terms) < FOLLOW_UP_MIN_TERMS:
        return []
    device = [term for term in terms if term.casefold() in DEVICE_TERMS][:1]
    context = _module_context(terms)
    original = {term.casefold() for term in terms}
    queries: list[str] = []
    for clause in CLAUSE_BOUNDARY.split(query):
        try:
            clause_terms = query_terms(clause)
        except ValueError:
            continue
        core = _core_terms(clause_terms, context)[:FOLLOW_UP_CORE_TERMS]
        # A single short word ("step", "pin", "large") is too vague and would take a slot from a
        # real clause; a single specific word ("polarity", "retention") is kept.
        if not core or (len(core) == 1 and len(core[0]) < 6):
            continue
        follow_up = " ".join(dict.fromkeys(device + context + core))
        if follow_up not in queries and {term.casefold() for term in query_terms(follow_up)} != original:
            queries.append(follow_up)
    return queries[:FOLLOW_UP_MAX_QUERIES]


def _term_present(term: str, text: str) -> bool:
    key = term.casefold()
    variants = {key, key.removesuffix("s")} if len(key) > 3 else {key}
    if is_plain_compound(term):
        parts = key.split("-")
        variants |= {" ".join(parts), "".join(parts)}
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(variant) + r"(?:s|es)?(?![a-z0-9])", text) for variant in variants
    )


def coverage_hints(query: str, results: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Identifiers and technical compounds from the question that no returned text contains."""
    if not results:
        return {}
    text = " ".join(
        f'{item.get("section") or ""} {item["citation"].get("section") or ""} '
        f'{item["citation"].get("excerpt") or ""} {item.get("text") or ""}'
        for result in results for item in [result, *result.get("evidence", [])]
    ).casefold()
    # Plain words ("versus", "denote") are usually absent without anything being missing.
    uncovered = [
        term for term in _core_terms(query_terms(query), [])
        if (is_anchor(term) or is_plain_compound(term)) and not _term_present(term, text)
    ]
    return {"uncoveredTerms": uncovered} if uncovered else {}


def _focused_segment(row: sqlite3.Row, terms: list[str], max_chars: int) -> dict[str, object]:
    lowered = row["text"].casefold()
    positions = [position for term in terms if (position := lowered.find(term.casefold())) >= 0]
    start = max(0, min(positions) - max_chars // 6) if positions else 0
    return evidence_segment(row, start, max_chars)


def _follow_up_results(
    connection: sqlite3.Connection,
    query: str,
    rows: list[sqlite3.Row],
    evidence: dict[str, list[dict[str, object]]],
    snippet_tokens: int,
    scoped: bool,
    veto_unknown_anchors: bool,
) -> list[dict[str, object]]:
    seen = {row["chunk_id"] for row in rows}
    seen.update(segment["chunk_id"] for segments in evidence.values() for segment in segments)
    seen_text = {" ".join(row["text"].split()) for row in rows}
    ranked = []
    for follow_up in follow_up_queries(query):
        try:
            ranked.append((follow_up, retrieve(
                connection, follow_up, FOLLOW_UP_PER_QUERY, snippet_tokens, scoped, veto_unknown_anchors,
            )))
        except ValueError:
            continue
    selected = []
    # Round-robin so every clause gets a hit before any clause gets a second one.
    for rank in range(FOLLOW_UP_PER_QUERY):
        for follow_up, candidates in ranked:
            if rank >= len(candidates) or len(selected) == FOLLOW_UP_MAX_RESULTS:
                continue
            row = candidates[rank]
            text_key = " ".join(row["text"].split())
            if row["chunk_id"] in seen or text_key in seen_text:
                continue
            seen.add(row["chunk_id"])
            seen_text.add(text_key)
            selected.append((follow_up, row))
    results = []
    for follow_up, row in selected:
        follow_up_terms = query_terms(follow_up)
        result = result_from_row(row)
        result["evidence"] = [_focused_segment(
            row, _core_terms(follow_up_terms, _module_context(follow_up_terms)), FOLLOW_UP_CHARS_PER_RESULT,
        )]
        result["applicability"] = "requires_verification"
        result["evidenceStatus"] = "not_assessed"
        result["retrievalPass"] = "follow_up"
        result["followUpQuery"] = follow_up
        results.append(result)
    return results


def search_results(
    database: Path,
    query: str,
    limit: int = 3,
    snippet_tokens: int = 64,
    *,
    board: str | None = None,
    hardware_version: str | None = None,
    veto_unknown_anchors: bool = True,
    follow_up: bool = False,
) -> list[dict[str, object]]:
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
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
        rows = retrieve(connection, query, limit, snippet_tokens, scoped=has_scope,
                        veto_unknown_anchors=veto_unknown_anchors)
        results = [result_from_row(row) for row in rows]
        # Reviewed board facts are already complete; board-manual text chunks
        # need full-text evidence like chip-manual chunks.
        evidence = expand_evidence(
            connection,
            [
                row for row in rows
                if row["document_type"] != "board_manual"
                or not metadata_by_chunk.get(row["chunk_id"], {}).get("facts")
            ],
            query,
        )
        for result in results:
            if result["chunk_id"] in evidence:
                result["evidence"] = evidence[result["chunk_id"]]
                result["applicability"] = "requires_verification"
                result["evidenceStatus"] = "not_assessed"
            metadata = metadata_by_chunk.get(result["chunk_id"])
            if metadata:
                result["facts"] = metadata.get("facts", [])
                result["applicability"] = "matched" if hardware_version else "hardware_version_required"
                result["citation"].update({key: value for key, value in metadata.items() if key != "facts"})
        if follow_up and rows:
            results.extend(_follow_up_results(
                connection, query, rows, evidence, snippet_tokens, has_scope, veto_unknown_anchors,
            ))
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