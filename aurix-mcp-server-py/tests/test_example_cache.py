"""examples_import keeps a local copy of downloaded examples and reuses it without network access."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server import example_cache
from aurix_mcp_server.tooldef import ToolContext
from aurix_mcp_server.tools import examples

FILES = ["Cpu0_Main.c", "Libraries/iLLD/Port/IfxPort.c", "Configurations/Ifx_Cfg.h"]
INDEX = {
    "sourceRoot": "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples",
    "examples": [{"id": "TC4D7_Shell", "title": "Shell", "rootPath": "Shell", "cpuMainFiles": ["Cpu0_Main.c"]}],
}


async def _noop(*_args) -> None:
    pass


class ExampleCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.downloads = 0
        self.files = list(FILES)
        for patcher in (
            patch.object(example_cache, "CACHE_ROOT", self.root / "cache"),
            patch.object(examples, "_load_examples_index", return_value=("unused", INDEX)),
            patch.object(examples, "_load_manifest", side_effect=lambda: {"Shell": self.files}),
            patch.object(examples, "regenerate_makefile_for_workspace", return_value=None),
            patch.dict(os.environ, {example_cache.ENVIRONMENT_VARIABLE: "1"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    async def fake_download(self, owner, repo, branch, remote_dir, local_dir, overwrite, file_list):
        self.downloads += 1
        downloaded, skipped = [], []
        for relative in file_list:
            path = Path(local_dir, *relative.split("/"))
            if path.exists() and not overwrite:
                skipped.append(relative)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"downloaded {relative}", encoding="utf-8")
            downloaded.append(relative)
        return {"downloaded": downloaded, "skipped": skipped, "errors": []}

    async def run_import(self, name: str, **extra):
        with patch.object(examples, "_download_github_directory", side_effect=self.fake_download):
            return await examples._import_run(
                {"id": "TC4D7_Shell", "targetDir": str(self.root / name), **extra}, ToolContext(send_progress=_noop),
            )

    def entries(self) -> list[str]:
        root = example_cache.CACHE_ROOT
        return sorted(path.name for path in root.iterdir()) if root.exists() else []

    async def test_second_import_is_copied_from_the_cache_without_downloading(self) -> None:
        first = await self.run_import("first")
        self.assertFalse(first.is_error, first.content[0].text)
        self.assertEqual(first.structured_content["exampleCache"]["status"], "stored")
        second = await self.run_import("second")
        self.assertFalse(second.is_error, second.content[0].text)
        self.assertEqual(self.downloads, 1)
        self.assertEqual(second.structured_content["exampleCache"]["status"], "hit")
        self.assertEqual(sorted(second.structured_content["downloaded"]), sorted(FILES))
        self.assertIn("copied from the local example cache", second.content[0].text)
        self.assertNotIn("download", second.structured_content["timingsMs"])
        for relative in FILES:
            self.assertEqual(
                (self.root / "second" / relative).read_text(encoding="utf-8"), f"downloaded {relative}",
            )

    async def test_cache_hit_keeps_existing_project_files_unless_overwrite(self) -> None:
        await self.run_import("first")
        target = self.root / "edited"
        target.mkdir()
        (target / "Cpu0_Main.c").write_text("user code", encoding="utf-8")
        result = await self.run_import("edited")
        self.assertEqual(result.structured_content["exampleCache"]["status"], "hit")
        self.assertEqual(result.structured_content["skipped"], ["Cpu0_Main.c"])
        self.assertEqual((target / "Cpu0_Main.c").read_text(encoding="utf-8"), "user code")
        await self.run_import("edited", overwrite=True)
        self.assertEqual((target / "Cpu0_Main.c").read_text(encoding="utf-8"), "downloaded Cpu0_Main.c")
        self.assertEqual(self.downloads, 1)

    async def test_partial_download_is_not_cached(self) -> None:
        # A file kept from the project instead of downloaded must never enter the cache.
        target = self.root / "partial"
        target.mkdir()
        (target / "Cpu0_Main.c").write_text("user code", encoding="utf-8")
        result = await self.run_import("partial")
        self.assertEqual(result.structured_content["exampleCache"]["status"], "not_stored")
        self.assertEqual(self.entries(), [])
        await self.run_import("next")
        self.assertEqual(self.downloads, 2)

    async def test_incomplete_or_stale_entries_are_downloaded_again(self) -> None:
        stored = await self.run_import("first")
        entry = Path(stored.structured_content["exampleCache"]["path"])
        (entry / "Libraries/iLLD/Port/IfxPort.c").unlink()
        await self.run_import("missing-file")
        self.assertEqual(self.downloads, 2)
        marker = entry / example_cache.COMPLETE_MARKER
        marker.write_text(json.dumps({"created": time.time() - example_cache.MAX_AGE_SECONDS - 1}), encoding="utf-8")
        refreshed = await self.run_import("stale")
        self.assertEqual(self.downloads, 3)
        self.assertEqual(refreshed.structured_content["exampleCache"]["status"], "stored")
        self.assertEqual((await self.run_import("fresh")).structured_content["exampleCache"]["status"], "hit")

    async def test_changed_file_list_uses_a_new_entry(self) -> None:
        await self.run_import("first")
        self.files = [*FILES, "README.md"]
        result = await self.run_import("more-files")
        self.assertEqual(self.downloads, 2)
        self.assertTrue((self.root / "more-files" / "README.md").is_file())
        self.assertEqual(result.structured_content["exampleCache"]["status"], "stored")

    async def test_disabled_by_environment(self) -> None:
        with patch.dict(os.environ, {example_cache.ENVIRONMENT_VARIABLE: "0"}):
            await self.run_import("first")
            result = await self.run_import("second")
        self.assertEqual(self.downloads, 2)
        self.assertEqual(result.structured_content["exampleCache"]["status"], "disabled")
        self.assertEqual(self.entries(), [])

    async def test_store_failure_does_not_fail_the_import(self) -> None:
        with patch.object(example_cache.shutil, "copyfile", side_effect=OSError("disk full")):
            result = await self.run_import("first")
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["exampleCache"]["status"], "store_failed")
        self.assertEqual(self.entries(), [])

    def test_unsafe_file_lists_are_not_cached(self) -> None:
        for files in ([], ["../outside.c"], ["/abs.c"], ["C:/x.c"]):
            with self.subTest(files=files):
                self.assertIsNone(example_cache.entry_key("id", "source", files))

    def test_prune_keeps_the_most_recently_used_entries(self) -> None:
        source = self.root / "source"
        source.mkdir()
        (source / "a.c").write_text("a", encoding="utf-8")
        for index in range(example_cache.MAX_ENTRIES + 2):
            report = example_cache.store(f"entry{index:02d}", ["a.c"], str(source))
            os.utime(Path(report["path"]) / example_cache.COMPLETE_MARKER, (1000 + index, 1000 + index))
        example_cache.prune()
        remaining = self.entries()
        self.assertEqual(len(remaining), example_cache.MAX_ENTRIES)
        self.assertNotIn("entry00", remaining)
        self.assertNotIn("entry01", remaining)


if __name__ == "__main__":
    unittest.main()
