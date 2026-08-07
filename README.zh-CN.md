<div align="center">

# AURIX AI Agent

**面向 Infineon AURIX™ TriCore™ MCU（TC3xx / TC4x）的 AI 嵌入式软件助手 —— 在 VS Code 中用 Copilot 自动生成、构建并烧录固件。**

<a href="./README.md">English</a> | <b>简体中文</b>

</div>

---

## 如何使用

### Configurator + Copilot Chat + AURIX MCP（推荐）

扩展会自动注册 **AURIX MCP server**。使用内置的 Configurator 生成
`.github/copilot-instructions.md`（以及可选的 skill 文件），
之后 Copilot Chat 便能自动应用面向 AURIX 的工具与工作流规则。

1. 安装 [`aurix-ai-agent-extension`](aurix-ai-agent-extension/) VSIX。
2. 在侧边栏打开 **AURIX AI Configurator** 视图。
3. 填写设备 / IDE 路径，然后点击 **Generate Copilot Config**。
4. 以 **Agent** 模式打开 Copilot Chat。
5. 打开 **Configure Tools**，确认已勾选 **`aurix-mcp-server`**。
6. 提问：*“Create a TC375 blinky and flash it.”* —— Copilot 会调用 AURIX MCP
  工具创建目标设备空项目、按需求生成代码，然后编译并烧录到开发板。

---

## 演示画廊

### Pose Game —— 摄像头 → 以太网 → TC375 → SPI TFT
AI 生成的姿态检测运行在 PC 摄像头上，经以太网串流到驱动 SPI TFT 触摸屏的
TC375，实现实时显示与一个小游戏 —— 全部由 AI agent 编写。

| | Prompt | 时长 | 链接 |
|---|---|---|---|
| [<img src="https://img.youtube.com/vi/MV0CGIHywlQ/hqdefault.jpg" width="320"/>](https://youtube.com/shorts/MV0CGIHywlQ) | *""* | ~60 s | [▶ 观看](https://youtube.com/shorts/MV0CGIHywlQ) |

### Blinky —— 从 Copilot Chat 快速上手
一句话让 TC387 上所有 LED 闪烁 —— 代码生成、构建与烧录。

| | Prompt | 时长 | 链接 |
|---|---|---|---|
| [<img src="https://img.youtube.com/vi/mf0XcYsMz_o/hqdefault.jpg" width="320"/>](https://youtu.be/mf0XcYsMz_o) | *"Make all LEDs blink on TC387"* | ~2 min | [▶ 观看](https://youtu.be/mf0XcYsMz_o) |



---

## 环境要求

- **Windows x64。** 当前发布的 VSIX 仅支持 `win32-x64`。
- **VS Code** + **GitHub Copilot**(Agent 模式)。
- **无需安装 Python 或 uv。** Windows 扩展已内置 [uv](https://docs.astral.sh/uv/),首次使用时会自动下载独立的 Python 环境和经过测试的 MCP 依赖。
- 构建/烧录还需安装 **AURIX IDE**（[AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio) 或 [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio)），以提供 TriCore 工具链与烧录器。

---

## 快速开始

1. 安装 [`aurix-ai-agent-extension`](aurix-ai-agent-extension/) VSIX。
2. 在侧边栏打开 **AURIX AI Configurator**，选择目标设备并填写 IDE 路径，然后点击 **Generate Copilot Config**。
3. 这会写入 `.github/copilot-instructions.md` 并自动注册 AURIX MCP server。
4. 以 **Agent** 模式打开 Copilot Chat，在 **Configure Tools** 中确认已勾选 **`aurix-mcp-server`**。
5. 开始提问 —— Copilot 会自动调用所需的 AURIX 工具。

---

## 软件包

- **[aurix-ai-agent-extension](aurix-ai-agent-extension/)** —— VS Code 扩展：Configurator UI、
  `copilot-instructions.md` + skill 文件生成器，以及 MCP server 自动注册。
- **[aurix-mcp-server-py](aurix-mcp-server-py/)** —— Model Context Protocol 服务器（Python），
  暴露 AURIX 工具：项目脚手架、iLLD 供给、构建、烧录、示例导入、设备上下文搜索。

各软件包的安装与配置详情请参见其各自的 README。

---

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。内置的 Infineon 示例代码摘录保留
原文件版权声明及 Boost Software License 1.0 条款。

AURIX™ 和 TriCore™ 是 Infineon Technologies AG 的商标。本文中的商标仅用于
说明产品兼容性，不代表 Infineon Technologies AG 对本项目的认可或背书。
