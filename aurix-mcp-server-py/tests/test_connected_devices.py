from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server import connected_devices, server_fastmcp
from aurix_mcp_server.board_documentation import board_evidence
from aurix_mcp_server.documentation_retrieval import hardware_version_matches
from aurix_mcp_server.tools import documentation_search

DETECT_OUTPUT = """AURIX Flasher Software Tool 3.1.0.0, built on 9/1/2026 9:05:13 AM
::Detecting connected devices on consecutive IDs...
::Connected device at id 0... [TC4x] TC4Dx NMG9HZ | BoardHw: AURIX LITE KIT V1.0 (TC4D7) LKASJE4G
::Connected device at id 1... [TC3x] TC37x DHACR2 | BoardHw: AURIX LITE KIT V2.0 (TC375) LK8PIMU6
::Detected 2 connected device(s).
Overall time: 90 ms
AURIXFlasher Exit Status: Pass
"""


def detected(devices):
    return patch.object(connected_devices, "detect_connected_devices", return_value={"ok": True, "devices": devices})


class ConnectedDeviceTests(unittest.TestCase):
    def test_parses_flasher_detect_output(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[1], {
            "id": 1, "generation": "TC3x", "family": "TC37x", "chipId": "DHACR2",
            "boardHardware": "AURIX LITE KIT V2.0 (TC375) LK8PIMU6", "board": "KIT_A2G_TC375_LITE",
            "hardwareVersion": "2.0", "part": "TC375", "serial": "LK8PIMU6",
        })
        self.assertEqual(devices[0]["board"], "KIT_A3G_TC4D7_LITE")
        # A TC4D7 lite Kit V2.1 reports V1.0: the revision of TC4x kits is not used.
        self.assertIsNone(devices[0]["hardwareVersion"])
        self.assertEqual(devices[0]["hardwareVersionNote"], connected_devices.TC4X_REVISION_NOTE)
        self.assertEqual(devices[0]["boardHardware"], "AURIX LITE KIT V1.0 (TC4D7) LKASJE4G")

    def test_tc4x_board_documentation_applies_to_every_revision(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        for arguments in ({"board": "KIT_A3G_TC4D7_LITE"}, {"board": "KIT_A3G_TC4D7_LITE", "hardwareVersion": "V1.0"}):
            with self.subTest(arguments=arguments), \
                    patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), detected(devices) as probe:
                payload = board_evidence(arguments, "Which pin drives LED1?", 3)
            probe.assert_not_called()
            self.assertIsNone(payload["hardwareVersion"])
            self.assertEqual(payload["hardwareVersionNote"], connected_devices.TC4X_REVISION_NOTE)
            self.assertEqual(payload["results"][0]["facts"][0]["pin"], "P03.9")
            self.assertTrue(payload["results"][0]["usableForCodeGeneration"])
            self.assertFalse(payload["requiresConfirmation"])

    def test_flash_list_devices_does_not_show_the_tc4x_board_id_revision(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        with patch.object(server_fastmcp, "detect_connected_devices", return_value={"ok": True, "devices": devices}):
            result = asyncio.run(server_fastmcp.flash_list_devices())
        tc4d7, tc375 = result.content[0].text.splitlines()[1:]
        self.assertNotIn("V1.0", tc4d7)
        self.assertIn("not reported for TC4x kits", tc4d7)
        self.assertIn("AURIX LITE KIT (TC4D7) LKASJE4G", tc4d7)
        self.assertIn("hardware 2.0 | AURIX LITE KIT V2.0 (TC375) LK8PIMU6", tc375)

    def test_reported_version_matches_manual_revision(self) -> None:
        self.assertTrue(hardware_version_matches("2.0", "2"))
        self.assertTrue(hardware_version_matches("V2", "2.0"))
        self.assertTrue(hardware_version_matches("2.0", "2.x"))
        self.assertFalse(hardware_version_matches("2.1", "2"))
        self.assertFalse(hardware_version_matches("1.0", "2"))

    def test_detected_version_makes_board_facts_usable_without_asking(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), detected(devices):
            payload = board_evidence({"board": "KIT_A2G_TC375_LITE"}, "Which pin drives LED1?", 3)
        self.assertEqual(payload["hardwareVersion"], "2.0")
        self.assertEqual(payload["hardwareVersionDetected"]["boardHardware"], "AURIX LITE KIT V2.0 (TC375) LK8PIMU6")
        self.assertTrue(payload["results"][0]["usableForCodeGeneration"])
        self.assertFalse(payload["requiresConfirmation"])

    def test_explicit_version_wins_and_absent_kit_still_requires_version(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), detected(devices[:1]):
            missing = board_evidence({"board": "KIT_A2G_TC375_LITE"}, "Which pin drives LED1?", 3)
        self.assertIsNone(missing["hardwareVersion"])
        self.assertFalse(missing["results"][0]["usableForCodeGeneration"])
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), detected(devices) as probe:
            explicit = board_evidence({"board": "KIT_A2G_TC375_LITE", "hardwareVersion": "V2"}, "LED1 pin", 3)
        self.assertEqual(explicit["hardwareVersion"], "2")
        self.assertNotIn("hardwareVersionDetected", explicit)
        probe.assert_not_called()

    def test_old_flasher_without_board_report_falls_back_to_newer_one(self) -> None:
        old = "AURIX Flasher Software Tool 3.0.10.0\n::Connected to device... [TC4x] TC4Dx \nAURIXFlasher Exit Status: Pass\n"
        outputs = {"old.exe": old, "new.exe": DETECT_OUTPUT}
        run = lambda command, **_: type("Completed", (), {"stdout": outputs[command[0]].encode(), "stderr": b""})()
        with tempfile.TemporaryDirectory() as home, \
                patch.object(connected_devices, "LAST_FLASHER_FILE", os.path.join(home, "detect-flasher.json")), \
                patch.object(connected_devices, "find_flashers", return_value=["old.exe", "new.exe"]), \
                patch.object(connected_devices.subprocess, "run", side_effect=run):
            result = connected_devices.detect_connected_devices(use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["flasherPath"], "new.exe")
        self.assertEqual(result["devices"][1]["hardwareVersion"], "2.0")
        with patch.object(connected_devices.subprocess, "run", side_effect=run):
            only_old = connected_devices.detect_connected_devices("old.exe", use_cache=False)
        self.assertFalse(only_old["ok"])
        self.assertIn("3.1 or newer", only_old["error"])

    def test_no_connected_kit_is_an_empty_list_not_an_error(self) -> None:
        # Real AURIXFlasher 3.1.0.0 "-detect all" output with no kit attached.
        empty = (
            "AURIX Flasher Software Tool 3.1.0.0, built on 9/1/2026 9:05:13 AM\n"
            "::Detecting connected devices on consecutive IDs...\n"
            "::No connected devices found starting from id 0.\n"
            "Overall time: 97 ms\n"
            "AURIXFlasher Exit Status: Fail\n"
        )
        failed = "AURIX Flasher Software Tool 3.1.0.0\n::Detect all error [DAS server not found]\n"
        outputs = {"empty.exe": empty, "failed.exe": failed}
        run = lambda command, **_: type("Completed", (), {"stdout": outputs[command[0]].encode(), "stderr": b""})()
        with tempfile.TemporaryDirectory() as home, \
                patch.object(connected_devices, "LAST_FLASHER_FILE", os.path.join(home, "detect-flasher.json")), \
                patch.object(connected_devices.subprocess, "run", side_effect=run) as probe:
            with patch.object(connected_devices, "find_flashers", return_value=["empty.exe", "other.exe"]):
                result = connected_devices.detect_connected_devices(use_cache=False)
            unexpected = connected_devices.detect_connected_devices("failed.exe", use_cache=False)
        self.assertEqual(result, {"ok": True, "flasherPath": "empty.exe", "devices": []})
        # An empty answer is final: other flashers would report the same bus.
        self.assertEqual(probe.call_count, 2)
        self.assertFalse(unexpected["ok"])
        self.assertNotIn("3.1 or newer", unexpected["error"])
        self.assertIn("Detect all error [DAS server not found]", unexpected["error"])
        with patch.object(server_fastmcp, "detect_connected_devices", return_value=result):
            listed = asyncio.run(server_fastmcp.flash_list_devices())
        self.assertFalse(listed.isError)
        self.assertIn("0 connected device(s).", listed.content[0].text)
        self.assertIn("check the USB connection", listed.content[0].text)

    def test_flashers_without_board_report_are_skipped_and_last_good_comes_first(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            def flasher(*parts: str) -> str:
                path = os.path.join(root, *parts, "AURIXFlasher.exe")
                os.makedirs(os.path.dirname(path))
                open(path, "wb").close()
                return path
            old = flasher("ADS", "tools", "AurixFlasherSoftwareTool_v3.0.10")
            acs24 = flasher("ACS24", "AurixFlasherSoftwareTool", "3.1.0.0")
            acs25 = flasher("ACS25", "AurixFlasherSoftwareTool", "3.2.0.0")
            remembered = os.path.join(root, "detect-flasher.json")
            with patch.object(connected_devices, "LAST_FLASHER_FILE", remembered), \
                    patch.object(connected_devices, "_FLASHER_GLOBS", (os.path.join(root, "*", "**", "AURIXFlasher.exe"),)), \
                    patch.object(connected_devices.glob, "glob", side_effect=lambda pattern: [old, acs24, acs25]), \
                    patch("aurix_mcp_server.tools.flash_program._probe_known_flasher_locations", return_value=old):
                self.assertEqual(connected_devices.find_flashers(), [acs25, acs24])
                connected_devices._remember_flasher(acs24)
                self.assertEqual(connected_devices.find_flashers(), [acs24, acs25])

    def test_detection_is_off_unless_enabled_by_the_host(self) -> None:
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "0"}), detected([]) as probe:
            payload = board_evidence({"board": "KIT_A2G_TC375_LITE"}, "Which pin drives LED1?", 3)
        probe.assert_not_called()
        self.assertIsNone(payload["hardwareVersion"])

    def test_compact_output_reports_detected_version(self) -> None:
        devices = connected_devices.parse_detect_output(DETECT_OUTPUT)
        with patch.dict("os.environ", {"AURIX_DEVICE_DETECTION": "1"}), detected(devices):
            result = asyncio.run(documentation_search._run(
                {"query": "Which pin drives LED1?", "board": "KIT_A2G_TC375_LITE"}, None,
            ))
        self.assertFalse(result.is_error, result.content[0].text)
        self.assertIn("Board hardware version 2.0 detected", result.content[0].text)
        self.assertIn("code generation yes", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
