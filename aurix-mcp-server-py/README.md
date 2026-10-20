# AURIX MCP Server

<p align="right"><b>English</b> | <a href="./README.zh-CN.md">简体中文</a></p>

Provides project creation, builds, flashing, example imports, and documentation
search for the AURIX AI extension, directly in Copilot Chat.

## Features

| Tool | Purpose |
|------|---------|
| `ads.create_project` | Create an AURIX project |
| `build.run` | Build a project |
| `flash.program` | Flash firmware |
| `illd.provision` | Add the required iLLD sources |
| `project.scan` | Inspect project structure, iLLD version, and available board pin labels |
| `examples.search` | Find AURIX examples |
| `examples.import` | Import an example into the workspace |
| `examples.read_source` | View example source code |
| `documentation.search` | Search AURIX documentation with source references |

## Usage

1. Install the [AURIX AI extension](../aurix-ai-agent-extension/README.md).
2. Open your project, then select a board and set the AURIX IDE path in the Configurator.
3. Enable the AURIX MCP tools in Copilot Chat's Agent mode and describe your task.

For example:

- "Find an LED blink example for the TC375 Lite."
- "Build the current project."
- "Which iLLD version does this project use?"

The extension starts the server automatically; no manual Python installation or
runtime setup is needed. For board pin queries, provide the exact board model
and hardware revision, and check the sources and applicability of the results.
