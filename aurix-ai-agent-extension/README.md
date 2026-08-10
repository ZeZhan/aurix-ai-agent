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