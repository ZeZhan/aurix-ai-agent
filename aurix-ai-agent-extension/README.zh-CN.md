# AURIX AI Agent

<p align="right"><a href="./README.md">English</a> | <b>简体中文</b></p>

面向 AURIX™ 固件开发的 VS Code 扩展，配合 GitHub Copilot 使用。
提供一个 **Configurator（配置器）** 面板，并为 Copilot Chat 自动注册 MCP 工具。

## 工作原理

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

安装 `.vsix` 后，点击活动栏（Activity Bar）中的 **AURIX AI** 图标打开
Configurator。填写好设置后点击 **Generate Copilot Config**，随后以
**Agent 模式**打开 Copilot Chat，在 **Configure Tools** 中启用
**`aurix-mcp-server`**，然后输入需求。

无需安装 Python 或 uv。Windows x64 VSIX 已内置 uv，首次使用时会自动下载
独立的 Python 环境和经过测试的 MCP 依赖。

## 配置（两项）

可通过 Configurator 面板或 VS Code 设置（`aurix-ai-agent.*`）进行配置。

### 1. 设备 — `selectedBoard`
构建 / 烧录 / 调试均需要。
它决定链接脚本（linker script）、iLLD 变体以及烧录目标。

### 2. IDE 路径 — `buildToolchainPath`（默认 `C:\Infineon\ide`）
填写 [AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio)
或 [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio)
的安装根目录。标准版和 Limited 版均受支持；扩展会自动识别其编译器和
烧录器目录结构。

## 各功能所需项

| 功能                 | 设备 | IDE 路径 |
| -------------------- | :--: | :------: |
| 聊天 / 问答          |  –   |    –     |
| 生成设备代码         |  ✓   |    –     |
| 构建（Build）        |  ✓   |    ✓     |
| 烧录（Flash）        |  ✓   |    ✓     |

## 自定义 skill

Configurator 会在 `.github/skills/` 下生成 skill 文件。当你的请求与某个
skill 的 description 匹配时，Copilot 会按需加载它。

内置 skill：`aurix-behaviour-workflow`、`aurix-code-migration`、
`aurix-cross-vendor-migration`、`aurix-illd-lookup`。

你也可以添加自己的：创建 `.github/skills/<name>/SKILL.md`，带上 YAML
frontmatter（`name`、`description`）以及 Markdown 指令内容。Copilot 会自动
发现它们——无需注册。

```markdown
---
name: my-custom-skill
description: One-sentence description of when this skill should activate.
---

# Instructions

Your workflow steps here...
```
