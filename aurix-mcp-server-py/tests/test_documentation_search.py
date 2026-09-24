from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.tools.documentation_search import (  # noqa: E402
    INDEX_DIRECTORY_ENVIRONMENT_VARIABLE,
    INDEX_ENVIRONMENT_VARIABLE,
    MAX_TOP_K,
    SELECTED_DEVICE_ENVIRONMENT_VARIABLE,
    _resolve_index_path,
    _run,
)
from aurix_mcp_server.documentation_retrieval import (  # noqa: E402
    build_index,
    query_document_prefixes,
    query_expansion_groups,
    search_results,
)


class BoardDocumentationRetrievalTests(unittest.TestCase):
    def test_documented_hardware_series_matches_only_its_major_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chunk = {
                "chunk_id": "series:led1", "document_id": "series-manual",
                "document_type": "board_manual", "document_title": "Test series manual",
                "document_version": "A", "source": "https://example.org/manual.pdf",
                "headings": ["LEDs"], "pages": [9], "text": "LED1 active low",
                "board": "KIT_A3G_TC4D7_LITE", "hardware_versions": ["2.x"],
                "facts": [{"signal": "LED1", "pin": "P03.9", "active_level": "low"}],
            }
            (root / "chunks.jsonl").write_text(json.dumps(chunk), encoding="utf-8")
            database = root / "boards.sqlite"
            build_index(root, database)
            for version in ("2", "V2.0", "2.1", "2.x"):
                with self.subTest(version=version):
                    results = search_results(database, "LED1", board=chunk["board"], hardware_version=version)
                    self.assertEqual(len(results), 1)
                    self.assertEqual(results[0]["citation"]["hardware_versions"], ["2.x"])
            for version in ("1", "3.0", "20.1"):
                self.assertEqual(search_results(database, "LED1", board=chunk["board"], hardware_version=version), [])

    def test_board_scope_survives_indexing_and_requires_matching_hardware(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            chunks = [{
                "chunk_id": f"{board}:led", "document_id": f"{board}-manual",
                "document_type": "board_manual", "document_title": "Test board manual",
                "document_version": "1.0", "source": "https://example.org/manual.pdf",
                "headings": ["LEDs"], "pages": [10], "text": "LED1 active low",
                "board": board, "hardware_versions": ["2"],
                "facts": [{"signal": "LED1", "pin": "P00.5", "active_level": "low"}],
            } for board in ("KIT_A2G_TC375_LITE", "KIT_A2G_TC375_ARD_SB")]
            (root / "chunks.jsonl").write_text(
                "\n".join(json.dumps(chunk) for chunk in chunks), encoding="utf-8",
            )
            database = root / "boards.sqlite"
            build_index(root, database)
            self.assertEqual(search_results(database, "LED1"), [])
            self.assertEqual(search_results(
                database, "LED1", board="KIT_A2G_TC375_LITE", hardware_version="1",
            ), [])
            results = search_results(
                database, "LED1", board="KIT_A2G_TC375_LITE", hardware_version="2",
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["citation"]["board"], "KIT_A2G_TC375_LITE")
            self.assertEqual(results[0]["applicability"], "matched")
            self.assertEqual(results[0]["facts"][0]["active_level"], "low")
            unknown = search_results(database, "LED1", board="KIT_A2G_TC375_LITE")
            self.assertEqual(unknown[0]["applicability"], "hardware_version_required")


class DocumentationSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_reviewed_tc375_led_and_button_facts(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for query in ("TC375 Lite V2 LED/button pins and polarity", "TC375 Lite V2 LED\u548c\u6309\u94ae\u5f15\u811a\u6709\u6548\u7535\u5e73", "KIT_A2G_TC375_LITE V2 LED button"):
                with self.subTest(query=query):
                    result = await _run({"query": query}, None)
                    self.assertFalse(result.is_error, result.content[0].text)
                    report = result.structured_content
                    self.assertEqual(report["resultCount"], 3)
                    self.assertFalse(report["requiresConfirmation"])
                    facts = {item["facts"][0]["signal"]: item for item in report["results"]}
                    for signal, pin, page in (("LED1", "P00.5", 10), ("LED2", "P00.6", 10), ("BUTTON1", "P00.7", 11)):
                        self.assertEqual(facts[signal]["facts"][0]["pin"], pin)
                        self.assertEqual(facts[signal]["facts"][0]["active_level"], "low")
                        self.assertEqual(facts[signal]["citation"]["pdf_pages"], [page])
                        self.assertEqual(facts[signal]["citation"]["document_version"], "2.2")

    async def test_board_scope_rejects_wrong_board_revision_and_unsupported_facts(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for arguments in (
                {"query": "TC375 LED1"},
                {"query": "LED1", "board": "KIT_A2G_TC375_ARD_SB", "hardwareVersion": "V2"},
                {"query": "LED1", "board": "KIT_A3G_TC4D7_LITE", "hardwareVersion": "V1"},
                {"query": "TC375 Lite V1 LED1"},
                {"query": "TC375 Lite V2.2 LED1"},
                {"query": "TC375 Lite V2 LED3"},
                {"query": "TC375 Lite V2 LED1 P00.4"},
                {"query": "TC375 Lite V2 \u6309\u94ae2"},
                {"query": "TC375 Lite V2 LED1 maximum current"},
            ):
                with self.subTest(arguments=arguments):
                    result = await _run(arguments, None)
                    self.assertFalse(result.is_error, result.content[0].text)
                    self.assertTrue(result.structured_content["abstained"])

    async def test_unknown_hardware_version_is_not_ready_for_code_generation(self) -> None:
        result = await _run({"query": "LED1", "board": "KIT_A2G_TC375_LITE"}, None)
        self.assertFalse(result.is_error, result.content[0].text)
        self.assertTrue(result.structured_content["requiresConfirmation"])
        self.assertFalse(result.structured_content["results"][0]["usableForCodeGeneration"])

    async def test_tc4d7_lite_facts_and_documented_hardware_series(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for version in ("V2", "V2.0", "V2.1", "V2.x"):
                result = await _run({"query": f"TC4D7 Lite {version} LED\u548c\u6309\u94ae"}, None)
                self.assertFalse(result.is_error, result.content[0].text)
                report = result.structured_content
                self.assertEqual(report["resultCount"], 3)
                facts = {item["facts"][0]["signal"]: item for item in report["results"]}
                for signal, pin in (("LED1", "P03.9"), ("LED2", "P03.10"), ("BUTTON1", "P03.11")):
                    self.assertEqual(facts[signal]["facts"][0]["pin"], pin)
                    self.assertEqual(facts[signal]["facts"][0]["active_level"], "low")
                    self.assertEqual(facts[signal]["citation"]["pdf_pages"], [9])
                    self.assertEqual(facts[signal]["citation"]["hardware_versions"], ["2.x"])
                    self.assertEqual(facts[signal]["citation"]["document_version"], "002-41555 Rev. *A")
                    self.assertTrue(facts[signal]["usableForCodeGeneration"])

    async def test_tc4d7_bpl_series_accepts_matching_specific_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bpl = Path(temp_dir) / "board_pin_label.bpl"
            bpl.write_text("// KIT_A3G_TC4D7_LITE V2.x\nF5, P3.9/LED1\n", encoding="utf-8")
            original = bpl.read_bytes()
            for version in (None, "V2.0", "V2.1"):
                result = await _run({"query": "LED1", "projectPath": temp_dir, "hardwareVersion": version}, None)
                self.assertFalse(result.is_error, result.content[0].text)
                item = result.structured_content["results"][0]
                self.assertEqual(item["bplCheck"], "matched")
                self.assertTrue(item["usableForCodeGeneration"])
            conflict = await _run({"query": "LED1", "projectPath": temp_dir, "hardwareVersion": "V3.0"}, None)
            self.assertTrue(conflict.structured_content["abstained"])
            self.assertEqual(conflict.structured_content["reason"], "project_bpl_conflict")
            self.assertEqual(bpl.read_bytes(), original)

    async def test_tc397_tft_uses_actual_led_designators_and_pins(self) -> None:
        for query in ("TC397 5V TFT V2.0 LEDs", "KIT_A2G_TC397_5V_TFT V2.0 \u706f"):
            result = await _run({"query": query, "topK": 10}, None)
            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["resultCount"], 4)
            facts = {item["facts"][0]["signal"]: item for item in result.structured_content["results"]}
            for signal, pin in (("D107", "P13.0"), ("D108", "P13.1"), ("D109", "P13.2"), ("D110", "P13.3")):
                self.assertEqual(facts[signal]["facts"][0]["pin"], pin)
                self.assertEqual(facts[signal]["facts"][0]["active_level"], "low")
                self.assertEqual(facts[signal]["citation"]["pdf_pages"], [14, 25])
                self.assertTrue(facts[signal]["usableForCodeGeneration"])
        specific = await _run({"query": "TC397 5V TFT V2.0 D110"}, None)
        self.assertEqual(specific.structured_content["resultCount"], 1)

    async def test_tc397_buttons_are_never_presented_as_gpio_inputs(self) -> None:
        for query in ("TC397 5V TFT V2.0 buttons", "TC397 5V TFT V2.0 \u590d\u4f4d\u548c\u5524\u9192"):
            result = await _run({"query": query}, None)
            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["resultCount"], 2)
            for item in result.structured_content["results"]:
                fact = item["facts"][0]
                expected = {"S101": ("/PORST", "low"), "S102": ("TLF35584.WAK/ENA", "high")}
                self.assertEqual((fact["pin"], fact["active_level"]), expected[fact["signal"]])
                self.assertFalse(fact["gpio"])
                self.assertEqual(item["usageRestriction"], "not_a_gpio")
                self.assertFalse(item["usableForCodeGeneration"])
        specific = await _run({"query": "TC397 5V TFT V2.0 S102 GPIO input"}, None)
        self.assertFalse(specific.is_error, specific.content[0].text)
        self.assertEqual(specific.structured_content["results"][0]["facts"][0]["signal"], "S102")

    async def test_tc397_scope_does_not_guess_board_revision_or_lite_labels(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for query in (
                "TC397 D107", "TC397 TFT V2.0 D107", "TC397 5V TFT V1.0 D107",
                "TC397 5V TFT V2.1 D107", "TC397 5V TFT V2.x D107",
                "TC397 5V TFT V2.0 LED1", "TC397 5V TFT V2.0 BUTTON1",
                "KIT_A2G_TC397_5V_TRB V2.0 D107", "KIT_A2G_TC397_3V3_TFT V2.0 D107",
                "TC4D7 Lite V2.0 D107", "TC375 Lite V2 S102",
            ):
                with self.subTest(query=query):
                    result = await _run({"query": query}, None)
                    self.assertFalse(result.is_error, result.content[0].text)
                    self.assertTrue(result.structured_content["abstained"])

    async def test_board_discovered_from_project_cannot_override_requested_chip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {}, clear=True):
            (Path(temp_dir) / "board_pin_label.bpl").write_text(
                "// KIT_A3G_TC4D7_LITE V2.x\nF5, P3.9/LED1\n", encoding="utf-8",
            )
            result = await _run({"query": "TC397 LED1", "projectPath": temp_dir}, None)
            self.assertTrue(result.is_error)
            self.assertIn("Project BPL board and requested device", result.content[0].text)

    async def test_project_bpl_conflict_blocks_electrical_facts_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bpl = Path(temp_dir) / "board_pin_label.bpl"
            bpl.write_text("// AURIX TC375 LITE KIT\n16, P0.6/LED1\n", encoding="utf-8")
            original = bpl.read_bytes()
            result = await _run({
                "query": "LED1", "board": "KIT_A2G_TC375_LITE", "hardwareVersion": "V2", "projectPath": temp_dir,
            }, None)
            self.assertFalse(result.is_error, result.content[0].text)
            self.assertTrue(result.structured_content["abstained"])
            item = result.structured_content["results"][0]
            self.assertEqual(item["applicability"], "pin_conflict")
            self.assertEqual(item["facts"], [])
            self.assertEqual(item["conflicts"][0]["bpl_pins"][0]["pin"], "P00.6")
            self.assertEqual(bpl.read_bytes(), original)

    async def test_explicit_board_and_query_conflicts_are_errors(self) -> None:
        for arguments in (
            {"query": "TC375 Lite V2 LED1", "board": "KIT_A2G_TC375_ARD_SB"},
            {"query": "TC375 Lite V1 LED1", "hardwareVersion": "V2"},
            {"query": "TC375 Lite V2 LED1", "device": "TC397"},
            {"query": "TC375 Lite V2 LED1", "family": "TC2xx"},
        ):
            result = await _run(arguments, None)
            self.assertTrue(result.is_error)

    async def test_generic_gpio_led_query_keeps_existing_chip_retrieval(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as index, patch(
            "aurix_mcp_server.tools.documentation_search.search_results", return_value=[],
        ) as search:
            result = await _run({"query": "TC375 GPIO output LED", "indexPath": index.name}, None)
        self.assertFalse(result.is_error, result.content[0].text)
        search.assert_called_once_with(Path(index.name).resolve(), "TC375 GPIO output LED", limit=3)

    async def test_project_bpl_and_reviewed_facts_agree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bpl = Path(temp_dir) / "board_pin_label.bpl"
            bpl.write_text("// AURIX TC375 LITE KIT V2\n16, P0.5/LED1\n17, P0.6/LED2\n18, P0.7/BUTTON1\n", encoding="utf-8")
            original = bpl.read_bytes()
            result = await _run({"query": "LED button", "projectPath": temp_dir}, None)
            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["resultCount"], 3)
            for item in result.structured_content["results"]:
                self.assertTrue(item["usableForCodeGeneration"])
                self.assertEqual(item["bplCheck"], "matched")
            self.assertEqual(bpl.read_bytes(), original)

    async def test_bpl_unavailable_or_identity_unknown_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "aurix_mcp_server.board_documentation.resolve_board_pins",
        ) as resolve:
            for pins in (
                {"status": "unavailable", "pins": []},
                {"status": "detected", "board": None, "pins": [{"pin": "P00.5", "aliases": ["LED1"]}]},
            ):
                resolve.return_value = pins
                result = await _run({
                    "query": "TC375 Lite V2 LED1", "projectPath": temp_dir,
                }, None)
                self.assertFalse(result.is_error, result.content[0].text)
                self.assertTrue(result.structured_content["requiresConfirmation"])
                self.assertFalse(result.structured_content["results"][0]["usableForCodeGeneration"])

    async def test_missing_bpl_labels_are_not_reported_as_pin_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "aurix_mcp_server.board_documentation.resolve_board_pins",
            return_value={"status": "detected", "board": "KIT_A2G_TC375_LITE", "pins": []},
        ):
            result = await _run({"query": "TC375 Lite V2 LED1", "projectPath": temp_dir}, None)
            self.assertFalse(result.is_error, result.content[0].text)
            item = result.structured_content["results"][0]
            self.assertEqual(item["bplCheck"], "not_mapped")
            self.assertEqual(item["missingSignals"], ["LED1"])
            self.assertEqual(item["facts"][0]["pin"], "P00.5")
            self.assertNotIn("conflicts", item)
            self.assertFalse(item["usableForCodeGeneration"])

    async def test_selected_board_does_not_override_query_device(self) -> None:
        with patch.dict(os.environ, {SELECTED_DEVICE_ENVIRONMENT_VARIABLE: "KIT_A2G_TC375_LITE"}, clear=True):
            matching = await _run({"query": "LED1", "hardwareVersion": "V2"}, None)
            other = await _run({"query": "TC397 LED1", "hardwareVersion": "V2"}, None)
        self.assertFalse(matching.is_error, matching.content[0].text)
        self.assertEqual(matching.structured_content["resultCount"], 1)
        self.assertTrue(other.structured_content["abstained"])

    def test_device_document_prefixes_keep_matching_and_common_manuals(self) -> None:
        self.assertEqual(
            query_document_prefixes("TC275 QSPI clock"),
            ("tc27x-",),
        )
        self.assertEqual(
            query_document_prefixes("TC375 GTM PWM"),
            ("tc37x-", "tc3xx-"),
        )
        self.assertEqual(
            query_document_prefixes("compare TC375 and TC397"),
            (),
        )

    def test_ethernet_capability_query_expands_to_product_interface_list(self) -> None:
        self.assertEqual(
            query_expansion_groups(
                "Does TC297 Ethernet support RGMII or only MII and RMII?"
            ),
            (("GMAC-UNIV", "supports", "PHY interfaces"),),
        )

    def test_explicit_index_path_precedes_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            explicit_index = root / "explicit.sqlite"
            environment_index = root / "environment.sqlite"
            explicit_index.touch()
            environment_index.touch()

            with patch.dict(
                os.environ,
                {INDEX_ENVIRONMENT_VARIABLE: str(environment_index)},
            ):
                resolved = _resolve_index_path(str(explicit_index))

            self.assertEqual(resolved, explicit_index.resolve())

    def test_family_selects_index_from_bundled_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            index = Path(temp_dir) / "aurix-tc3xx.sqlite"
            index.touch()
            with patch.dict(
                os.environ,
                {INDEX_DIRECTORY_ENVIRONMENT_VARIABLE: temp_dir},
                clear=True,
            ):
                resolved = _resolve_index_path(None, "tc3xx")

        self.assertEqual(resolved, index.resolve())

    async def test_query_device_precedes_selected_device(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tc2_index = root / "aurix-tc2xx.sqlite"
            tc3_index = root / "aurix-tc3xx.sqlite"
            tc2_index.touch()
            tc3_index.touch()
            with patch.dict(
                os.environ,
                {
                    INDEX_DIRECTORY_ENVIRONMENT_VARIABLE: temp_dir,
                    SELECTED_DEVICE_ENVIRONMENT_VARIABLE: "KIT_A2G_TC375_LITE",
                },
                clear=True,
            ), patch(
                "aurix_mcp_server.tools.documentation_search.search_results",
                return_value=[],
            ) as search:
                result = await _run(
                    {"query": "TC275 standby RAM"},
                    None,  # type: ignore[arg-type]
                )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["family"], "tc2xx")
        search.assert_called_once_with(tc2_index.resolve(), "TC275 standby RAM", limit=3)

    async def test_multiple_generations_are_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {INDEX_DIRECTORY_ENVIRONMENT_VARIABLE: temp_dir},
            clear=True,
        ):
            result = await _run(
                {"query": "compare TC275 with TC375"},
                None,  # type: ignore[arg-type]
            )

        self.assertTrue(result.is_error)
        self.assertIn("multiple AURIX generations", result.content[0].text)

    async def test_missing_index_is_an_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = await _run({"query": "AURIX GPIO"}, None)  # type: ignore[arg-type]

        self.assertTrue(result.is_error)
        self.assertIn("Pass device/family/indexPath", result.content[0].text)

    async def test_invalid_query_and_top_k_are_errors(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as index:
            invalid_inputs = (
                {"query": "", "indexPath": index.name},
                {"query": "AURIX", "topK": 0, "indexPath": index.name},
                {"query": "AURIX", "topK": True, "indexPath": index.name},
            )
            for arguments in invalid_inputs:
                with self.subTest(arguments=arguments):
                    result = await _run(arguments, None)  # type: ignore[arg-type]
                    self.assertTrue(result.is_error)

    async def test_success_preserves_citation_and_clamps_top_k(self) -> None:
        search_result = {
            "chunk_id": "manual:p00042:001",
            "document_id": "manual",
            "document_title": "AURIX User Manual",
            "document_type": "user_manual",
            "document_version": "1.0",
            "source": "manual.pdf",
            "section": "Ports > Output",
            "pages": "42",
            "score": -1.0,
            "excerpt": "Configure the port output mode.",
            "citation": {
                "document_id": "manual",
                "document_title": "AURIX User Manual",
                "document_version": "1.0",
                "document_type": "user_manual",
                "source": "manual.pdf",
                "section": "Ports > Output",
                "pdf_pages": [42],
                "page_basis": "physical_pdf",
                "excerpt": "Configure the port output mode.",
            },
        }
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as index, patch(
            "aurix_mcp_server.tools.documentation_search.search_results",
            return_value=[search_result],
        ) as search:
            result = await _run(
                {"query": "  port output  ", "topK": 100, "indexPath": index.name},
                None,  # type: ignore[arg-type]
            )

        self.assertFalse(result.is_error)
        search.assert_called_once_with(Path(index.name).resolve(), "port output", limit=MAX_TOP_K)
        self.assertEqual(result.structured_content["resultCount"], 1)
        self.assertFalse(result.structured_content["abstained"])
        self.assertEqual(
            result.structured_content["results"][0]["citation"]["pdf_pages"],
            [42],
        )
        self.assertIn("physical PDF page(s) 42", result.content[0].text)

    async def test_no_results_returns_abstention(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".sqlite") as index, patch(
            "aurix_mcp_server.tools.documentation_search.search_results",
            return_value=[],
        ):
            result = await _run(
                {"query": "unsupported device claim", "indexPath": index.name},
                None,  # type: ignore[arg-type]
            )

        self.assertFalse(result.is_error)
        self.assertTrue(result.structured_content["abstained"])
        self.assertEqual(result.structured_content["results"], [])


if __name__ == "__main__":
    unittest.main()