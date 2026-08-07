# MCP Server for Infineon AURIX™ Microcontrollers (Python)

<p align="right"><b>English</b> | <a href="./README.zh-CN.md">简体中文</a></p>

The MCP server for Infineon AURIX™ microcontrollers, built on the official
[`mcp`](https://pypi.org/project/mcp/) Python SDK. Tools are registered with
`FastMCP` and served over the SDK's stdio transport.

## Tools

| Tool | Purpose |
|------|---------|
| `ads.create_project` | Scaffold a new AURIX ADS project |
| `build.run` | Build a project (prepends tricore-gcc + make to PATH) |
| `flash.program` | Flash an `.elf`/image via aurixflasher |
| `illd.provision` | Provision iLLD sources for a device variant |
| `project.scan` | Scan and report project structure |
| `examples.search` | Search the bundled example index |
| `examples.import` | Import an example into the workspace |
| `examples.read_source` | Read source of a specific example |

## Run

### With uv (recommended — no manual Python setup)

[uv](https://docs.astral.sh/uv/) provisions a Python interpreter and the
server's dependencies automatically:

```pwsh
# from this folder
uv run --with mcp --with httpx --python 3.12 python -m aurix_mcp_server
```

The VS Code extension launches the bundled server this way by default.

### With an existing Python

```pwsh
# from this folder, with the workspace .venv active
$env:PYTHONPATH = "src"
python -m aurix_mcp_server            # start stdio MCP server
python -m aurix_mcp_server --doctor   # health report JSON
python -m aurix_mcp_server --version
```

Or install editable:

```pwsh
pip install -e .
aurix-mcp-server --doctor
```

## Test

```pwsh
python tests/smoke_stdio.py
```

## Layout

```
src/aurix_mcp_server/
  __init__.py          constants (name, version, protocol)
  __main__.py          CLI entry (stdio | doctor | version)
  server_fastmcp.py    FastMCP wiring (tool registration + instructions)
  context.py           .aurix-ai/context.json loader
  utils.py             helpers (LimitedBuffer, path/address parsing)
  tooldef.py           ToolResult / ToolContext primitives
  tools/
    __init__.py        tool package doc (registration lives in server_fastmcp)
    ads_create_project.py
    build_run.py
    flash_program.py
    illd_provision.py
    scan_project.py
    examples.py        examples.search / import / read_source
tests/
  smoke_stdio.py       end-to-end stdio client test
```
