"""Tests for project-local iLLD release reporting."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.illd_version import detect_illd_version, format_illd_version
from aurix_mcp_server.tooldef import ToolContext, ToolResult
from aurix_mcp_server.tools import ads_create_project, scan_project


def write_version(root: Path, version: tuple[int, int, int], device: str = "TC3xx") -> Path:
    header = root / "Libraries" / "iLLD" / device / "Tricore" / "IfxLldVersion.h"
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text("\n".join(
        f"#define IFX_LLD_VERSION_{part} {value}"
        for part, value in zip(("MAJOR", "MINOR", "REVISION"), version)
    ) + "\n", encoding="utf-8")
    return header


def run_create(cache: Path, workspace: Path | None = None) -> ToolResult:
    args = {"device": "TC375"}
    if workspace is not None:
        args["workspace"] = str(workspace)
    with (
        patch.object(ads_create_project, "resolve_studio_dir", return_value="unused-studio"),
        patch.object(ads_create_project, "create_project_in_cache", return_value={
            "cachePath": str(cache), "info": ads_create_project.DEVICE_MAP["TC375"],
            "details": ["Using cached template"],
        }),
        patch.object(ads_create_project, "generate_makefile", return_value=[]),
    ):
        return asyncio.run(ads_create_project._run(args, ToolContext(send_progress=AsyncMock())))


class IlldVersionTests(unittest.TestCase):
    def test_release_macros_and_relative_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            header = write_version(Path(temp_dir), (1, 20, 0))
            result = detect_illd_version(temp_dir)

            self.assertEqual(result, {
                "status": "detected",
                "version": "1.20.0",
                "sources": [{
                    "path": header.relative_to(temp_dir).as_posix(),
                    "version": "1.20.0",
                }],
            })
            self.assertIn("1.20.0", format_illd_version(result))

    def test_tc4xx_root_header_uses_patch_macro(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            header = Path(temp_dir) / "Libraries" / "IfxLldVersion.h"
            header.parent.mkdir()
            header.write_text(
                "#ifndef IFX_LLD_VERSION_H\n#define IFX_LLD_VERSION_H 1\n"
                "#define IFX_LLD_VERSION_MAJOR (2U) /* release */\n"
                "#define IFX_LLD_VERSION_MINOR 4 // release\n"
                "#define IFX_LLD_VERSION_PATCH 0\n#endif\n",
                encoding="utf-8-sig",
            )
            result = detect_illd_version(temp_dir)
            self.assertEqual(result["version"], "2.4.0")
            self.assertEqual(result["sources"][0]["path"], "Libraries/IfxLldVersion.h")

    def test_unverified_or_ambiguous_macro_formats_remain_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for extra in (
                "#define IFX_LLD_VERSION_BUILD 1\n",
                "#define IFX_LLD_VERSION_MAJOR 2\n",
                "#define IFX_LLD_VERSION_PATCH 0\n",
            ):
                with self.subTest(extra=extra):
                    header = write_version(Path(temp_dir), (1, 20, 0))
                    header.write_text(header.read_text(encoding="utf-8") + extra, encoding="utf-8")
                    self.assertEqual(detect_illd_version(temp_dir)["status"], "unknown")

    def test_commented_defines_do_not_count_as_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            header = write_version(Path(temp_dir), (1, 20, 0))
            header.write_text("/*\n" + header.read_text(encoding="utf-8") + "*/", encoding="utf-8")
            self.assertEqual(detect_illd_version(temp_dir)["status"], "unknown")

    def test_truncated_scan_cannot_claim_a_single_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            write_version(Path(temp_dir), (1, 20, 0))
            result = detect_illd_version(temp_dir, scan_complete=False)
            self.assertEqual(result["status"], "unknown")
            self.assertIsNone(result["version"])
            self.assertEqual(result["reason"], "scan_limit")
            self.assertIn("increase maxFiles", format_illd_version(result))

    def test_missing_declaration_does_not_guess_from_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="iLLD_9_99_0_") as temp_dir:
            result = detect_illd_version(temp_dir)
            self.assertEqual(result, {"status": "unknown", "version": None, "sources": []})
            self.assertIn("unknown", format_illd_version(result))

    def test_conflicting_releases_do_not_select_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            write_version(Path(temp_dir), (1, 20, 0))
            write_version(Path(temp_dir), (1, 21, 0), "TC37A")
            result = detect_illd_version(temp_dir)
            self.assertEqual(result["status"], "conflict")
            self.assertIsNone(result["version"])
            self.assertIn("1.20.0, 1.21.0", format_illd_version(result))

    def test_incomplete_or_unreadable_declaration_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_version(root, (1, 20, 0))
            incomplete = write_version(root, (1, 20, 0), "TC37A")
            incomplete.write_text("#define IFX_LLD_VERSION_MAJOR 1\n", encoding="utf-8")
            self.assertEqual(detect_illd_version(temp_dir)["status"], "unknown")
            incomplete.unlink()
            result = detect_illd_version(temp_dir, [incomplete.relative_to(root).as_posix()])
            self.assertEqual(result["status"], "unknown")


class ProjectVersionReportingTests(unittest.TestCase):
    def test_create_without_workspace_reports_cached_library(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir:
            cache = Path(cache_dir)
            header = write_version(cache, (1, 20, 0))
            result = run_create(cache)

            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["illdVersion"]["version"], "1.20.0")
            self.assertIn("iLLD version: 1.20.0", result.content[0].text)
            write_version(cache, (1, 21, 0))
            self.assertEqual(run_create(cache).structured_content["illdVersion"]["version"], "1.21.0")
            self.assertTrue(header.is_file())

    def test_create_reports_preserved_workspace_not_template_version(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            cache = Path(cache_dir)
            workspace = Path(workspace_dir)
            write_version(cache, (1, 21, 0))
            header = write_version(workspace, (1, 20, 0))
            original = header.read_bytes()
            (workspace / "Configurations").mkdir()
            (workspace / "Configurations" / "Ifx_Cfg.h").touch()

            result = run_create(cache, workspace)

            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["illdVersion"]["version"], "1.20.0")
            self.assertEqual(header.read_bytes(), original)
            self.assertIn("iLLD version: 1.20.0", result.content[0].text)

    def test_create_reports_library_after_deployment(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            cache = Path(cache_dir)
            workspace = Path(workspace_dir)
            write_version(cache, (1, 20, 0))

            result = run_create(cache, workspace)

            self.assertFalse(result.is_error, result.content[0].text)
            version = result.structured_content["illdVersion"]
            self.assertEqual(version["version"], "1.20.0")
            self.assertTrue((workspace / version["sources"][0]["path"]).is_file())

    def test_create_succeeds_when_version_is_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir:
            result = run_create(Path(cache_dir))
            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["illdVersion"]["status"], "unknown")
            self.assertIn("iLLD version: unknown", result.content[0].text)

    def test_scan_reports_version_in_text_and_structured_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            write_version(Path(temp_dir), (1, 20, 0))

            result = asyncio.run(scan_project._run(
                {"projectPath": temp_dir}, ToolContext(send_progress=AsyncMock()),
            ))

            self.assertFalse(result.is_error, result.content[0].text)
            self.assertEqual(result.structured_content["scan"]["illdVersion"]["version"], "1.20.0")
            self.assertIn("iLLD version: 1.20.0", result.content[0].text)

    def test_scan_honors_exclusions_and_reports_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_version(root, (1, 20, 0))
            write_version(root / "backup", (1, 21, 0))
            write_version(root / "Debug", (1, 22, 0))
            excluded = scan_project._scan_project(temp_dir, ["backup"], 5000)
            self.assertEqual(excluded["illdVersion"]["version"], "1.20.0")
            self.assertEqual(len(excluded["illdVersion"]["sources"]), 1)
            included = scan_project._scan_project(temp_dir, [], 5000)
            self.assertEqual(included["illdVersion"]["status"], "conflict")
            self.assertEqual(len(included["illdVersion"]["sources"]), 2)

    def test_scan_limit_keeps_version_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            write_version(Path(temp_dir), (1, 20, 0))
            result = scan_project._scan_project(temp_dir, [], 1)
            self.assertEqual(result["illdVersion"]["status"], "unknown")
            self.assertEqual(result["illdVersion"]["reason"], "scan_limit")


if __name__ == "__main__":
    unittest.main()