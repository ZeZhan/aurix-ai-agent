from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server import connected_devices
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
        self.assertEqual(devices[0]["hardwareVersion"], "1.0")

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
        with patch.object(connected_devices, "find_flashers", return_value=["old.exe", "new.exe"]), \
                patch.object(connected_devices.subprocess, "run", side_effect=run):
            result = connected_devices.detect_connected_devices(use_cache=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["flasherPath"], "new.exe")
        self.assertEqual(result["devices"][1]["hardwareVersion"], "2.0")
        with patch.object(connected_devices.subprocess, "run", side_effect=run):
            only_old = connected_devices.detect_connected_devices("old.exe", use_cache=False)
        self.assertFalse(only_old["ok"])
        self.assertIn("3.1 or newer", only_old["error"])

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
