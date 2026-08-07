"""Tool submodules for the AURIX MCP server.

Each tool's business logic lives in its own module as an async ``_run`` (or
``*_run``) coroutine. Tools are registered with FastMCP in
``aurix_mcp_server.server_fastmcp`` — there is no separate ToolDef registry.
"""
