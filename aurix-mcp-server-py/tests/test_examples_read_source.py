"""Regression tests for example source output and import readiness."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from aurix_mcp_server.server_fastmcp import examples_import, examples_read_source
from aurix_mcp_server.tooldef import ToolContext
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

    async def test_default_multicore_budget_keeps_cpu0_first_and_marks_truncation(self) -> None:
        filenames = [f"Cpu{core}_Main.c" for core in reversed(range(6))]
        self.index["examples"][0]["cpuMainFiles"] = filenames
        source = "x" * (examples.MAX_SOURCE_CHARS_PER_FILE + 1)
        for filename in filenames:
            (self.example_root / filename).write_text(source, encoding="utf-8")

        result = await examples_read_source(id="TC375_Blinky")
        structured = result.structuredContent

        self.assertEqual(structured["filesRead"], 6)
        self.assertEqual(structured["totalFiles"], 6)
        self.assertEqual(structured["totalChars"], examples.MAX_SOURCE_CHARS_TOTAL)
        self.assertEqual([item["file"] for item in structured["files"]], list(reversed(filenames)))
        self.assertEqual(structured["files"][0]["chars"], examples.MAX_SOURCE_CHARS_PER_FILE)
        for item in structured["files"]:
            self.assertTrue(item["truncated"])
            self.assertEqual(item["originalChars"], len(source))
        self.assertIn("request this file explicitly", result.content[0].text)

    async def test_explicit_large_files_bypass_default_budget_and_keep_order(self) -> None:
        source = "x" * (examples.MAX_SOURCE_CHARS_TOTAL + 1)
        (self.example_root / "Cpu0_Main.c").write_text(source, encoding="utf-8")
        (self.example_root / "Other.c").write_text("int value;", encoding="utf-8")

        default = await examples_read_source(id="TC375_Blinky")
        self.assertTrue(default.structuredContent["files"][0]["truncated"])
        for files in (["Cpu0_Main.c"], ["Other.c", "Cpu0_Main.c"]):
            with self.subTest(files=files):
                result = await examples_read_source(id="TC375_Blinky", files=files)
                returned = result.structuredContent["files"]
                self.assertEqual([item["file"] for item in returned], files)
                self.assertEqual(returned[-1]["content"], source)
                self.assertNotIn("truncated", returned[-1])
                self.assertIn(source, result.content[0].text)

    def test_readiness_hint_requires_an_actual_makefile(self) -> None:
        for message in (None, "Generator returned a status"):
            note = examples._build_readiness_note(str(self.root), message)
            self.assertIn("No Makefile was generated", note)
            self.assertNotIn("try build.run", note)
        (self.root / "Makefile").write_text("all:\n", encoding="utf-8")
        for message in (None, "Regenerated Makefile"):
            note = examples._build_readiness_note(str(self.root), message)
            self.assertIn("Makefile: present", note)
            self.assertNotIn("do NOT", note)

    async def test_import_readiness_for_local_zip_and_github_sources(self) -> None:
        (self.example_root / "Cpu0_Main.c").write_text("int main(void) {}", encoding="utf-8")
        archive = self.root / "examples.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.write(self.example_root / "Cpu0_Main.c", "code_examples/Blinky/Cpu0_Main.c")
        roots = {
            "local": str(self.root),
            "zip": f"{archive}::code_examples",
            "github": "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples",
        }
        for kind, source_root in roots.items():
            for generate in (False, True):
                with self.subTest(kind=kind, generate=generate):
                    self.index["sourceRoot"] = source_root
                    target = self.root / f"target-{kind}-{generate}"

                    def regenerate(workspace: str):
                        if generate:
                            (Path(workspace) / "Makefile").write_text("all:\n", encoding="utf-8")
                            return "Regenerated Makefile"
                        return None

                    with patch.object(examples, "regenerate_makefile_for_workspace", side_effect=regenerate), \
                            patch.object(examples, "_load_manifest", return_value={}), \
                            patch.object(examples, "_download_github_directory", new=AsyncMock(return_value={
                                "downloaded": ["Cpu0_Main.c"], "skipped": [], "errors": [],
                            })):
                        result = await examples_import(id="TC375_Blinky", targetDir=str(target))
                    self.assertFalse(result.isError, result.content[0].text)
                    self.assertEqual(result.structuredContent["hasMakefile"], generate)
                    expected = "Makefile: present" if generate else "No Makefile was generated"
                    self.assertIn(expected, result.content[0].text)
                    stage = {"local": "copy", "zip": "extract", "github": "download"}[kind]
                    self.assertTrue({"index", stage, "makefile"} <= result.structuredContent["timingsMs"].keys())
                    self.assertGreaterEqual(result.structuredContent["durationMs"], 0)
                    self.assertIn("Timing: total=", result.content[0].text)
                    self.assertIn("Diagnostics:", result.content[0].text)
                    self.assertEqual(
                        result.structuredContent["diagnostics"]["stages"].keys(),
                        result.structuredContent["timingsMs"].keys(),
                    )
                    self.assertNotIn("download", result.structuredContent["diagnostics"])

    async def test_download_diagnostics_preserve_success_errors_and_skips(self) -> None:
        target = self.root / "download"
        target.mkdir()
        (target / "Existing.c").write_bytes(b"keep")

        def respond(request):
            if request.url.path.endswith("Missing.c"):
                return httpx.Response(404, content=b"missing")
            if request.url.path.endswith("Timeout.c"):
                raise httpx.ReadTimeout("timed out", request=request)
            return httpx.Response(200, content=b"source")

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(examples.httpx, "AsyncClient", return_value=client):
            result = await examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(target), False,
                ["Cpu0_Main.c", "Existing.c", "Missing.c", "Timeout.c"],
            )
        self.assertEqual(result["downloaded"], ["Cpu0_Main.c"])
        self.assertEqual(result["skipped"], ["Existing.c"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertEqual((target / "Existing.c").read_bytes(), b"keep")
        self.assertEqual((target / "Cpu0_Main.c").read_bytes(), b"source")
        diagnostics = result["downloadDiagnostics"]
        self.assertEqual(diagnostics["httpRequestCount"], 3)
        self.assertEqual(diagnostics["httpErrorCount"], 2)
        self.assertEqual(diagnostics["httpStatusCounts"], {"200": 1, "404": 1})
        self.assertEqual(diagnostics["httpResponseBytes"], 13)
        self.assertEqual(diagnostics["filesWritten"], 1)
        self.assertGreaterEqual(diagnostics["httpRequestTotalMs"], diagnostics["httpRequestMaxMs"])
        self.assertGreaterEqual(diagnostics["writeMs"], diagnostics["writeMaxMs"])
        self.assertTrue(client.is_closed)

    async def test_download_timing_separates_client_request_and_disk(self) -> None:
        clock = [0.0]

        def respond(request):
            clock[0] += 0.1
            return httpx.Response(200, content=b"source")

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

        def create_client(**kwargs):
            clock[0] += 0.2
            return client

        @contextmanager
        def write_file(path, mode):
            clock[0] += 0.05
            with open(path, mode) as handle:
                yield handle

        with patch.object(examples, "time", Mock(monotonic=lambda: clock[0])), \
                patch.object(examples.httpx, "AsyncClient", side_effect=create_client), \
                patch.object(examples, "open", write_file, create=True):
            result = await examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(self.root / "timed"), False, ["Cpu0_Main.c"],
            )
        diagnostics = result["downloadDiagnostics"]
        self.assertEqual(diagnostics["clientInitMs"], 200)
        self.assertEqual(diagnostics["httpRequestTotalMs"], 100)
        self.assertEqual(diagnostics["writeMs"], 50)
        self.assertEqual(diagnostics["mkdirMs"], 0)

    async def test_slow_file_write_does_not_block_event_loop(self) -> None:
        loop = asyncio.get_running_loop()
        write_started = asyncio.Event()
        release_write = threading.Event()
        worker_ids = []
        main_thread = threading.get_ident()

        @contextmanager
        def slow_open(path, mode):
            worker_ids.append(threading.get_ident())
            loop.call_soon_threadsafe(write_started.set)
            if not release_write.wait(timeout=3):
                raise RuntimeError("Event loop did not release the write")
            with open(path, mode) as handle:
                yield handle

        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"source")))
        with patch.object(examples.httpx, "AsyncClient", return_value=client), \
                patch.object(examples, "open", slow_open, create=True):
            task = asyncio.create_task(examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(self.root / "threaded"), False, ["Cpu0_Main.c"],
            ))
            try:
                await asyncio.wait_for(write_started.wait(), timeout=3)
                self.assertFalse(task.done())
                release_write.set()
                result = await asyncio.wait_for(task, timeout=3)
            finally:
                release_write.set()
                await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(result["errors"])
        self.assertEqual(result["downloadDiagnostics"]["filesWritten"], 1)
        self.assertNotEqual(worker_ids[0], main_thread)

    async def test_file_pool_and_in_flight_files_are_bounded(self) -> None:
        loop = asyncio.get_running_loop()
        workers_ready = asyncio.Event()
        release_write = threading.Event()
        lock = threading.Lock()
        active = 0
        peak = 0
        requests = []
        thread_ids = set()

        def respond(request):
            requests.append(request.url.path)
            return httpx.Response(200, content=b"source")

        @contextmanager
        def slow_open(path, mode):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                thread_ids.add(threading.get_ident())
                if active == examples.DOWNLOAD_FILE_WORKERS:
                    loop.call_soon_threadsafe(workers_ready.set)
            try:
                if not release_write.wait(timeout=5):
                    raise RuntimeError("Worker limit check did not release writers")
                with open(path, mode) as handle:
                    yield handle
            finally:
                with lock:
                    active -= 1

        files = [f"Source{number}.c" for number in range(24)]
        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch.object(examples.httpx, "AsyncClient", return_value=client), \
                patch.object(examples, "open", slow_open, create=True):
            task = asyncio.create_task(examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(self.root / "bounded"), False, files,
            ))
            try:
                await asyncio.wait_for(workers_ready.wait(), timeout=5)
                self.assertLessEqual(len(requests), examples.DOWNLOAD_CONCURRENCY)
                self.assertEqual(peak, examples.DOWNLOAD_FILE_WORKERS)
                release_write.set()
                result = await asyncio.wait_for(task, timeout=5)
            finally:
                release_write.set()
                await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result["downloaded"], files)
        self.assertFalse(result["errors"])
        self.assertEqual(result["downloadDiagnostics"]["filesWritten"], len(files))
        self.assertLessEqual(len(thread_ids), examples.DOWNLOAD_FILE_WORKERS)
        self.assertEqual(active, 0)

    async def test_cancellation_waits_for_active_file_workers_without_blocking_loop(self) -> None:
        loop = asyncio.get_running_loop()
        write_started = asyncio.Event()
        shutdown_started = asyncio.Event()
        release_write = threading.Event()
        write_finished = threading.Event()
        worker_ids = set()
        main_thread = threading.get_ident()
        shutdown_threads = []

        class TrackedExecutor(ThreadPoolExecutor):
            def shutdown(self, *args, **kwargs):
                shutdown_threads.append(threading.get_ident())
                loop.call_soon_threadsafe(shutdown_started.set)
                return super().shutdown(*args, **kwargs)

        @contextmanager
        def slow_open(path, mode):
            worker_ids.add(threading.get_ident())
            loop.call_soon_threadsafe(write_started.set)
            if not release_write.wait(timeout=5):
                raise RuntimeError("Cancellation cleanup blocked the event loop")
            try:
                with open(path, mode) as handle:
                    yield handle
            finally:
                write_finished.set()

        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"source")))
        with patch.object(examples.httpx, "AsyncClient", return_value=client), \
                patch.object(examples, "ThreadPoolExecutor", TrackedExecutor), \
                patch.object(examples, "open", slow_open, create=True):
            task = asyncio.create_task(examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(self.root / "cancel"), False, ["Cpu0_Main.c"],
            ))
            try:
                await asyncio.wait_for(write_started.wait(), timeout=5)
                task.cancel()
                await asyncio.wait_for(shutdown_started.wait(), timeout=5)
                self.assertFalse(task.done())
                self.assertFalse(write_finished.is_set())
                task.cancel()
                release_write.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
            finally:
                release_write.set()
                await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(write_finished.is_set())
        self.assertTrue(client.is_closed)
        self.assertNotIn(main_thread, shutdown_threads)
        self.assertFalse(worker_ids & {thread.ident for thread in threading.enumerate()})

    async def test_file_errors_preserve_other_downloads(self) -> None:
        real_makedirs = examples.os.makedirs

        def create_directory(path, **kwargs):
            if Path(path).name == "bad-directory":
                raise PermissionError("Directory denied")
            return real_makedirs(path, **kwargs)

        def open_file(path, mode):
            if Path(path).name == "bad-write.c":
                raise PermissionError("Write denied")
            return open(path, mode)

        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"source")))
        with patch.object(examples.httpx, "AsyncClient", return_value=client), \
                patch.object(examples.os, "makedirs", side_effect=create_directory), \
                patch.object(examples, "open", open_file, create=True):
            result = await examples._download_raw_files(
                "owner", "repo", "revision", "Blinky", str(self.root / "file-errors"), False,
                ["bad-directory/Source.c", "bad-write.c", "Good.c"],
            )
        self.assertEqual(result["downloaded"], ["Good.c"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertIn("Directory denied", result["errors"][0])
        self.assertIn("Write denied", result["errors"][1])
        self.assertEqual(result["downloadDiagnostics"]["httpRequestCount"], 2)
        self.assertEqual(result["downloadDiagnostics"]["httpErrorCount"], 0)
        self.assertEqual(result["downloadDiagnostics"]["filesWritten"], 1)

    async def test_threaded_overwrite_and_all_skipped_metrics(self) -> None:
        target = self.root / "overwrite"
        target.mkdir()
        source = target / "Cpu0_Main.c"
        source.write_bytes(b"keep")
        for overwrite in (False, True):
            client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"replace")))
            with patch.object(examples.httpx, "AsyncClient", return_value=client):
                result = await examples._download_raw_files(
                    "owner", "repo", "revision", "Blinky", str(target), overwrite, [source.name],
                )
            self.assertEqual(source.read_bytes(), b"replace" if overwrite else b"keep")
            self.assertEqual(result["downloadDiagnostics"]["httpRequestCount"], int(overwrite))
            self.assertEqual(result["downloadDiagnostics"]["filesWritten"], int(overwrite))
            self.assertEqual(result["skipped"], [] if overwrite else [source.name])

    async def test_import_forwards_progress_to_mcp_context(self) -> None:
        self.index["sourceRoot"] = "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples"
        context = Mock(report_progress=AsyncMock(), info=AsyncMock(), warning=AsyncMock())
        with patch.object(examples, "regenerate_makefile_for_workspace", return_value=None), \
                patch.object(examples, "_load_manifest", return_value={}), \
                patch.object(examples, "_download_github_directory", new=AsyncMock(return_value={
                    "downloaded": ["Cpu0_Main.c"], "skipped": [], "errors": [],
                })):
            result = await examples_import(id="TC375_Blinky", targetDir=str(self.root / "progress"), ctx=context)
        self.assertFalse(result.isError)
        self.assertTrue(context.report_progress.await_count)
        messages = [call.args[2] for call in context.report_progress.await_args_list]
        self.assertIn("examples.import: index started", messages)
        self.assertIn("examples.import: download started", messages)
        self.assertIn("examples.import: makefile started", messages)
        self.assertTrue(any("makefile completed" in message for message in messages))
        self.assertLess(messages.index("examples.import: download started"), messages.index("examples.import: makefile started"))
        self.assertTrue(context.info.await_count)

    async def test_slow_makefile_sends_heartbeat_before_work_finishes(self) -> None:
        (self.example_root / "Cpu0_Main.c").write_text("int value;", encoding="utf-8")
        heartbeat = threading.Event()

        def regenerate(workspace: str):
            if not heartbeat.wait(timeout=3):
                raise RuntimeError("Makefile processing blocked progress notifications")
            return None

        async def on_progress(progress, total, message):
            if "makefile still running" in message:
                heartbeat.set()

        context = Mock(report_progress=AsyncMock(side_effect=on_progress), info=AsyncMock(), warning=AsyncMock())
        with patch.object(examples, "regenerate_makefile_for_workspace", side_effect=regenerate), \
                patch.object(examples, "IMPORT_PROGRESS_INTERVAL_SECONDS", 0.01):
            result = await examples_import(id="TC375_Blinky", targetDir=str(self.root / "slow"), ctx=context)
        self.assertFalse(result.isError)
        self.assertTrue(heartbeat.is_set())
        messages = [call.args[2] for call in context.report_progress.await_args_list]
        self.assertTrue(any("makefile still running" in message for message in messages))
        self.assertIn("makefile", result.structuredContent["timingsMs"])

    async def test_stage_notification_failure_does_not_abort_work(self) -> None:
        progress = AsyncMock(side_effect=RuntimeError("Client stopped accepting notifications"))
        operation = AsyncMock(return_value="completed")
        timings = {}
        result = await examples._run_import_stage("download", operation(), ToolContext(send_progress=progress), timings)
        self.assertEqual(result, "completed")
        self.assertIn("download", timings)
        operation.assert_awaited_once()

    async def test_failed_stage_reports_failure_and_keeps_exception(self) -> None:
        progress = AsyncMock()
        operation = AsyncMock(side_effect=ValueError("Cannot generate Makefile"))
        timings = {}
        with self.assertRaisesRegex(ValueError, "Cannot generate Makefile"):
            await examples._run_import_stage("makefile", operation(), ToolContext(send_progress=progress), timings)
        self.assertIn("makefile", timings)
        self.assertTrue(any("makefile failed" in call.args[0] for call in progress.await_args_list))
        self.assertFalse(any("makefile completed" in call.args[0] for call in progress.await_args_list))

    async def test_cancelled_download_stage_does_not_leave_background_task(self) -> None:
        started = asyncio.Event()
        finished = asyncio.Event()
        never_complete = asyncio.Event()

        async def download():
            started.set()
            try:
                await never_complete.wait()
            finally:
                finished.set()

        loop = Mock(time=asyncio.get_running_loop().time)
        diagnostics = {}
        with patch.object(examples.asyncio, "get_running_loop", return_value=loop):
            task = asyncio.create_task(examples._run_import_stage(
                "download", download(), ToolContext(send_progress=AsyncMock()), {}, diagnostics,
            ))
            await asyncio.wait_for(started.wait(), timeout=3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(finished.is_set())
        loop.call_at.return_value.cancel.assert_called_once()
        self.assertIn("download", diagnostics)

    async def test_progress_timing_includes_completion_notification(self) -> None:
        clock = [0.0]

        async def send_progress(message, stream):
            clock[0] += 0.2

        diagnostics = {}
        with patch.object(examples, "time", Mock(monotonic=lambda: clock[0])):
            result = await examples._run_import_stage(
                "download", AsyncMock(return_value="done")(),
                ToolContext(send_progress=send_progress), {}, diagnostics,
            )
        self.assertEqual(result, "done")
        self.assertEqual(diagnostics["download"]["progressSendCount"], 2)
        self.assertEqual(diagnostics["download"]["progressSendTotalMs"], 400)
        self.assertEqual(diagnostics["download"]["progressSendMaxMs"], 200)

    async def test_loop_lag_captures_unserviced_timer_and_cleans_up(self) -> None:
        clock = [0.0]
        loop = Mock(time=lambda: clock[0])
        diagnostics = {}

        async def operation():
            clock[0] = 1.0
            return "done"

        with patch.object(examples.asyncio, "get_running_loop", return_value=loop):
            await examples._run_import_stage(
                "download", operation(), ToolContext(send_progress=AsyncMock()), {}, diagnostics,
            )
        self.assertEqual(diagnostics["download"]["eventLoopLagMaxMs"], 750)
        self.assertEqual(diagnostics["download"]["eventLoopSampleCount"], 1)
        loop.call_at.return_value.cancel.assert_called_once()

    async def test_http_diagnostics_reach_result_and_progress_on_partial_failure(self) -> None:
        self.index["sourceRoot"] = "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples"
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
            404 if request.url.path.endswith("Missing.c") else 200, content=b"source",
        )))
        context = Mock(report_progress=AsyncMock(), info=AsyncMock(), warning=AsyncMock())
        with patch.object(examples, "_load_manifest", return_value={"Blinky": ["Cpu0_Main.c", "Missing.c"]}), \
                patch.object(examples.httpx, "AsyncClient", return_value=client):
            result = await examples_import(id="TC375_Blinky", targetDir=str(self.root / "partial"), ctx=context)
        self.assertTrue(result.isError)
        diagnostics = result.structuredContent["diagnostics"]
        self.assertEqual(diagnostics["download"]["httpRequestCount"], 2)
        self.assertEqual(diagnostics["download"]["filesWritten"], 1)
        self.assertNotIn("makefile", diagnostics["stages"])
        self.assertIn("httpRequests=2", result.content[0].text)
        self.assertIn("Diagnostic times overlap", result.content[0].text)
        messages = [call.args[2] for call in context.report_progress.await_args_list]
        self.assertTrue(any("downloadDiagnostics=" in message for message in messages))

    async def test_failed_import_never_reports_ready_or_regenerates(self) -> None:
        self.index["sourceRoot"] = "https://github.com/Infineon/AURIX_code_examples/tree/master/code_examples"
        with patch.object(examples, "regenerate_makefile_for_workspace") as regenerate, \
                patch.object(examples, "_load_manifest", return_value={}), \
                patch.object(examples, "_download_github_directory", new=AsyncMock(return_value={
                    "downloaded": [], "skipped": [], "errors": ["connection failed"],
                })):
            result = await examples_import(id="TC375_Blinky", targetDir=str(self.root / "failed"))
        self.assertTrue(result.isError)
        self.assertIn("connection failed", result.content[0].text)
        self.assertNotIn("try build.run", result.content[0].text)
        self.assertIn("download", result.structuredContent["timingsMs"])
        self.assertNotIn("makefile", result.structuredContent["timingsMs"])
        regenerate.assert_not_called()

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