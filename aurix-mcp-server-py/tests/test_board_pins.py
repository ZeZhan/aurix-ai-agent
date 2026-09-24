"""Tests for board pin label parsing and project integration."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.board_pins import (
    BPL_FILENAME, deploy_board_pins, normalize_board, read_bpl,
    resolve_board_pins, selected_board,
)
from aurix_mcp_server.tools import ads_create_project, scan_project
from aurix_mcp_server.tooldef import ToolResult


TC375_BPL = (
    "// Generated with gdd version 3.3.0\n"
    "// Device: TC37xpd, Package: QFP, Pin number:4\n"
    "// AURIX TC375 LITE KIT\n"
    "16, P0.5/LED1\n17, P0.6/LED2\n18, P0.7/BUTTON1\n19, VSS\n"
)


class BoardPinParsingTests(unittest.TestCase):
    def parse(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / BPL_FILENAME
            path.write_text(text, encoding="utf-8-sig")
            return read_bpl(path)

    def test_tc375_labels_preserve_evidence_without_guessing_polarity(self) -> None:
        result = self.parse(TC375_BPL)
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["board"], "KIT_A2G_TC375_LITE")
        self.assertEqual(result["device"], "TC37xpd")
        self.assertEqual(result["package"], "QFP")
        self.assertIsNone(result["hardwareVersion"])
        self.assertEqual(result["electricalProperties"], "not_provided")
        self.assertEqual(result["totalPins"], 4)
        self.assertEqual(result["pins"][0], {
            "position": "16", "pin": "P00.5", "aliases": ["LED1"],
            "line": 4, "raw": "16, P0.5/LED1",
        })
        self.assertEqual(len(result["pins"]), 3)
        self.assertEqual(result["source"]["kind"], "project")

    def test_bga_and_multiple_aliases_are_not_treated_as_connections(self) -> None:
        result = self.parse(
            "// AURIX TC4D7 LITE KIT, KIT_A3G_TC4D7_LITE V2.x\n"
            "F5, P3.9/LED1\nU1, P40.14/AN29/NC\nJ16, TCK/DAP0\n"
        )
        self.assertEqual(result["board"], "KIT_A3G_TC4D7_LITE")
        self.assertEqual(result["hardwareVersion"], "2.x")
        self.assertEqual(result["pins"][0]["pin"], "P03.9")
        self.assertEqual(result["pins"][1]["aliases"], ["AN29", "NC"])
        self.assertEqual(result["pins"][2]["pin"], "TCK")

    def test_invalid_records_do_not_return_partial_mappings(self) -> None:
        for suffix in ("16, P0.7/BUTTON1", "bad row", "20, P0.8/", "../20, P0.8/LED3"):
            with self.subTest(suffix=suffix):
                result = self.parse(TC375_BPL + suffix)
                self.assertEqual(result["status"], "invalid")
                self.assertEqual(result["pins"], [])

    def test_extra_pad_is_a_warning_not_an_invalid_file(self) -> None:
        result = self.parse(TC375_BPL + "177, VSS\n")
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["totalPins"], 5)
        self.assertTrue(result["warnings"])

    def test_board_names_are_specific_and_path_safe(self) -> None:
        self.assertEqual(normalize_board(" tc375 lk "), "KIT_A2G_TC375_LITE")
        self.assertEqual(normalize_board("kit_a2g_tc375_ard_sb"), "KIT_A2G_TC375_ARD_SB")
        for value in ("TC375", "../KIT_A2G_TC375_LITE", "KIT_A2G/TC375", 123):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_board(value)


class BoardPinLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.studio = self.root / "acs/eclipse"
        self.studio.mkdir(parents=True)
        self.board = "KIT_A2G_TC375_LITE"
        self.bsp = self.root / "acs/libstore/DeviceFeatures/pack/0.0.0/BSP" / self.board
        self.bsp.mkdir(parents=True)
        (self.bsp / BPL_FILENAME).write_text(TC375_BPL, encoding="utf-8")

    def test_installation_lookup_is_read_only(self) -> None:
        result = resolve_board_pins(str(self.workspace), self.board, str(self.studio))
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["boardIdentitySource"], "bsp_directory")
        self.assertEqual(result["source"]["kind"], "installation")
        self.assertFalse((self.workspace / BPL_FILENAME).exists())

    def test_project_file_wins_and_is_never_overwritten(self) -> None:
        project_file = self.workspace / BPL_FILENAME
        project_file.write_text(TC375_BPL.replace("P0.5/LED1", "P0.9/LED1"), encoding="utf-8")
        original = project_file.read_bytes()
        result = deploy_board_pins(str(self.workspace), self.board, str(self.studio))
        self.assertEqual(result["deployment"], "preserved")
        self.assertEqual(result["pins"][0]["pin"], "P00.9")
        self.assertEqual(project_file.read_bytes(), original)

    def test_conflicting_or_invalid_project_file_never_falls_back(self) -> None:
        project_file = self.workspace / BPL_FILENAME
        for text, status in (
            (TC375_BPL.replace("AURIX TC375 LITE KIT", "KIT_A2G_TC375_ARD_SB"), "conflict"),
            ("broken", "invalid"),
        ):
            with self.subTest(status=status):
                project_file.write_text(text, encoding="utf-8")
                result = deploy_board_pins(str(self.workspace), self.board, str(self.studio))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["pins"], [])
                self.assertEqual(project_file.read_text(encoding="utf-8"), text)

    def test_deployment_copies_exact_file_only_to_project(self) -> None:
        result = deploy_board_pins(str(self.workspace), self.board, str(self.studio))
        self.assertEqual(result["deployment"], "copied")
        self.assertEqual((self.workspace / BPL_FILENAME).read_bytes(), (self.bsp / BPL_FILENAME).read_bytes())
        self.assertEqual(result["source"]["kind"], "project")
        self.assertEqual(result["source"]["copiedFrom"], str((self.bsp / BPL_FILENAME).resolve()))

    def test_missing_resources_and_ambiguous_device_do_not_guess(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(selected_board(None, str(self.workspace), "TC375"))
        self.assertEqual(resolve_board_pins(str(self.workspace))["status"], "not_found")
        result = resolve_board_pins(str(self.workspace), "KIT_A2G_TC375_ARD_SB", str(self.studio))
        self.assertEqual(result["status"], "not_found")
        self.assertFalse((self.workspace / BPL_FILENAME).exists())

    def test_newest_pack_uses_numeric_version_order(self) -> None:
        for pack_version, pin in (("1.9.0", "P0.8"), ("1.10.0", "P0.9")):
            directory = self.root / "acs/libstore/DeviceFeatures/pack" / pack_version / "BSP" / self.board
            directory.mkdir(parents=True)
            (directory / BPL_FILENAME).write_text(TC375_BPL.replace("P0.5", pin), encoding="utf-8")
        self.assertEqual(resolve_board_pins(str(self.workspace), self.board, str(self.studio))["pins"][0]["pin"], "P00.9")

    def test_unknown_project_board_is_not_claimed_to_match_selection(self) -> None:
        (self.workspace / BPL_FILENAME).write_text("16, P0.5/LED1\n", encoding="utf-8")
        result = resolve_board_pins(str(self.workspace), self.board, str(self.studio))
        self.assertIsNone(result["board"])
        self.assertEqual(result["boardIdentitySource"], "unknown")
        self.assertTrue(result["warnings"])

    def create(
        self, *, board: str | None = None, deploy: bool = True, device: str = "TC375",
    ) -> ToolResult:
        cache = self.root / "cache"
        cache.mkdir(exist_ok=True)
        args = {"device": device, "board": board or self.board}
        if deploy:
            args["workspace"] = str(self.workspace)
        with (
            patch.object(ads_create_project, "resolve_studio_dir", return_value=str(self.studio)),
            patch.object(ads_create_project, "create_project_in_cache", return_value={
                "cachePath": str(cache), "info": ads_create_project.DEVICE_MAP["TC375"], "details": [],
            }),
            patch.object(ads_create_project, "generate_makefile", return_value=[]),
        ):
            return asyncio.run(ads_create_project._run(args, None))

    def test_create_deploys_bpl_but_does_not_contaminate_device_cache(self) -> None:
        result = self.create()
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["boardPins"]["deployment"], "copied")
        self.assertTrue((self.workspace / BPL_FILENAME).is_file())
        self.assertFalse((self.root / "cache" / BPL_FILENAME).exists())

    def test_cache_only_create_returns_installation_evidence_without_copy(self) -> None:
        result = self.create(deploy=False)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["boardPins"]["source"]["kind"], "installation")
        self.assertFalse((self.root / "cache" / BPL_FILENAME).exists())

    def test_create_rejects_different_device_before_deploying(self) -> None:
        result = self.create(board="KIT_A3G_TC4D7_LITE")
        self.assertTrue(result.is_error)
        self.assertFalse((self.workspace / BPL_FILENAME).exists())

    def test_scan_uses_selected_board_but_leaves_project_unchanged(self) -> None:
        with (
            patch.dict("os.environ", {"AURIX_SELECTED_DEVICE": self.board}, clear=True),
            patch.object(ads_create_project, "resolve_studio_dir", return_value=str(self.studio)),
        ):
            result = asyncio.run(scan_project._run({"projectPath": str(self.workspace)}, None))
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["scan"]["boardPins"]["pins"][0]["pin"], "P00.5")
        self.assertEqual(list(self.workspace.iterdir()), [])

    def test_invalid_bpl_does_not_break_source_scan(self) -> None:
        (self.workspace / BPL_FILENAME).write_text("broken", encoding="utf-8")
        (self.workspace / "main.c").touch()
        result = scan_project._scan_project(str(self.workspace), [], 100)
        self.assertEqual(result["boardPins"]["status"], "invalid")
        self.assertEqual(result["cSources"], ["main.c"])

    def test_same_device_different_board_arguments_are_rejected(self) -> None:
        result = self.create(device="KIT_A2G_TC375_ARD_SB")
        self.assertTrue(result.is_error)
        self.assertFalse((self.workspace / BPL_FILENAME).exists())

    def test_installation_board_header_conflict_has_no_usable_pins(self) -> None:
        (self.bsp / BPL_FILENAME).write_text(
            TC375_BPL.replace("AURIX TC375 LITE KIT", "KIT_A2G_TC375_ARD_SB"), encoding="utf-8",
        )
        result = self.create()
        self.assertEqual(result.structured_content["boardPins"]["status"], "conflict")
        self.assertFalse((self.workspace / BPL_FILENAME).exists())

    def test_no_studio_does_not_break_project_scan(self) -> None:
        with patch.object(ads_create_project, "resolve_studio_dir", side_effect=FileNotFoundError("No ACS")):
            result = asyncio.run(scan_project._run({"projectPath": str(self.workspace), "board": self.board}, None))
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["scan"]["boardPins"]["status"], "unavailable")

    def test_board_selection_precedence_and_explicit_chip_rejection(self) -> None:
        with patch.dict("os.environ", {"AURIX_SELECTED_DEVICE": "KIT_A3G_TC4D7_LITE"}, clear=True):
            self.assertEqual(selected_board(self.board, str(self.workspace)), self.board)
            self.assertEqual(selected_board(None, str(self.workspace), "KIT_A2G_TC375_ARD_SB"), "KIT_A2G_TC375_ARD_SB")
            with self.assertRaises(ValueError):
                selected_board("TC375", str(self.workspace))

    def test_public_mcp_wrappers_forward_board_and_pin_evidence(self) -> None:
        from aurix_mcp_server import server_fastmcp

        (self.workspace / BPL_FILENAME).write_text(TC375_BPL, encoding="utf-8")
        scanned = asyncio.run(server_fastmcp.project_scan(projectPath=str(self.workspace), board=self.board))
        self.assertFalse(scanned.isError)
        self.assertEqual(scanned.structuredContent["scan"]["boardPins"]["pins"][0]["pin"], "P00.5")
        self.assertIn("LED1", scanned.content[0].text)
        with patch.object(server_fastmcp, "ads_create_project_run", return_value=ToolResult.text("ok")) as create:
            asyncio.run(server_fastmcp.ads_create_project("TC375", str(self.workspace), self.board))
        self.assertEqual(create.call_args.args[0]["board"], self.board)

    def test_ads_initializer_layout_is_supported(self) -> None:
        studio = self.root / "ads"
        bsp = studio / "build_system/bundled-artefacts-repo/project-initializer/tricore-tc3xx/1.0/BSP" / self.board
        bsp.mkdir(parents=True)
        (bsp / BPL_FILENAME).write_text(TC375_BPL, encoding="utf-8")
        result = resolve_board_pins(str(self.workspace), self.board, str(studio))
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["board"], self.board)


if __name__ == "__main__":
    unittest.main()