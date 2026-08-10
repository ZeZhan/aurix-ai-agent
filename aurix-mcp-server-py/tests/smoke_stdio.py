"""Smoke test: drive the AURIX MCP server over stdio with the MCP client SDK.

Run:  python tests/smoke_stdio.py
"""

import asyncio
import os
import sys

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
            assert {"query", "topK", "indexPath", "device", "family"} <= set(
                documentation_properties
            )

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
