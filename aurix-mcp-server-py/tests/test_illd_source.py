from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server.illd_version import quick_illd_version
from aurix_mcp_server.tools import ads_create_project as acp
from aurix_mcp_server.tools import examples

VERSION_HEADER = (
    "#define IFX_LLD_VERSION_MAJOR 1\n#define IFX_LLD_VERSION_MINOR 22\n#define IFX_LLD_VERSION_PATCH 0\n"
)


class IlldSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        cache_patch = patch.object(acp, "DEVICE_PROJECTS_CACHE", str(self.root / "device_projects"))
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def ide(self, name: str, content: bytes) -> tuple[str, acp.InitializerPaths]:
        ide = self.root / name
        zip_path = ide / "TC37A.zip"
        zip_path.parent.mkdir(parents=True)
        zip_path.write_bytes(content)
        paths = acp.InitializerPaths(
            root=str(ide), illd_zip=str(zip_path), source_templates="", config_templates="",
            linker_tasking="", linker_gcc="",
        )
        return str(ide), paths

    def cached_template(self, source: dict) -> Path:
        cache = self.root / "device_projects" / "TC37A"
        cache.mkdir(parents=True)
        (cache / ".device_project_ready").write_text(json.dumps({
            "templateVersion": acp.TEMPLATE_VERSION, "illdSource": source,
        }), encoding="utf-8")
        return cache

    def test_template_is_reused_only_for_the_same_ide_illd(self) -> None:
        acs, acs_paths = self.ide("ACS", b"iLLD 1.22")
        self.cached_template(acp._illd_source(acs_paths, acs))
        with patch.object(acp, "find_project_initializer", return_value=acs_paths):
            reused = acp.create_project_in_cache("TC375", acs)
        self.assertIn("TC37A.zip from", acp.describe_illd_source(reused["illdSource"]))
        self.assertTrue(reused["details"][0].startswith("Using cached project template"))

        ads, ads_paths = self.ide("ADS", b"iLLD 1.20 (different archive)")
        with patch.object(acp, "find_project_initializer", return_value=ads_paths), \
                patch.object(acp, "extract_zip", side_effect=RuntimeError("regenerating")):
            with self.assertRaisesRegex(RuntimeError, "regenerating"):
                acp.create_project_in_cache("TC375", ads)

    def test_template_without_recorded_source_is_regenerated(self) -> None:
        acs, acs_paths = self.ide("ACS", b"iLLD 1.22")
        self.cached_template(None)  # created by an older extension version
        with patch.object(acp, "find_project_initializer", return_value=acs_paths), \
                patch.object(acp, "extract_zip", side_effect=RuntimeError("regenerating")):
            with self.assertRaisesRegex(RuntimeError, "regenerating"):
                acp.create_project_in_cache("TC375", acs)

    def test_ide_without_this_illd_keeps_a_valid_cached_template(self) -> None:
        acs, acs_paths = self.ide("ACS", b"iLLD 1.22")
        self.cached_template(acp._illd_source(acs_paths, acs))
        with patch.object(acp, "find_project_initializer", side_effect=FileNotFoundError("no TC37A zip")):
            result = acp.create_project_in_cache("TC375", str(self.root / "other-ide"))
        self.assertIn("has no iLLD", result["details"][0])
        self.assertEqual(result["illdSource"]["zip"], acs_paths.illd_zip)


class IlldVersionReportTests(unittest.TestCase):
    def project(self, with_header: bool = True) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        tricore = root / "Libraries" / "iLLD" / "TC3xx" / "Tricore"
        tricore.mkdir(parents=True)
        if with_header:
            (tricore / "IfxLldVersion.h").write_text(VERSION_HEADER, encoding="utf-8")
        return root

    def test_quick_lookup_reads_the_declared_version(self) -> None:
        result = quick_illd_version(str(self.project()))
        self.assertEqual(result["status"], "detected")
        self.assertEqual(result["version"], "1.22.0")

    def test_project_without_illd_has_no_version(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            self.assertIsNone(quick_illd_version(empty))

    def test_import_note_names_the_example_when_it_bundles_illd(self) -> None:
        root = str(self.project())
        text, version = examples._illd_note(root, ["Libraries/iLLD/TC3xx/Tricore/Port/IfxPort.c"], "Blinky_LED_1")
        self.assertIn("1.22.0", text)
        self.assertIn("bundled with example Blinky_LED_1", text)
        self.assertEqual(version["version"], "1.22.0")
        text, _ = examples._illd_note(root, ["Cpu0_Main.c"], "Blinky_LED_1")
        self.assertIn("already in the project", text)


if __name__ == "__main__":
    unittest.main()
