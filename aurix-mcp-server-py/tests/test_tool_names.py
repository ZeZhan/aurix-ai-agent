from __future__ import annotations

import asyncio
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server.server_fastmcp import mcp


class ToolNameTests(unittest.TestCase):
    def test_tool_names_are_accepted_by_vscode(self) -> None:
        # VS Code drops MCP tools whose names contain anything outside [a-z0-9_-].
        names = [tool.name for tool in asyncio.run(mcp.list_tools())]
        self.assertEqual(len(names), 11)
        for name in names:
            with self.subTest(name=name):
                self.assertRegex(name, re.compile(r"^[a-z0-9_-]+$"))

    def test_documentation_search_schema_keeps_agents_on_compact_output(self) -> None:
        tool = next(tool for tool in asyncio.run(mcp.list_tools()) if tool.name == "documentation_search")
        self.assertNotIn("detail", tool.inputSchema["properties"])
        self.assertNotIn('detail="full"', tool.description)
        self.assertIn("documentation_read", tool.description)
        self.assertIn("maximum 5 text excerpts", tool.description)


if __name__ == "__main__":
    unittest.main()
