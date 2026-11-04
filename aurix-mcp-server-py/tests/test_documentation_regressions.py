from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server import connected_devices
from aurix_mcp_server.board_documentation import board_evidence
from aurix_mcp_server.documentation_retrieval import (
    EVIDENCE_TOTAL_CHARS, build_index, follow_up_queries, query_terms, search_results,
)
from aurix_mcp_server.tools import documentation_search


def chunk(identifier: str, text: str, **fields) -> dict:
    record = {
        "chunk_id": identifier, "document_id": "tc37x-manual",
        "document_type": "user_manual", "document_title": "Fixture manual",
        "document_version": "1", "source": "fixture.pdf",
        "headings": ["DMA"], "pages": [10], "text": text,
    }
    record.update(fields)
    return record


class RoutingRegressionTests(unittest.TestCase):
    def test_bundled_documentation_modules_match_source(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = root / "aurix-mcp-server-py" / "src" / "aurix_mcp_server"
        bundle = root / "aurix-ai-agent-extension" / "server" / "aurix-mcp-server-py" / "src" / "aurix_mcp_server"
        if not bundle.is_dir():
            self.skipTest("The extension bundle is not present in this source-only checkout")
        for relative in (
            Path("board_documentation.py"), Path("documentation_retrieval.py"),
            Path("tools") / "documentation_search.py", Path("server_fastmcp.py"),
            Path("build_cache.py"), Path("connected_devices.py"),
            Path("tools") / "build_run.py", Path("tools") / "ads_create_project.py",
        ):
            with self.subTest(module=str(relative)):
                self.assertEqual((source / relative).read_bytes(), (bundle / relative).read_bytes())

    def test_module_reset_and_wakeup_do_not_require_a_board(self) -> None:
        for query in (
            "TC375 DMA channel reset completion and software request",
            "TC375 STM reset compare flags and interrupt initialization",
            "How does the CAN module wake from sleep?",
            "What does the reset register do?",
            "What are reset requirements?",
        ):
            with self.subTest(query=query):
                self.assertIsNone(board_evidence({}, query, 5))

    def test_physical_reset_still_requires_board_identity(self) -> None:
        for query in ("Which pin is the reset button wired to?", "WAKE switch connection"):
            with self.subTest(query=query):
                self.assertEqual(board_evidence({}, query, 5)["reason"], "specific_board_required")

    def test_port_pin_with_on_chip_function_uses_chip_path(self) -> None:
        for query in (
            "TC37x I2C0_SCL Serial Clock Output P02.5 I2C0_SCLA",
            "Which alternate output function selects ASCLIN0 TX on P14.0?",
        ):
            with self.subTest(query=query):
                self.assertIsNone(board_evidence({"device": "TC375"}, query, 5))
        for query in ("TC375 Lite V2 LED1 P00.4", "Is P00.5 the LED on my board active low?"):
            with self.subTest(query=query):
                self.assertIsNotNone(board_evidence({}, query, 5))

    def test_frozen_original_reset_questions_use_chip_path(self) -> None:
        dataset_path = Path(__file__).resolve().parents[1] / "evaluation" / "tc375-english-round2.json"
        if not dataset_path.is_file():
            self.skipTest("The evaluation data set is kept outside the repository")
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        for case in dataset["cases"]:
            if case["id"] in {"TC375-29", "TC375-34"}:
                self.assertIsNone(board_evidence({"device": "TC375"}, case["query_en"], 5))

    def test_query_generation_does_not_inherit_other_selected_device(self) -> None:
        with patch.dict("os.environ", {"AURIX_SELECTED_DEVICE": "KIT_A2G_TC375_LITE"}):
            self.assertEqual(documentation_search._retrieval_query({}, "TC2xx DMA"), "TC2xx DMA")


class RetrievalRegressionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.index = self.root / "fixture.sqlite"

    def index_chunks(self, *records: dict) -> None:
        (self.root / "chunks.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records), encoding="utf-8",
        )
        build_index(self.root, self.index)

    async def test_full_evidence_and_cited_table_continuation_reach_the_agent(self) -> None:
        self.index_chunks(
            chunk("table", "VADC converter reference clock. " + "Conditions apply. " * 120
                  + "\nSupply | Maximum clock\n3.3 V | 26.67 MHz\n5 V | 53.33 MHz",
                  headings=["VADC electrical characteristics"], document_type="datasheet"),
            chunk("footnote", "Footnote: accuracy scaling is 1.1/k.",
                  headings=["VADC electrical characteristics"], pages=[11], document_type="datasheet"),
            chunk("other-section", "Unrelated secret-shaped fixture text.",
                  headings=["QSPI"], pages=[11]),
            chunk("other-version", "Obsolete limits.", document_version="0", pages=[11],
                  headings=["VADC electrical characteristics"]),
        )
        result = await documentation_search._run(
            {"query": "TC375 VADC converter reference clock", "indexPath": str(self.index), "topK": 1,
             "detail": "full"},
            None,
        )
        self.assertFalse(result.is_error)
        text = result.content[0].text
        self.assertIn("26.67 MHz", text)
        self.assertIn("53.33 MHz", text)
        self.assertIn("1.1/k", text)
        self.assertIn("physical PDF page(s) 11", text)
        self.assertNotIn("Obsolete limits", text)
        self.assertNotIn("Unrelated secret-shaped", text)
        item = result.structured_content["results"][0]
        self.assertEqual(item["citation"]["pdf_pages"], [10])
        self.assertEqual(item["evidence"][1]["citation"]["pdf_pages"], [11])
        self.assertEqual(result.structured_content["evidenceStatus"], "not_assessed")

    def test_count_statement_beats_contents_and_duplicate_chunks(self) -> None:
        question = "How many DMA channels are implemented in the TC37x DMA used by TC375?"
        self.index_chunks(
            chunk("toc1", question, headings=["Table of contents"], pages=[1]),
            chunk("toc2", question, headings=["Contents"], pages=[2]),
            chunk("answer", "The TC37x DMA contains 128 DMA channels.",
                  headings=["DMA specific IP configuration"], pages=[368]),
            chunk("duplicate", "The TC37x DMA contains 128 DMA channels.",
                  headings=["DMA specific IP configuration"], pages=[368]),
        )
        results = search_results(self.index, question, limit=3)
        self.assertEqual(results[0]["chunk_id"], "answer")
        self.assertFalse({"answer", "duplicate"} <= {row["chunk_id"] for row in results})

    def test_device_specific_limits_beat_foreign_device_use_case(self) -> None:
        self.index_chunks(
            chunk("foreign", "TC375 SPB STM GTM maximum clock limits.",
                  document_id="tc3xx-part1", headings=["TC39x SPU use case"]),
            chunk("limits", "SPB maximum 100 MHz. STM maximum 100 MHz. GTM maximum 200 MHz.",
                  document_type="datasheet", headings=["Clock limits"], pages=[217]),
        )
        results = search_results(self.index, "TC375 SPB STM GTM maximum clock limits", limit=3)
        self.assertEqual(results[0]["chunk_id"], "limits")
        self.assertNotIn("foreign", {row["chunk_id"] for row in results})

    def test_compound_question_keeps_evidence_when_final_clause_has_no_hit(self) -> None:
        self.index_chunks(chunk("timestamp", "DMA timestamp counter width is 32 bits. Clock is SPB/8."))
        results = search_results(
            self.index,
            "TC375 DMA timestamp counter width and clock? Is WALLCLOCK_REALTIME supported?",
            limit=5,
        )
        self.assertEqual(results[0]["chunk_id"], "timestamp")

    async def test_device_argument_scopes_query_without_device_words(self) -> None:
        self.index_chunks(
            chunk("wrong", "DMA channel configuration", document_id="tc39x-manual"),
            chunk("right", "DMA channel configuration", document_id="tc37x-manual"),
        )
        result = await documentation_search._run(
            {"query": "DMA channel configuration", "device": "TC375", "indexPath": str(self.index)},
            None,
        )
        self.assertFalse(result.is_error)
        self.assertEqual([row["chunk_id"] for row in result.structured_content["results"]], ["right"])

    async def test_explicit_device_conflict_is_reported(self) -> None:
        result = await documentation_search._run(
            {"query": "TC397 DMA channels", "device": "TC375", "indexPath": str(self.index)},
            None,
        )
        self.assertTrue(result.is_error)
        self.assertIn("device", result.content[0].text)

    async def test_bounded_evidence_can_be_read_to_completion(self) -> None:
        original = "DMA timestamp. " + "counter information " * 3000 + " END_OF_CHUNK"
        self.index_chunks(chunk("large", original))
        results = search_results(self.index, "TC375 DMA timestamp", limit=1)
        evidence = results[0]["evidence"][0]
        self.assertTrue(evidence["truncated"])
        self.assertLessEqual(len(evidence["text"]), 6000)
        offset = 0
        parts = []
        while offset is not None:
            result = await documentation_search._read_run({
                "chunkId": "large", "offset": offset, "maxChars": 8000,
                "indexPath": str(self.index), "device": "TC375",
            }, None)
            self.assertFalse(result.is_error, result.content[0].text)
            data = result.structured_content
            self.assertNotIn("excerpt", data["citation"])
            segment = original[offset:offset + 8000]
            self.assertIn(segment, result.content[0].text)
            self.assertEqual(data["text"], segment)
            parts.append(segment)
            offset = data["nextOffset"]
        self.assertEqual("".join(parts), original)

    async def test_read_rejects_unknown_chunks_wrong_device_and_invalid_offsets(self) -> None:
        self.index_chunks(chunk("known", "DMA facts"))
        for extra in (
            {"chunkId": "missing"}, {"offset": -1}, {"offset": 999},
            {"offset": True}, {"maxChars": 0}, {"device": "TC397"},
        ):
            result = await documentation_search._read_run(
                {"chunkId": "known", "indexPath": str(self.index), **extra}, None,
            )
            self.assertTrue(result.is_error, extra)

    def test_evidence_has_a_total_budget_and_does_not_merge_other_sources(self) -> None:
        self.index_chunks(
            *(chunk(f"long-{i}", f"DMA timestamp {i}. " + "counter " * 1200, pages=[i + 1])
              for i in range(10)),
            chunk("other-source", "Wrong source footnote", source="other.pdf", pages=[1]),
        )
        results = search_results(self.index, "DMA timestamp", limit=10)
        evidence = [part for row in results for part in row["evidence"]]
        self.assertLessEqual(sum(len(part["text"]) for part in evidence), EVIDENCE_TOTAL_CHARS)
        self.assertEqual(len(results), 10)
        self.assertNotIn("other-source", {part["chunk_id"] for part in evidence})

    async def test_read_cannot_bypass_reviewed_board_guards(self) -> None:
        self.index_chunks(chunk("board", "LED1", document_type="board_manual"))
        result = await documentation_search._read_run(
            {"chunkId": "board", "indexPath": str(self.index)}, None,
        )
        self.assertTrue(result.is_error)
        self.assertIn("hardwareVersion", result.content[0].text)

    def test_unknown_single_question_anchor_still_abstains(self) -> None:
        self.index_chunks(chunk("timestamp", "DMA timestamp counter width is 32 bits."))
        self.assertEqual(search_results(self.index, "TC375 UNKNOWN_FIRMWARE_HASH DMA"), [])

    def test_incidental_ellipsis_in_body_text_is_not_treated_as_contents(self) -> None:
        self.index_chunks(
            chunk("body", "TOS mapping (TOS=0 -> ICU0, TOS=1 -> ICU1, ....). For a group of service "
                  "requests with the same SRPN, the sequence of execution can not be defined.", pages=[1373]),
            *(chunk(f"other-{i}", "SRPN service requests sequence execution priority mapping",
                    pages=[1400 + i * 5]) for i in range(6)),
        )
        results = search_results(self.index, "same SRPN service requests sequence of execution defined", limit=5)
        self.assertEqual(results[0]["chunk_id"], "body")

    def test_all_terms_match_outranks_higher_scoring_partial_match(self) -> None:
        filler = " ".join(["register field description"] * 80)
        self.index_chunks(
            chunk("complete", f"{filler} CPU_TC.130 concurrent DSPR store corrupts the adjacent byte. "
                  f"Workaround documented. {filler}", document_type="errata", document_id="tc37x-errata",
                  pages=[20]),
            *(chunk(f"partial-{i}", "CPU_TC.130 DSPR adjacent byte", document_type="errata",
                    document_id="tc37x-errata", pages=[180 + i * 5]) for i in range(8)),
            *(chunk(f"noise-{i}", "concurrent workaround documented corrupts", pages=[500 + i * 5])
              for i in range(10)),
        )
        results = search_results(
            self.index, "CPU_TC.130 concurrent DSPR adjacent byte corrupts workaround documented", limit=5,
        )
        self.assertEqual(results[0]["chunk_id"], "complete")

    def test_question_scaffolding_is_not_search_vocabulary(self) -> None:
        terms = query_terms("Do all three TC375 CPUs have the same DSPR? Give each CPU's size. Can CAN wake?")
        self.assertNotIn("have", [t.casefold() for t in terms])
        self.assertNotIn("s", terms)
        self.assertIn("CAN", terms)
        self.assertIn("same", terms)

    def test_hyphenated_question_word_matches_closed_compound(self) -> None:
        self.index_chunks(
            chunk("map", "Address Range Size Unit. 240 Kbyte Data ScratchPad RAM (CPU0). 96 Kbyte Data ScratchPad RAM (CPU2).",
                  headings=["Memory Map"], pages=[12]),
            *(chunk(f"noise-{i}", "data RAM size CPU memory", pages=[100 + i * 5]) for i in range(8)),
        )
        results = search_results(self.index, "TC375 data scratch-pad RAM size per CPU", limit=3)
        self.assertEqual(results[0]["chunk_id"], "map")

    def test_unknown_plain_compound_does_not_veto_the_query(self) -> None:
        self.index_chunks(chunk("timestamp", "The DMA timestamp is a 32-bit counter clocked at fSPB/8."))
        results = search_results(self.index, "TC375 DMA timestamp counter wall-clock time", limit=3)
        self.assertEqual(results[0]["chunk_id"], "timestamp")

    def test_numeric_only_anchor_does_not_reject_every_candidate(self) -> None:
        self.index_chunks(
            chunk("supply", "Single Supply mode (a): VEXT 5 V single supply. VDD and VDDP3 are generated internally "
                  "by the EVRC and EVR33 internal regulators. The current drawn from the external regulator "
                  "during start-up is limited to a maximum of 100 mA.", document_type="datasheet", pages=[264]),
            *(chunk(f"noise-{i}", "regulator current limit", pages=[400 + i * 5]) for i in range(6)),
        )
        results = search_results(self.index, "In TC375 5 V single-supply mode, which core and I/O rails are generated "
                                 "internally, and what limit applies to current drawn from the external regulator "
                                 "during start-up?", limit=3)
        self.assertEqual(results[0]["chunk_id"], "supply")

    def test_single_erratum_identifier_supports_moderate_coverage(self) -> None:
        self.index_chunks(
            chunk("erratum", "[CPU_TC.130] Data corruption when ST.B to local DSPR coincides with external access. "
                  "If the condition occurs the adjacent byte is corrupted. Marking/Step (E)ES-AA, AA.",
                  document_type="errata", document_id="tc37x-errata", pages=[20]),
        )
        results = search_results(self.index, "Does CPU_TC.130 definitely affect my TC375 board if I do not know "
                                 "its silicon stepping?", limit=3)
        self.assertEqual([row["chunk_id"] for row in results], ["erratum"])

    def test_relevant_errata_are_not_globally_demoted(self) -> None:
        self.index_chunks(
            chunk("generic", "DMA double buffer stops when full.", pages=[30]),
            chunk("errata", "DMA double buffer erratum: may continue; workaround uses protection.",
                  document_type="errata", document_id="tc37x-errata", pages=[25]),
        )
        results = search_results(self.index, "TC375 DMA double buffer erratum workaround")
        self.assertEqual(results[0]["chunk_id"], "errata")


class BoardManualTextTests(unittest.IsolatedAsyncioTestCase):
    BOARD = "KIT_A2G_TC375_LITE"

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        common = {"document_id": "tc375-lite-kit-v2", "document_type": "board_manual", "document_title": "Board manual",
                  "document_version": "2.2", "source": "board.pdf", "board": self.BOARD, "hardware_versions": ["2"]}
        records = [
            {**common, "chunk_id": "fact:led1", "headings": ["LEDs"], "pages": [10],
             "text": "TC375 Lite Kit V2: LED1 is on P00.5. It is low-active.",
             "facts": [{"signal": "LED1", "pin": "P00.5", "active_level": "low"}]},
            {**common, "chunk_id": "text:p12", "headings": ["lite Kit V2 > 2.5 CAN Transceiver"], "pages": [12], "facts": [],
             "text": "The transceiver TLE9251V is in stand-by mode per default. Drive CAN_STB P20.6 low for normal mode. "
                     "LED1 maximum current is limited by the series resistor."},
            chunk("chip", "MCMCAN node transceiver standby control register", document_id="tc37x-manual"),
        ]
        (root / "chunks.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        self.index = root / "board-fixture.index"
        build_index(root, self.index)

    async def search(self, query: str, **extra):
        result = await documentation_search._run(
            {"query": query, "device": "TC375", "indexPath": str(self.index), **extra}, None,
        )
        self.assertFalse(result.is_error, result.content[0].text)
        return result.structured_content

    async def test_named_board_manual_text_of_matching_revision_is_usable_with_citation(self) -> None:
        question = "On the TC375 lite Kit V2, how is the CAN transceiver standby TLE9251V controlled?"
        data = await self.search(question, detail="full")
        first = data["results"][0]
        self.assertEqual(first["chunk_id"], "text:p12")
        self.assertTrue(first["usableForCodeGeneration"])
        self.assertEqual(first["usageRestriction"], "cite_board_manual_page")
        self.assertIn("P20.6", first["evidence"][0]["text"])
        self.assertIn("without asking", data["boardTextGuidance"])
        result = await documentation_search._run(
            {"query": question, "device": "TC375", "indexPath": str(self.index)}, None,
        )
        compact = result.structured_content["results"][0]
        self.assertEqual(compact["usageRestriction"], "cite_board_manual_page")
        self.assertTrue(compact["usableForCodeGeneration"])
        self.assertIn("P20.6", result.content[0].text)
        self.assertIn("without asking the user to confirm", result.content[0].text)
        self.assertIn("code generation yes", result.content[0].text)
        self.assertNotIn("unreviewed", result.content[0].text)

    async def test_manual_text_without_known_revision_points_to_device_detection(self) -> None:
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "0"}):
            result = await documentation_search._run(
                {"query": "On the TC375 lite Kit, how is the CAN transceiver standby TLE9251V controlled?",
                 "device": "TC375", "indexPath": str(self.index)}, None,
            )
        first = result.structured_content["results"][0]
        self.assertEqual(first["chunk_id"], "text:p12")
        self.assertFalse(first["usableForCodeGeneration"])
        self.assertEqual(first["usageRestriction"], "board_hardware_version_required")
        self.assertIn("call flash_list_devices", result.content[0].text)

    async def test_board_scope_outside_pin_facts_falls_back_to_revision_matched_text(self) -> None:
        data = await self.search("TC375 Lite V2 LED1 maximum current")
        self.assertTrue(data["abstained"])
        self.assertEqual(data["reason"], "outside_reviewed_pin_and_active_level_scope")
        self.assertEqual([r["chunk_id"] for r in data["results"]], ["text:p12"])
        self.assertFalse(data["requiresConfirmation"])
        self.assertEqual(data["evidenceStatus"], "board_manual_text")

    async def test_reviewed_facts_still_win_for_led_questions(self) -> None:
        data = await self.search("TC375 Lite V2 LED1 pin")
        self.assertEqual([[fact["signal"] for fact in r["facts"]] for r in data["results"]], [["LED1"]])
        self.assertTrue(data["results"][0]["usableForCodeGeneration"])
        # A reviewed fact is complete; offering its chunkId only invites a failing documentation_read.
        self.assertNotIn("chunk_id", data["results"][0])

    async def test_text_excerpts_keep_chunk_id_for_documentation_read(self) -> None:
        data = await self.search("TC375 Lite V2 LED1 maximum current")
        self.assertEqual([r["chunk_id"] for r in data["results"]], ["text:p12"])

    async def test_no_board_text_without_named_board_or_for_other_revision(self) -> None:
        data = await self.search("CAN transceiver standby TLE9251V")
        self.assertNotIn("text:p12", [r["chunk_id"] for r in data["results"]])
        data = await self.search("On the TC375 lite Kit V1, how is the CAN transceiver standby TLE9251V controlled?")
        self.assertNotIn("text:p12", [r["chunk_id"] for r in data["results"]])

    async def test_identifier_missing_from_board_manual_does_not_suppress_board_text(self) -> None:
        data = await self.search("Which CAN transceiver TLE9251V and MAC-PHY interface does the TC375 lite Kit V2 use?")
        self.assertEqual(data["results"][0]["chunk_id"], "text:p12")

    def test_unknown_identifier_still_abstains_on_chip_documentation(self) -> None:
        self.assertEqual(search_results(self.index, "MCMCAN UNKNOWN_REG_XYZ transceiver standby", limit=3), [])

    def test_bundled_board_index_contains_lite_kit_manual_text(self) -> None:
        from aurix_mcp_server.board_documentation import BOARD_INDEX, board_manual_text
        for query, page in (("TLE9251V CAN_STB standby", 12), ("24AA02E48 EEPROM", 12),
                            ("DP83825I RMII", 13), ("R59 HWCFG6", 14)):
            with self.subTest(query=query):
                pages = [r["citation"]["pdf_pages"][0] for r in board_manual_text({}, query, 3, self.BOARD, "2")]
                self.assertIn(page, pages)
        self.assertEqual(board_manual_text({}, "TLE9251V CAN_STB standby", 3, self.BOARD, "1"), [])
        # Older server code only reads the reviewed-fact index; it must never see manual text.
        self.assertEqual(search_results(BOARD_INDEX, "TLE9251V CAN_STB standby", board=self.BOARD, hardware_version="2"), [])
        for result in search_results(BOARD_INDEX, "Block Diagram LED1 Button Reset", limit=10, board=self.BOARD, hardware_version="2"):
            self.assertTrue(result["facts"])

    async def test_board_text_read_pointer_is_readable_but_facts_are_not(self) -> None:
        read = lambda chunk_id, **extra: documentation_search._read_run(
            {"chunkId": chunk_id, "device": "TC375", "indexPath": str(self.index), **extra}, None,
        )
        result = await read("text:p12")
        self.assertFalse(result.is_error, result.content[0].text)
        self.assertIn("P20.6", result.content[0].text)
        self.assertIn("flash_list_devices", result.content[0].text)
        self.assertFalse(result.structured_content["usableForCodeGeneration"])
        self.assertEqual(result.structured_content["usageRestriction"], "board_hardware_version_required")
        self.assertEqual(result.structured_content["citation"]["board"], self.BOARD)
        kit = [{"board": self.BOARD, "hardwareVersion": "2.0", "boardHardware": "AURIX LITE KIT V2.0 (TC375)", "id": 1}]
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), patch.object(
            connected_devices, "detect_connected_devices", return_value={"ok": True, "devices": kit},
        ):
            detected = await read("text:p12")
        self.assertTrue(detected.structured_content["usableForCodeGeneration"])
        self.assertEqual(detected.structured_content["usageRestriction"], "cite_board_manual_page")
        self.assertIn("without asking the user to confirm", detected.content[0].text)
        facts = await read("fact:led1")
        self.assertTrue(facts.is_error)
        self.assertIn("reviewed board facts", facts.content[0].text)
        invented = await read("tc3xx_um_p2:mcmcan:2054")
        self.assertTrue(invented.is_error)
        self.assertIn("exactly as printed", invented.content[0].text)

    async def test_bundled_board_text_read_pointer_resolves_without_index_path(self) -> None:
        # Without indexPath the chip index may be absent (source checkout); the bundled board-text index is used.
        read = await documentation_search._read_run(
            {"chunkId": "tc375-lite-kit-v2:manual:p012", "device": "TC375", "maxChars": 3000}, None,
        )
        self.assertFalse(read.is_error, read.content[0].text)
        self.assertIn("CAN_STB", read.content[0].text)
        self.assertFalse(read.structured_content["usableForCodeGeneration"])


