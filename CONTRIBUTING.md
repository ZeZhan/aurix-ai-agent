# Contributing

Issues and pull requests are welcome. Keep changes focused, avoid committing
local AURIX projects or credentials, and preserve third-party license headers.

## Prerequisites

- Node.js 20 or later
- Python 3.10 or later, managed with [uv](https://docs.astral.sh/uv/)
- Windows x64 to build the packaged VSIX

## Validate changes

```pwsh
Push-Location aurix-ai-agent-extension
npm ci
npm audit
npm run build
Pop-Location

Push-Location aurix-ai-agent-extension/gui
npm ci
npm audit
npm run build
Pop-Location

uv lock --project aurix-mcp-server-py --check
uv run --project aurix-mcp-server-py --with pytest pytest aurix-mcp-server-py/tests -q
uv run --project aurix-mcp-server-py python aurix-mcp-server-py/tests/smoke_stdio.py
```

The Python MCP source under `aurix-mcp-server-py/src/aurix_mcp_server` and the
copy bundled by the extension must remain byte-identical. Run the public export
guard before preparing a release:

```pwsh
./scripts/publish-public.ps1
```