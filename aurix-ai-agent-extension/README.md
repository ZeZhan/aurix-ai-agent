# AI Agent for Infineon AURIX™ Microcontrollers

<p align="right"><b>English</b> | <a href="./README.zh-CN.md">简体中文</a></p>

VS Code extension for Infineon AURIX™ microcontroller firmware development with GitHub Copilot.
Provides a **Configurator** panel + auto-registered MCP tools for Copilot Chat.

## How it works

```
┌─────────────────────────────────┐
│  AURIX AI Configurator (sidebar)│
│  • Select device/board          │
│  • Set IDE path                 │
│  • Choose skills                │
│  • [Generate Copilot Config]    │
└────────────┬────────────────────┘
             │ generates
             ▼
┌─────────────────────────────────┐
│  .github/                       │
│   copilot-instructions.md       │
│   skills/*.md                   │
└────────────┬────────────────────┘
             │ consumed by
             ▼
┌─────────────────────────────────┐
│  Copilot Chat (Agent mode)      │
│  + AURIX MCP tools              │
│    (build, flash, examples,     │
│     illd, project scan)         │
└─────────────────────────────────┘
```

After installing the `.vsix`, click the **AURIX AI** icon in the Activity Bar
to open the Configurator. Fill in your settings, click **Generate Copilot
Config**, then open **Copilot Chat in Agent mode**. Open **Configure Tools**,
enable **`aurix-mcp-server`**, and enter your request.

No Python or uv installation is needed. The Windows x64 VSIX includes uv and
downloads an isolated Python runtime with tested MCP packages on first use.

## Build and deploy a local update

From the repository root:

```powershell
Push-Location .\aurix-ai-agent-extension
npm run build
Pop-Location

# Test the server that will actually be bundled, using synthetic chip fixtures.
# Clear production-index overrides in this test shell to avoid live-index tests.
$env:AURIX_DOCUMENTATION_INDEX_DIR = $null
$env:AURIX_DOCUMENTATION_INDEX = $null
.\.venv\Scripts\python.exe .\aurix-mcp-server-py\tests\smoke_stdio.py `
  --server-src .\aurix-ai-agent-extension\server\aurix-mcp-server-py\src
```

The test uses the repository development virtual environment. It checks MCP
tool discovery, documentation search/read pagination, reviewed board facts,
project scanning, and synthetic import/build operations; it does not flash
hardware. `npm run build` compiles TypeScript and copies skill templates, but
does **not** create a VSIX, update the installed extension, or synchronize the
standalone Python source into the bundled server. The documentation regression
suite checks parity of the four documentation-related source/bundled modules.

Only in an environment authorized to read and package **all** bundled data:

```powershell
Push-Location .\aurix-ai-agent-extension
npm run package
if ($LASTEXITCODE -eq 0) {
    code --install-extension .\aurix-ai-agent-extension-win32-x64.vsix --force
}
Pop-Location
```

Packaging requires the bundled documentation indexes and example catalogs,
VSCE, and the trusted uv binary/version/hash checked by
[the packaging script](scripts/package-vsix.js). Do not omit restricted indexes
to produce a misleading partial release, and do not install an older VSIX as if
it contained the new build.

After a successful installation, reload the VS Code window and restart the
AURIX MCP server through the MCP server controls. In Copilot's tool list, verify
that both `documentation_search` and `documentation_read` are exposed. A tool
list check establishes deployment, not engineering-answer quality; run the
frozen TC375 documentation evaluation separately
when authorized index access is available.

## Setup (2 things)

Configure via the Configurator panel or VS Code Settings (`aurix-ai-agent.*`).

### 1. Device — `selectedBoard`
Required for build / flash / debug.
Drives linker scripts, iLLD variant, and flash target.

### 2. IDE Path — `buildToolchainPath` (default `C:\Infineon\ide`)
Set this to the installation root of [AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio)
or [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio).
Standard and Limited installations are supported; the extension detects their
compiler and flasher layouts automatically.

## What needs what

| Feature              | Device | IDE Path |
| -------------------- | :----: | :------: |
| Chat / Q&A           |   –    |    –     |
| Generate device code |   ✓    |    –     |
| Build                |   ✓    |    ✓     |
| Flash                |   ✓    |    ✓     |

## Custom skills

The Configurator generates skill files in `.github/skills/`. Copilot loads
them on-demand when your request matches the skill's description.

Built-in skills: `aurix-behaviour-workflow`, `aurix-code-migration`,
`aurix-cross-vendor-migration`, `aurix-illd-lookup`.

You can add your own: create `.github/skills/<name>/SKILL.md` with YAML
frontmatter (`name`, `description`) and Markdown instructions. Copilot
discovers them automatically — no registration needed.

```markdown
---
name: my-custom-skill
description: One-sentence description of when this skill should activate.
---

# Instructions

Your workflow steps here...
```