from __future__ import annotations

import os
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
    query_document_prefixes,
    query_expansion_groups,
)


class DocumentationSearchTests(unittest.IsolatedAsyncioTestCase):
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