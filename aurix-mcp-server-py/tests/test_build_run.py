"""Regression tests for bounded build results and complete diagnostic logs."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.tooldef import ToolContext
from aurix_mcp_server.tools import build_run


class BuildLogTests(unittest.TestCase):
    def test_chunk_boundaries_crlf_and_unterminated_diagnostics(self) -> None:
        log = build_run.BuildLog()
        log.feed("main.c:3: er")
        log.feed("ror: missing symbol\r\nmain.c:4: warn")
        log.feed("ing: unused variable")
        log.close()
        log.close()
        self.assertEqual(log.error_count, 1)
        self.assertEqual(log.warning_count, 1)
        self.assertEqual(log.line_count, 2)
        self.assertEqual(log.errors, ["main.c:3: error: missing symbol"])
        self.assertEqual(log.warnings, ["main.c:4: warning: unused variable"])

    def test_diagnostics_survive_large_output_and_are_bounded(self) -> None:
        log = build_run.BuildLog()
        log.feed("early.c:1: error: first failure\n")
        log.feed("Compiling Libraries/Error.c\n" * 500)
        log.feed("main.c:2: warning: unused variable\n" * 300)
        log.feed("ld: undefined reference to `missing`\nmake: *** [all] Error 1\n")
        log.close()
        self.assertEqual(log.error_count, 3)
        self.assertEqual(log.warning_count, 300)
        self.assertIn("first failure", log.errors[0])
        self.assertIn("undefined reference", log.errors[1])
        self.assertLessEqual(len(log.warnings), build_run.MAX_WARNING_LINES)
        self.assertTrue(log.truncated)

    def test_long_lines_and_pending_data_are_bounded(self) -> None:
        log = build_run.BuildLog()
        for _ in range(100):
            log.feed("x" * 4096)
        self.assertLessEqual(len(log._pending), build_run.MAX_LINE_CHARS)
        log.feed("\n")
        log.feed(("main.c:1: error: " + "x" * 5000 + "\n") * 250)
        log.close()
        self.assertTrue(log.truncated)
        self.assertEqual(log.error_count, 250)
        self.assertLessEqual(len(log.tail_text()), build_run.MAX_TAIL_CHARS)
        self.assertLessEqual(sum(map(len, log.errors)), build_run.MAX_ERROR_CHARS)


class BuildRunTests(unittest.IsolatedAsyncioTestCase):
    async def run_build(self, stdout: bytes, stderr: bytes, exit_code: int = 0,
                        timed_out: bool = False, log_failure: bool = False):
        process = AsyncMock()
        process.returncode = exit_code
        process.stdout = asyncio.StreamReader()
        process.stderr = asyncio.StreamReader()
        process.stdout.feed_data(stdout)
        process.stdout.feed_eof()
        process.stderr.feed_data(stderr)
        process.stderr.feed_eof()
        process.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), None] if timed_out else [None])
        process.kill = unittest.mock.Mock()
        progress = AsyncMock()
        with tempfile.TemporaryDirectory() as workspace:
            with patch.object(build_run, "_build_path_env", return_value=({}, [])), \
                    patch.object(build_run.asyncio, "create_subprocess_shell", return_value=process):
                if log_failure:
                    with patch.object(build_run.tempfile, "NamedTemporaryFile", side_effect=OSError("disk full")):
                        result = await build_run._run({"workspace": workspace}, ToolContext(send_progress=progress))
                else:
                    result = await build_run._run({"workspace": workspace}, ToolContext(send_progress=progress))
        for path in result.structured_content["logFiles"].values():
            self.addCleanup(Path(path).unlink, missing_ok=True)
        return result, progress, process

    async def test_success_keeps_warning_and_artifact_summary_with_complete_logs(self) -> None:
        stdout = ("Compiling source.c " + "-Iinclude " * 300 + "\n") * 500
        stdout += "Build complete: build/TC4D7.elf\ntext data bss\n123 0 456\n"
        stderr = "main.c:1: warning: implicit declaration of function 'blinkLED'\n"
        result, progress, _ = await self.run_build(stdout.encode(), stderr.encode())
        report = result.structured_content
        self.assertFalse(result.is_error)
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(report["warningCount"], 1)
        self.assertTrue(report["logTruncated"])
        self.assertIn("blinkLED", result.content[0].text)
        self.assertIn("build/TC4D7.elf", result.content[0].text)
        self.assertIn("123 0 456", report["stdout"])
        self.assertLess(len(json.dumps(report)), 10000)
        self.assertEqual(Path(report["logFiles"]["stdout"]).read_bytes(), stdout.encode())
        self.assertEqual(Path(report["logFiles"]["stderr"]).read_bytes(), stderr.encode())
        streamed = "".join(call.args[0] for call in progress.await_args_list if call.args[1] == "stdout")
        self.assertEqual(streamed, stdout)

    async def test_failure_keeps_early_errors_and_both_stream_tails(self) -> None:
        stdout = b"custom build failure details\n"
        stderr = b"main.c:1: error: missing declaration\n  offending_expression();\n" + b"compile\n" * 200
        stderr += b"ld: undefined reference to `missing`\n"
        result, _, _ = await self.run_build(stdout, stderr, exit_code=2)
        report = result.structured_content
        self.assertTrue(result.is_error)
        self.assertEqual(report["errorCount"], 2)
        self.assertIn("missing declaration", result.content[0].text)
        self.assertIn("custom build failure details", result.content[0].text)
        self.assertIn("undefined reference", result.content[0].text)
        self.assertEqual(Path(report["logFiles"]["stderr"]).read_bytes(), stderr)

    async def test_timeout_remains_failure_and_retains_output(self) -> None:
        result, _, process = await self.run_build(b"still compiling\n", b"", exit_code=-1, timed_out=True)
        self.assertTrue(result.is_error)
        self.assertTrue(result.structured_content["timedOut"])
        self.assertIn("still compiling", result.content[0].text)
        process.kill.assert_called_once()

    async def test_log_storage_failure_does_not_change_build_result(self) -> None:
        result, _, _ = await self.run_build(b"build complete\n", b"", log_failure=True)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["logFiles"], {})
        self.assertEqual(set(result.structured_content["logFileErrors"]), {"stdout", "stderr"})
        self.assertIn("disk full", result.content[0].text)


if __name__ == "__main__":
    unittest.main()