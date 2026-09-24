"""Smoke test: drive the AURIX MCP server over stdio with the MCP client SDK.

Run:  python tests/smoke_stdio.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src")


async def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "aurix_mcp_server"],
        env=env,
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("initialize OK:", init.serverInfo.name, init.serverInfo.version)
            assert init.instructions and "AURIX" in init.instructions

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools/list:", names)
            assert {
                "ads.create_project", "build.run", "examples.import",
                "examples.read_source", "examples.search", "flash.program",
                "documentation.search", "illd.provision", "project.scan",
            } <= set(names)

            documentation_tool = next(
                tool for tool in tools.tools if tool.name == "documentation.search"
            )
            documentation_properties = documentation_tool.inputSchema["properties"]
            assert {"query", "topK", "indexPath", "device", "family", "board", "hardwareVersion", "projectPath"} <= set(
                documentation_properties
            )
            for name in ("ads.create_project", "project.scan"):
                tool = next(tool for tool in tools.tools if tool.name == name)
                assert "board" in tool.inputSchema["properties"]

            with tempfile.TemporaryDirectory() as project:
                bpl = Path(project) / "board_pin_label.bpl"
                bpl.write_text("// AURIX TC375 LITE KIT\n16, P0.5/LED1\n", encoding="utf-8")
                original = bpl.read_bytes()
                pins_result = await session.call_tool("project.scan", {
                    "projectPath": project, "board": "KIT_A2G_TC375_LITE",
                })
                assert pins_result.isError is False
                pins = pins_result.structuredContent["scan"]["boardPins"]
                assert pins["status"] == "detected"
                assert pins["pins"][0]["pin"] == "P00.5"
                assert pins["pins"][0]["aliases"] == ["LED1"]
                assert pins["pins"][0]["line"] == 2
                assert pins["source"]["kind"] == "project"
                assert pins["hardwareVersion"] is None
                assert pins["electricalProperties"] == "not_provided"
                assert bpl.read_bytes() == original
                print("project.scan BPL evidence OK:", pins["board"])

                evidence = await session.call_tool("documentation.search", {
                    "query": "LED1 pin and active level", "board": "KIT_A2G_TC375_LITE",
                    "hardwareVersion": "V2", "projectPath": project,
                })
                assert not evidence.isError
                item = evidence.structuredContent["results"][0]
                assert item["facts"][0]["pin"] == pins["pins"][0]["pin"]
                assert item["facts"][0]["active_level"] == "low"
                assert item["citation"]["pdf_pages"] == [10]
                assert item["bplCheck"] == "matched" and item["usableForCodeGeneration"]
                assert bpl.read_bytes() == original
                print("documentation.search BPL + pin/polarity/citation OK")

            for query in ("TC375 Lite V2 LED button", "TC375 Lite V2 LED\u548c\u6309\u94ae\u6709\u6548\u7535\u5e73"):
                evidence = await session.call_tool("documentation.search", {"query": query})
                assert not evidence.isError
                assert evidence.structuredContent["resultCount"] == 3
                assert not evidence.structuredContent["requiresConfirmation"]
            for arguments in (
                {"query": "LED1", "board": "KIT_A2G_TC375_LITE", "hardwareVersion": "V1"},
                {"query": "LED1", "board": "KIT_A2G_TC375_ARD_SB", "hardwareVersion": "V2"},
            ):
                evidence = await session.call_tool("documentation.search", arguments)
                assert not evidence.isError and evidence.structuredContent["abstained"]
            print("documentation.search board/revision/language checks OK")

            with tempfile.TemporaryDirectory() as project:
                bpl = Path(project) / "board_pin_label.bpl"
                bpl.write_text("// KIT_A3G_TC4D7_LITE V2.x\nF5, P3.9/LED1\nF4, P3.10/LED2\nG5, P3.11/BUTTON1\n", encoding="utf-8")
                original = bpl.read_bytes()
                evidence = await session.call_tool("documentation.search", {
                    "query": "TC4D7 Lite LED\u548c\u6309\u94ae", "hardwareVersion": "V2.0", "projectPath": project,
                })
                assert not evidence.isError
                assert evidence.structuredContent["resultCount"] == 3
                for item in evidence.structuredContent["results"]:
                    assert item["bplCheck"] == "matched" and item["usableForCodeGeneration"]
                    assert item["citation"]["pdf_pages"] == [9]
                assert bpl.read_bytes() == original

            evidence = await session.call_tool("documentation.search", {
                "query": "TC397 5V TFT V2.0 LED\u548c\u6309\u94ae", "topK": 10,
            })
            assert not evidence.isError
            assert evidence.structuredContent["resultCount"] == 6
            for item in evidence.structuredContent["results"]:
                fact = item["facts"][0]
                assert item["citation"]["pdf_pages"] == [14, 25]
                if fact["signal"].startswith("S"):
                    assert item["usageRestriction"] == "not_a_gpio" and not item["usableForCodeGeneration"]
                else:
                    assert fact["pin"] in {"P13.0", "P13.1", "P13.2", "P13.3"}
                    assert fact["active_level"] == "low"
            print("documentation.search TC4D7 BPL series and TC397 dedicated buttons OK")

            if os.environ.get("AURIX_DOCUMENTATION_INDEX_DIR"):
                documentation = await session.call_tool(
                    "documentation.search",
                    {"query": "TC397 BD-step errata", "topK": 1},
                )
                assert documentation.isError is False
                assert documentation.structuredContent
                assert documentation.structuredContent["family"] == "tc3xx"
                results = documentation.structuredContent["results"]
                assert results and results[0]["document_id"] == "tc39x-bd-errata"
                print("documentation.search routed OK:", results[0]["chunk_id"])
            elif os.environ.get("AURIX_DOCUMENTATION_INDEX"):
                documentation = await session.call_tool(
                    "documentation.search",
                    {
                        "query": "CPU_TC.H026 spurious lockstep error DSPR MBIST",
                        "topK": 1,
                    },
                )
                assert documentation.isError is False
                assert documentation.structuredContent
                results = documentation.structuredContent["results"]
                assert results and results[0]["citation"]["pdf_pages"] == [92]
                print("documentation.search OK:", results[0]["chunk_id"])

            # project.scan on this repo's python source dir → structured content
            res = await session.call_tool("project.scan", {"projectPath": SRC})
            assert res.isError is False
            assert res.structuredContent and "scan" in res.structuredContent
            print("project.scan OK:", res.structuredContent["scan"]["stats"])

    print("\nALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
