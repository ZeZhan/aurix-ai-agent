"""Regression tests for AURIX build and flash tool discovery."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.tools.build_run import (  # noqa: E402
    _build_path_env,
    _normalize_build_command,
)
from aurix_mcp_server.tools.ads_create_project import (  # noqa: E402
    deploy_template_dependencies,
    discover_studio_candidates,
    find_gcc_cross_compile_prefix,
    is_studio_directory,
)
from aurix_mcp_server.tools.flash_program import (  # noqa: E402
    _configured_studio_roots,
    _probe_known_flasher_locations,
)


class BuildRunDiscoveryTests(unittest.TestCase):
    def test_build_intent_alias_uses_default_command(self) -> None:
        self.assertEqual(_normalize_build_command("build"), "make --output-sync -j20 all")
        self.assertEqual(_normalize_build_command("build project", "make clean all"), "make clean all")

    def test_effective_paths_report_configured_acs_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_dir = root / "eclipse" / "tools"
            gcc_dir = root / "eclipse" / "tricore-gcc11" / "bin"
            make_dir.mkdir(parents=True)
            gcc_dir.mkdir(parents=True)
            (make_dir / "make.exe").touch()

            with patch.dict(os.environ, {
                "AURIX_ADS_STUDIO_PATH": str(root),
                "AURIX_IDE_PATH": str(root),
            }):
                _, detected = _build_path_env(None, None)

            self.assertEqual(detected, [str(make_dir), str(gcc_dir)])


class ProjectCompilerDiscoveryTests(unittest.TestCase):
    def test_ads_compiler_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gcc_dir = Path(temp_dir) / "tools" / "Compilers" / "tricore-gcc11" / "bin"
            gcc_dir.mkdir(parents=True)

            actual = find_gcc_cross_compile_prefix(temp_dir)

            self.assertEqual(actual, f"{gcc_dir.as_posix()}/tricore-elf-")

    def test_acs_compiler_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gcc_dir = Path(temp_dir) / "eclipse" / "tricore-gcc11" / "bin"
            gcc_dir.mkdir(parents=True)

            actual = find_gcc_cross_compile_prefix(temp_dir)

            self.assertEqual(actual, f"{gcc_dir.as_posix()}/tricore-elf-")


class ProjectStudioDiscoveryTests(unittest.TestCase):
    def test_ads_acs_and_limited_install_roots_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = [
                root / "AURIX-Studio-1.10.0",
                root / "AURIX-Studio-Limited-1.10.0",
                root / "AURIX-Configuration-Studio-1.0.22" / "eclipse",
                root / "AURIX-Configuration-Studio-Limited-1.0.22" / "eclipse",
            ]
            for studio_dir in expected:
                studio_dir.mkdir(parents=True)

            candidates = discover_studio_candidates(temp_dir)

            for studio_dir in expected:
                self.assertIn(str(studio_dir), candidates)

    def test_limited_launcher_name_variations_are_recognized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            studio_dir = Path(temp_dir)
            (studio_dir / "AURIX-configuration-studio-lc.exe").touch()

            self.assertTrue(is_studio_directory(temp_dir))


class ProjectDependencyDeploymentTests(unittest.TestCase):
    def test_complete_existing_bundle_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            cache = Path(cache_dir)
            workspace = Path(workspace_dir)
            (cache / "Configurations").mkdir()
            (cache / "Configurations" / "Ifx_Cfg.h").write_text("acs", encoding="ascii")
            (workspace / "Libraries" / "iLLD").mkdir(parents=True)
            (workspace / "Configurations").mkdir()
            config = workspace / "Configurations" / "Ifx_Cfg.h"
            config.write_text("example", encoding="ascii")
            (workspace / "Lcf").mkdir()

            details = deploy_template_dependencies(cache_dir, workspace_dir)

            self.assertEqual(config.read_text(encoding="ascii"), "example")
            self.assertEqual(details, [
                "Preserved existing Libraries/ and Configurations/ dependency bundle",
                "Preserved existing Lcf/",
            ])

    def test_partial_existing_bundle_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            workspace = Path(workspace_dir)
            (workspace / "Libraries" / "iLLD").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "missing Configurations/Ifx_Cfg.h"):
                deploy_template_dependencies(cache_dir, workspace_dir)

    def test_missing_linker_scripts_are_deployed_for_existing_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            cache = Path(cache_dir)
            workspace = Path(workspace_dir)
            (cache / "Lcf").mkdir()
            (cache / "Lcf" / "linker.ld").write_text("linker", encoding="ascii")
            (workspace / "Libraries" / "iLLD").mkdir(parents=True)
            (workspace / "Configurations").mkdir()
            (workspace / "Configurations" / "Ifx_Cfg.h").write_text("example", encoding="ascii")

            details = deploy_template_dependencies(cache_dir, workspace_dir)

            self.assertEqual((workspace / "Lcf" / "linker.ld").read_text(encoding="ascii"), "linker")
            self.assertEqual(details, [
                "Preserved existing Libraries/ and Configurations/ dependency bundle",
                "Deployed Lcf/",
            ])

    def test_empty_workspace_receives_complete_template_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as cache_dir, tempfile.TemporaryDirectory() as workspace_dir:
            cache = Path(cache_dir)
            for dir_name in ("Libraries", "Lcf", "Configurations"):
                source_dir = cache / dir_name
                source_dir.mkdir()
                (source_dir / "marker.txt").write_text(dir_name, encoding="ascii")

            details = deploy_template_dependencies(cache_dir, workspace_dir)

            self.assertEqual(details, ["Deployed Libraries/", "Deployed Lcf/", "Deployed Configurations/"])
            for dir_name in ("Libraries", "Lcf", "Configurations"):
                marker = Path(workspace_dir) / dir_name / "marker.txt"
                self.assertEqual(marker.read_text(encoding="ascii"), dir_name)

class FlashProgramDiscoveryTests(unittest.TestCase):
    def test_configured_acs_install_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            flasher = (
                root / "eclipse" / "plugins" / "com.ifx.ads2.flash_2.0.22"
                / "AurixFlasherSoftwareTool_v3.0.18" / "AURIXFlasher.exe"
            )
            lsmcdd = (
                root / "eclipse" / "plugins" / "com.rt.hightec.tcf.agent.launcher_1.0.63"
                / "res" / "lsmcdd.exe"
            )
            flasher.parent.mkdir(parents=True)
            lsmcdd.parent.mkdir(parents=True)
            flasher.touch()
            lsmcdd.touch()

            with patch.dict(os.environ, {
                "AURIX_ADS_STUDIO_PATH": str(root),
                "AURIX_IDE_PATH": str(root),
            }), patch("aurix_mcp_server.tools.flash_program.sys.platform", "win32"):
                preferred_roots = _configured_studio_roots(None)
                actual_flasher = _probe_known_flasher_locations(
                    ["AURIXFlasher.exe", "aurixflasher.exe"], preferred_roots
                )
                actual_lsmcdd = _probe_known_flasher_locations(["lsmcdd.exe"], preferred_roots)

            self.assertEqual(actual_flasher, str(flasher))
            self.assertEqual(actual_lsmcdd, str(lsmcdd))


if __name__ == "__main__":
    unittest.main()
