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
| `documentation.search` | Search offline AURIX documentation with device-aware routing and physical PDF page citations |

## iLLD version reporting

`ads.create_project` and `project.scan` report the iLLD version declared in local
library headers. Unrecognized or conflicting versions are marked `unknown` or
`conflict`. No update checks or upgrades are performed.

## Board pin labels

`ads.create_project` and `project.scan` accept an optional `board`, such as
`KIT_A2G_TC375_LITE`. When omitted, a board ID passed as `device`, workspace
context, or the Configurator selection can supply it; a bare chip model does not
identify a board. Project-root `board_pin_label.bpl` takes precedence over the
matching BSP in the selected local ADS/ACS installation.

Creation copies an available BPL into the workspace without overwriting existing
files or adding board data to the shared device cache. Scanning is read-only.
Both report `boardPins` with annotated pins, aliases, source path/hash and original
line evidence. Missing or malformed BPL files do not block normal creation/scanning;
recognized board conflicts return no usable mappings. Unverified project board
identity is reported explicitly. BPL does not establish polarity or electrical
limits; unspecified hardware versions remain unknown. No vendor BPLs are bundled.

## Reviewed board electrical facts

`documentation.search` includes a small offline index of reviewed board facts.
Each result cites the official manual revision, section/table, physical PDF pages,
source URL and PDF hash. Voltage/current limits and pull-up settings are not covered.

| Board / Hardware | Reviewed Signals | Evidence |
| --- | --- | --- |
| TC375 Lite V2 | LED1 P00.5, LED2 P00.6, BUTTON1 P00.7; active low | Manual 2.2, pp10/11 |
| TC4D7 Lite V2.x | LED1 P03.9, LED2 P03.10, BUTTON1 P03.11; active low | 002-41555 Rev. *A, p9 |
| TC397 5V TFT V2.0 | D107-D110 P13.0-P13.3; active low. S101 RESET and S102 PMIC WAKE are not GPIO buttons | Manual V2.0, pp14/25 |

```json
{"query":"LED and button pins and polarity","board":"KIT_A2G_TC375_LITE","hardwareVersion":"V2"}
```

For TC4D7 use `KIT_A3G_TC4D7_LITE` with `V2.0` (the manual covers `2.x`).
For TC397 use `KIT_A2G_TC397_5V_TFT` with exact `V2.0`; set `topK: 10` for all
six facts. Do not substitute TriBoard or 3.3 V variants. TC397 buttons include
the electrical level's target (`level_at`) and `usageRestriction: not_a_gpio`.

An optional `projectPath` checks facts against the project BPL (or matching local
BSP). Mismatches are reported without overwriting either source. Missing hardware
revision returns `hardware_version_required`; conflicting pins suppress usable
facts. Check `requiresConfirmation`, `applicability`, and `usableForCodeGeneration`
before using results. Without `projectPath`, the evidence is manual-only, not a
verification of connected hardware. A bare chip does not identify the board.
Missing BPL labels return `not_mapped`, not a fabricated match or pin conflict;
the inspected TC397 installation BPL has no LED/button labels. Chinese/English
queries and board-specific names are supported. Other boards,
hardware revisions, and unreviewed electrical limits receive no supported evidence.

The small board index ships inside the Python package; it needs no chip index or
network access. Explicit `indexPath` overrides it and must include board metadata.
Source facts and rebuild instructions are in
[data/board_manuals](src/aurix_mcp_server/data/board_manuals/README.md).

## Documentation index

Documentation extraction and indexing, including any Docling processing, run
offline and outside the MCP server. The server only opens the resulting SQLite
index at query time. The VSIX bundles separate TC2xx, TC3xx, and TC4Dx indexes
and selects one from the query, `device`/`family`, or the Configurator board.
PDFs are never bundled. The standalone Python wheel does not include these chip indexes.

For a standalone server, configure an index directory or pass `indexPath` as an
override:

```pwsh
$env:AURIX_DOCUMENTATION_INDEX_DIR = "C:\path\to\documentation-indexes"
# Legacy single-index override:
$env:AURIX_DOCUMENTATION_INDEX = "C:\path\to\aurix-documentation.sqlite"
```

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
python -m unittest discover -s tests -p "test_*.py"
python tests/smoke_stdio.py
```

## Layout

```
src/aurix_mcp_server/
  __init__.py          constants (name, version, protocol)
  __main__.py          CLI entry (stdio | doctor | version)
  server_fastmcp.py    FastMCP wiring (tool registration + instructions)
  context.py           .aurix-ai/context.json loader
  documentation_retrieval.py  SQLite FTS retrieval + physical-page citations
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
    documentation_search.py  documentation.search MCP business logic
tests/
  smoke_stdio.py       end-to-end stdio client test
```
