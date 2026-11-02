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
                        timed_out: bool = False, log_failure: bool = False, extra: dict | None = None):
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
        process.pid = 4242
        progress = AsyncMock()
        with tempfile.TemporaryDirectory() as workspace:
            with patch.object(build_run, "_build_path_env", return_value=({}, [])), \
                    patch.object(build_run, "kill_process_tree") as kill_tree, \
                    patch.object(build_run.asyncio, "create_subprocess_shell", return_value=process):
                if log_failure:
                    with patch.object(build_run.tempfile, "NamedTemporaryFile", side_effect=OSError("disk full")):
                        result = await build_run._run({"workspace": workspace, **(extra or {})}, ToolContext(send_progress=progress))
                else:
                    result = await build_run._run({"workspace": workspace, **(extra or {})}, ToolContext(send_progress=progress))
        for path in result.structured_content["logFiles"].values():
            self.addCleanup(Path(path).unlink, missing_ok=True)
        process.kill_tree = kill_tree
        return result, progress, process

    async def test_short_agent_timeout_is_raised_to_full_build_minimum(self) -> None:
        result, _, _ = await self.run_build(b"Build complete: build/TC375.elf\n", b"", extra={"timeoutMs": 120000})
        self.assertEqual(result.structured_content["timeoutMs"], build_run.MIN_BUILD_TIMEOUT_MS)

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
        # Killing only the shell would leave make and the compilers running on Windows.
        process.kill_tree.assert_called_once_with(4242)
        process.kill.assert_called_once()

    async def test_log_storage_failure_does_not_change_build_result(self) -> None:
        result, _, _ = await self.run_build(b"build complete\n", b"", log_failure=True)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["logFiles"], {})
        self.assertEqual(set(result.structured_content["logFileErrors"]), {"stdout", "stderr"})
        self.assertIn("disk full", result.content[0].text)


class BuildRunCancellationTests(unittest.IsolatedAsyncioTestCase):
    """A silent make must keep the client's request alive; a cancelled request must stop the build."""

    def silent_process(self, finish: asyncio.Event) -> unittest.mock.Mock:
        process = unittest.mock.Mock()
        process.pid = 4242
        process.returncode = None
        process.stdout = asyncio.StreamReader()
        process.stderr = asyncio.StreamReader()

        async def wait():
            await finish.wait()
            process.returncode = 0
            for stream in (process.stdout, process.stderr):
                if not stream.at_eof():
                    stream.feed_eof()
            return 0

        process.wait = wait
        return process

    def start(self, process, progress, workspace: str, **patches) -> asyncio.Task:
        stack = [
            patch.object(build_run, "_build_path_env", return_value=({}, [])),
            patch.object(build_run.asyncio, "create_subprocess_shell", AsyncMock(return_value=process)),
            *(patch.object(build_run, name, value) for name, value in patches.items()),
        ]
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)
        return asyncio.ensure_future(build_run._run({"workspace": workspace}, ToolContext(send_progress=progress)))

    async def test_silent_make_sends_heartbeats_that_are_not_build_output(self) -> None:
        finish = asyncio.Event()
        process = self.silent_process(finish)
        progress = AsyncMock()
        with tempfile.TemporaryDirectory() as workspace:
            task = self.start(process, progress, workspace, HEARTBEAT_SECONDS=0.05)
            for _ in range(200):
                if any("still running" in call.args[0] for call in progress.await_args_list):
                    break
                await asyncio.sleep(0.01)
            process.stdout.feed_data(b"Build complete: build/TC4D7.elf\n")
            finish.set()
            result = await task
        self.assertFalse(result.is_error, result.content[0].text)
        heartbeats = [call.args[0] for call in progress.await_args_list if "still running" in call.args[0]]
        self.assertTrue(heartbeats)
        self.assertNotIn("still running", Path(result.structured_content["logFiles"]["stdout"]).read_text())
        self.assertNotIn("still running", result.structured_content["stdout"])
        for path in result.structured_content["logFiles"].values():
            Path(path).unlink(missing_ok=True)

    async def test_cancelled_request_stops_the_whole_build(self) -> None:
        finish = asyncio.Event()
        process = self.silent_process(finish)
        kill_tree = unittest.mock.Mock()
        with tempfile.TemporaryDirectory() as workspace:
            task = self.start(process, AsyncMock(), workspace, kill_process_tree=kill_tree)
            for _ in range(200):
                if build_run.asyncio.create_subprocess_shell.await_count:
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        # Left running, make would compete with the retried build_run for the same objects.
        kill_tree.assert_called_once_with(4242)
        process.kill.assert_called_once()

    async def test_cancelled_request_stops_a_cache_build(self) -> None:
        import threading

        started = threading.Event()
        stopped = threading.Event()

        def prepare(cwd, env, timeout_s, cancel):
            started.set()
            if cancel.wait(timeout=10):
                stopped.set()
            return {"status": "failed", "reason": "cache build cancelled"}

        finish = asyncio.Event()
        process = self.silent_process(finish)
        with tempfile.TemporaryDirectory() as workspace, \
                patch.object(build_run.build_cache, "prepare", side_effect=prepare):
            task = self.start(process, AsyncMock(), workspace)
            await asyncio.to_thread(started.wait, 5)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(await asyncio.to_thread(stopped.wait, 5))
        build_run.asyncio.create_subprocess_shell.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()