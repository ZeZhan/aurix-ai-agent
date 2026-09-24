"""Regression tests for source text in both MCP result representations."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.server_fastmcp import examples_read_source
from aurix_mcp_server.tools import examples


class ExamplesReadSourceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.example_root = self.root / "Blinky"
        self.example_root.mkdir()
        self.index = {
            "sourceRoot": str(self.root),
            "examples": [{
                "id": "TC375_Blinky",
                "title": "TC375 Blinky",
                "rootPath": "Blinky",
                "cpuMainFiles": ["Cpu0_Main.c"],
            }],
        }
        loader = patch.object(examples, "_load_examples_index", return_value=("unused", self.index))
        loader.start()
        self.addCleanup(loader.stop)

    async def test_default_file_preserves_source_in_both_mcp_fields(self) -> None:
        source = '#include "Ifx_Types.h"\nvoid core0_main(void) { }\n'
        (self.example_root / "Cpu0_Main.c").write_text(source, encoding="utf-8")

        result = await examples_read_source(id="TC375_Blinky")
        wire = result.model_dump(mode="json", by_alias=True)

        self.assertFalse(wire["isError"])
        self.assertEqual(wire["content"][0]["text"], f"=== Cpu0_Main.c ===\n{source}")
        structured = wire["structuredContent"]
        self.assertEqual(structured["exampleId"], "TC375_Blinky")
        self.assertEqual(structured["filesRead"], 1)
        self.assertEqual(structured["totalFiles"], 1)
        self.assertEqual(structured["totalChars"], len(source))
        self.assertEqual(structured["files"], [{
            "file": "Cpu0_Main.c", "chars": len(source), "content": source,
        }])

    async def test_multiple_files_include_empty_source_and_keep_requested_order(self) -> None:
        contents = {"Empty.h": "", "Cpu0_Main.c": "/* \u6e90\u7801 */\nint value = 1;\n"}
        for filename, source in contents.items():
            (self.example_root / filename).write_text(source, encoding="utf-8")

        result = await examples_read_source(id="TC375_Blinky", files=list(contents))
        structured = result.structuredContent

        self.assertEqual(structured["filesRead"], 2)
        self.assertEqual(structured["totalFiles"], 2)
        self.assertEqual(structured["totalChars"], sum(map(len, contents.values())))
        self.assertEqual(structured["files"], [
            {"file": filename, "chars": len(source), "content": source}
            for filename, source in contents.items()
        ])
        self.assertEqual(result.content[0].text, "\n\n".join(
            f"=== {filename} ===\n{source}" for filename, source in contents.items()
        ))

    async def test_partial_and_total_failure_preserve_errors_and_counts(self) -> None:
        source = "void core0_main(void) {}\n"
        (self.example_root / "Cpu0_Main.c").write_text(source, encoding="utf-8")
        for files in (["Missing.h", "Cpu0_Main.c"], ["Missing.h"]):
            with self.subTest(files=files):
                result = await examples_read_source(id="TC375_Blinky", files=files)
                structured = result.structuredContent
                self.assertEqual(structured["files"][0], {
                    "file": "Missing.h", "chars": 0, "content": "", "error": "File not found",
                })
                self.assertEqual(structured["totalFiles"], len(files))
                self.assertEqual(structured["filesRead"], len(files) - 1)
                self.assertEqual(structured["totalChars"], len(source) if len(files) == 2 else 0)
                self.assertIn("ERROR: File not found", result.content[0].text)
                if len(files) == 2:
                    self.assertEqual(structured["files"][1]["content"], source)

    async def test_downloaded_source_and_download_error_reach_structured_result(self) -> None:
        self.index["sourceRoot"] = "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples"
        source = "void core0_main(void) {}\n"
        with patch.object(examples, "_fetch_github_raw", side_effect=[source, OSError("Download failed")]) as fetch:
            result = await examples_read_source(id="TC375_Blinky", files=["Cpu0_Main.c", "Missing.h"])

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(result.structuredContent["files"], [
            {"file": "Cpu0_Main.c", "chars": len(source), "content": source},
            {"file": "Missing.h", "chars": 0, "content": "", "error": "Download failed"},
        ])
        self.assertEqual(result.structuredContent["filesRead"], 1)
        self.assertIn(source, result.content[0].text)


if __name__ == "__main__":
    unittest.main()