class FollowUpRetrievalTests(unittest.IsolatedAsyncioTestCase):
    QUESTION = (
        "For TC375 DMA timestamps with a constant 100 MHz SPB clock, what are the timestamp tick period "
        "and wraparound interval? Are these timestamps wall-clock time?"
    )
    OVERVIEW = chunk(
        "overview",
        "DMA timestamps: with a constant 100 MHz SPB clock the timestamp tick period is 80 ns and the "
        "wraparound interval follows from the 32-bit counter.",
    )
    WALL_CLOCK = chunk(
        "wall-clock", "Timestamps are not wall-clock time; they record when the DMA event was recorded.",
        headings=["DMA timestamp semantics"], pages=[40],
    )

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.index = self.root / "fixture.index"

    def index_chunks(self, *records: dict) -> None:
        (self.root / "chunks.jsonl").write_text(
            "\n".join(json.dumps(record) for record in records), encoding="utf-8",
        )
        build_index(self.root, self.index)

    def test_follow_up_queries_split_clauses_and_keep_device_and_module(self) -> None:
        queries = follow_up_queries(self.QUESTION)
        self.assertLessEqual(len(queries), 3)
        self.assertIn("TC375 DMA SPB timestamps wall-clock time", queries)
        self.assertIn("TC375 DMA SPB timestamp tick period wraparound interval", queries)
        self.assertEqual(follow_up_queries("TC375 DMA timestamp"), [])
        # A clause reduced to a single vague word does not become a follow-up query.
        self.assertNotIn("TC375 AA DMA step", follow_up_queries(
            "For TC375 AA step, what access width must software use when updating DMA double-buffer addresses?"
        ))

    def test_follow_up_hits_are_appended_without_changing_primary_results(self) -> None:
        self.index_chunks(self.OVERVIEW, self.WALL_CLOCK)
        primary = search_results(self.index, self.QUESTION, limit=1)
        combined = search_results(self.index, self.QUESTION, limit=1, follow_up=True)
        self.assertEqual([result["chunk_id"] for result in primary], ["overview"])
        self.assertEqual(combined[:1], primary)
        extra = combined[1:]
        self.assertEqual([result["chunk_id"] for result in extra], ["wall-clock"])
        self.assertEqual(extra[0]["retrievalPass"], "follow_up")
        self.assertIn("wall-clock", extra[0]["followUpQuery"])
        self.assertIn("not wall-clock time", extra[0]["evidence"][0]["text"])

    def test_abstention_is_not_overridden_by_follow_ups(self) -> None:
        self.index_chunks(self.OVERVIEW, self.WALL_CLOCK)
        question = (
            "Which UNKNOWN_FIRMWARE_HASH applies to TC375 DMA timestamps with a constant 100 MHz SPB clock "
            "and their tick period and wraparound interval"
        )
        self.assertGreaterEqual(len(follow_up_queries(question)), 1)
        self.assertEqual(search_results(self.index, question, limit=3, follow_up=True), [])

    async def test_tool_reports_uncovered_identifiers_only(self) -> None:
        self.index_chunks(self.OVERVIEW)
        question = self.QUESTION.replace("wall-clock time", "wall-clock time per DMA_TC.099")
        result = await documentation_search._run(
            {"query": question, "indexPath": str(self.index), "topK": 1}, None,
        )
        self.assertFalse(result.is_error)
        structured = result.structured_content
        # Plain words such as "time" are not reported; identifiers and technical compounds are.
        self.assertEqual(structured["uncoveredTerms"], ["wall-clock", "DMA_TC.099"])
        self.assertNotIn("suggestedQueries", structured)
        self.assertIn("Not found in the returned text: wall-clock, DMA_TC.099.", result.content[0].text)

    async def test_tool_labels_follow_up_results(self) -> None:
        self.index_chunks(self.OVERVIEW, self.WALL_CLOCK)
        result = await documentation_search._run(
            {"query": self.QUESTION, "indexPath": str(self.index), "topK": 1}, None,
        )
        self.assertEqual(result.structured_content["resultCount"], 2)
        self.assertIn('[2] (follow-up "TC375 DMA SPB timestamps wall-clock time")', result.content[0].text)
        self.assertNotIn("uncoveredTerms", result.structured_content)

    async def test_named_board_follow_ups_search_board_text_before_chip_manuals(self) -> None:
        board = {"document_id": "tc375-lite-kit-v2", "document_type": "board_manual", "document_title": "Board manual",
                 "document_version": "2.2", "source": "board.pdf", "board": "KIT_A2G_TC375_LITE",
                 "hardware_versions": ["2"], "facts": []}
        self.index_chunks(
            {**board, "chunk_id": "text:p6", "headings": ["Power supply"], "pages": [6],
             "text": "The DC jack X3 accepts a supply voltage of 5 V to 40 V."},
            {**board, "chunk_id": "text:p7", "headings": ["Polarity"], "pages": [7],
             "text": "DC jack polarity: center pin is positive."},
            {**board, "chunk_id": "text:p8", "headings": ["LDO"], "pages": [8],
             "text": "Maximum total current from the on-board LDOs is 400 mA."},
            chunk("chip-supply", "Supply voltage operating conditions and maximum total current of the device.",
                  document_id="tc37x-datasheet", headings=["Operating conditions"]),
            chunk("chip-polarity", "Reverse polarity and supply voltage protection for the device supply pins.",
                  document_id="tc37x-datasheet", headings=["Supply monitoring"], pages=[20]),
        )
        question = ("What supply voltage can the TC375 lite Kit V2 DC jack X3 accept, what is its polarity, and what "
                    "is the maximum total current from the on-board LDOs?")
        self.assertTrue(all("lite" not in query.split() for query in follow_up_queries(question)))
        result = await documentation_search._run(
            {"query": question, "device": "TC375", "indexPath": str(self.index), "topK": 2}, None,
        )
        self.assertFalse(result.is_error)
        results = result.structured_content["results"]
        follow_ups = [item for item in results if item.get("retrievalPass") == "follow_up"]
        self.assertTrue(follow_ups)
        self.assertEqual(follow_ups[0]["citation"]["board"], "KIT_A2G_TC375_LITE")
        self.assertTrue(follow_ups[0]["usableForCodeGeneration"])
        returned_pages = {item["citation"]["pdf_pages"][0] for item in results if item["citation"].get("board")}
        self.assertEqual(returned_pages, {6, 7, 8})

    async def test_board_follow_up_skips_pages_already_returned(self) -> None:
        board = {"document_id": "tc375-lite-kit-v2", "document_type": "board_manual", "document_title": "Board manual",
                 "document_version": "2.2", "source": "board.pdf", "board": "KIT_A2G_TC375_LITE",
                 "hardware_versions": ["2"], "facts": []}
        overview = ("Power overview: the DC jack X3 supply voltage, DC jack polarity and the maximum total current "
                    "of the on-board LDOs are described in this chapter. DC polarity DC polarity.")
        self.index_chunks(
            {**board, "chunk_id": "text:overview", "headings": ["Power"], "pages": [5], "text": overview},
            {**board, "chunk_id": "text:polarity", "headings": ["Polarity"], "pages": [7],
             "text": "DC jack polarity: the center pin is positive."},
        )
        question = ("What supply voltage can the TC375 lite Kit V2 DC jack X3 accept, what is its polarity, and what "
                    "is the maximum total current from the on-board LDOs?")
        result = await documentation_search._run(
            {"query": question, "device": "TC375", "indexPath": str(self.index), "topK": 1}, None,
        )
        results = result.structured_content["results"]
        self.assertEqual(results[0]["chunk_id"], "text:overview")
        self.assertIn("text:polarity", [item["chunk_id"] for item in results if item.get("retrievalPass") == "follow_up"])


class CompactOutputTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.index = self.root / "fixture.index"
        filler = "General description of the module and its integration. " * 60
        records = [
            chunk(f"c{number}", filler + f"Flash wait state table {number}: tPF maximum 30 ns, tPFECC 10 ns. " + filler,
                  headings=["Flash parameters"], pages=[300 + number * 3], document_type="datasheet")
            for number in range(5)
        ]
        (self.root / "chunks.jsonl").write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        build_index(self.root, self.index)

    async def run_search(self, **extra):
        result = await documentation_search._run(
            {"query": "TC375 flash wait state tPF tPFECC", "indexPath": str(self.index), "topK": 5, **extra}, None,
        )
        self.assertFalse(result.is_error, result.content[0].text)
        return result

    async def test_compact_output_is_bounded_and_focused_on_matching_text(self) -> None:
        compact = await self.run_search()
        full = await self.run_search(detail="full")
        text = compact.content[0].text
        structured = json.dumps(compact.structured_content)
        # structuredContent carries the text too and is what VS Code passes to the model.
        self.assertLess(len(structured), (len(full.content[0].text) + len(json.dumps(full.structured_content))) / 3)
        self.assertLess(len(text), 5 * 3200 + 600)
        self.assertEqual(text.count("tPF maximum 30 ns"), 5)
        self.assertIn('documentation_read chunkId="c0"', text)
        self.assertEqual(compact.structured_content["text"], text)
        self.assertNotIn("evidence", compact.structured_content["results"][0])
        self.assertEqual(compact.structured_content["results"][0]["citation"]["page_basis"], "physical_pdf")
        self.assertNotIn("evidencePolicy", compact.structured_content)

    async def test_full_detail_keeps_complete_evidence(self) -> None:
        full = await self.run_search(detail="full")
        self.assertIn("evidence", full.structured_content["results"][0])
        self.assertIn("evidencePolicy", full.structured_content)

    async def test_invalid_detail_is_rejected(self) -> None:
        result = await documentation_search._run(
            {"query": "TC375 flash", "indexPath": str(self.index), "detail": "verbose"}, None,
        )
        self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
