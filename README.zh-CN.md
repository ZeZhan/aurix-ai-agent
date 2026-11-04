<div align="center">

# AURIX AI Agent

**面向英飞凌 AURIX™ TriCore™ MCU（TC3xx / TC4x）的 AI 嵌入式软件助手 —— 在 VS Code 中用 Copilot 自动生成、构建并烧录固件。**

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

<div align="center">

<img src="media/debug-loop.zh-CN.svg" width="720" alt="你的需求 → 生成代码 → 构建 → 烧录 → 调试 → 在板子上运行；检查未通过时从调试回到生成代码"/>

</div>

### Demo 1 —— 从空文件夹开始的按键与 LED（TC375 lite Kit）
按下 BUTTON1 切换 LED1（带软件消抖），LED2 由 STM 定时器中断驱动，以 1 Hz 闪烁。agent 从已连接的板卡识别硬件版本，所有引脚和有效电平都取自板卡手册并在代码中注明页码，一次完成构建和烧录，全程没有向用户提问。

| | 任务 | 模型 | 时长 | 链接 |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/8RlI9NKPQiE/hqdefault.jpg" width="320"/>](https://youtu.be/8RlI9NKPQiE) | 按键切换 LED（带消抖）+ STM 中断心跳灯，引脚引用板卡手册，构建并烧录 | GPT-6 Luna (medium) · 约 2.9 AI credits | ~6 min | [▶ 观看](https://youtu.be/8RlI9NKPQiE) |

<details>
<summary>Prompt</summary>

```text
On the TC375 lite Kit (KIT_A2G_TC375_LITE), create a small button/LED application from this empty workspace:

1. LED1 is off after reset. Each press of the on-board user button BUTTON1 toggles LED1 (press once: on, press again: off), exactly one toggle per press, with software debounce of about 20 ms.
2. LED2 blinks as a heartbeat: 500 ms on, 500 ms off, driven by an STM timer interrupt (not a busy-wait loop).
3. Take the LED and button pins and their active levels from the board documentation, and cite the document and page number in a code comment for each pin.
4. Build and flash the firmware to the connected board.

Finally, report: which files you created or changed, the source (document and page, or official example) for every pin and active level, and the build and flash results.
```

</details>

### Demo 2 —— 从空文件夹开始的 UART 控制台（TC4D7 lite Kit）
通过板载 USB 口实现的串口控制台：复位时打印芯片型号和 iLLD 版本，每秒输出一行状态，支持 `led on`、`led off`、`status` 命令。agent 以官方 UART shell 示例为基础，LED 和按键引脚取自板卡指南（注明页码），一次完成构建和烧录。

| | 任务 | 模型 | 时长 | 链接 |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/LIgmHI_rDQU/hqdefault.jpg" width="320"/>](https://youtu.be/LIgmHI_rDQU) | USB 串口控制台：周期状态输出、消抖按键计数、LED 命令，报告引脚来源，构建并烧录 | GPT-6 Luna (medium) · 约 3.3 AI credits | ~7 min | [▶ 观看](https://youtu.be/LIgmHI_rDQU) |

<details>
<summary>Prompt</summary>

```text
On the TC4D7 lite Kit (KIT_A3G_TC4D7_LITE), create a UART console from this empty workspace:

1. USB virtual COM port, 115200 baud. On reset, print the device name and iLLD version.
2. Every second, print uptime, LED1 state and the debounced BUTTON1 press count.
3. Commands: "led on" / "led off" switch LED1, "status" prints the status line, anything else replies "unknown command".
4. Build and flash, then report the changed files, the source of each pin, and the build and flash results.
```

</details>

### Demo 3 —— 两种模式的旋钮控制（TC375 lite Kit）
电位器当作旋钮用，按 BUTTON1 切换它控制的对象：LED1 亮度，或 LED2 闪烁频率。旋钮拧到底时两盏灯一起报警闪烁。当前模式和旋钮位置通过 USB 串口打印出来。agent 以官方 UART VCOM 示例为基础，通过板卡引脚映射把旋钮定位到 EVADC 第 0 组第 0 通道，用 GTM 硬件 PWM 而不是软件循环调节 LED1 亮度，一次完成构建和烧录。

| | 任务 | 模型 | 时长 | 链接 |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/IU6GJHU2Ipg/hqdefault.jpg" width="320"/>](https://youtu.be/IU6GJHU2Ipg) | 两种模式的电位器旋钮：LED1 PWM 亮度或 LED2 闪烁频率，超过 95 % 报警，USB 串口输出状态，报告引脚和 ADC 来源，构建并烧录 | GPT-6 Luna · 约 5.8 AI credits | ~9 min | [▶ 观看](https://youtu.be/IU6GJHU2Ipg) |

<details>
<summary>Prompt</summary>

```text
On the TC375 lite Kit (KIT_A2G_TC375_LITE), from this empty workspace:

1. The on-board potentiometer is a control knob with two modes, switched by BUTTON1:
   - Mode 1: the knob sets LED1 brightness (off to fully on).
   - Mode 2: the knob sets the LED2 blink rate from 1 to 10 Hz.
2. When the knob is at its maximum (above 95 %), both LEDs blink fast as an alarm, in either mode.
3. Over the USB virtual COM port at 115200 baud, print the mode on every change and the knob position in percent every 500 ms.
4. Build and flash, then report the changed files, the source of each pin and ADC channel, and the build and flash results.
```

</details>

### Demo 4 —— CAN FD 急停，用调试器验证（TC375 lite Kit）
单块板上的机器人急停总线：两个 MCMCAN 节点在内部回环中分别扮演控制器和关节，按下 BUTTON1 发送高优先级急停帧。**随后 AI 亲自调试运行中的板子：** 设断点、单步走过 CAN 接收中断、读取实时变量和错误计数，证明每一帧都完整到达；再请用户按下 BUTTON1，确认急停断点命中、关节切换到 STOP。

| | 任务 | 模型 | 时长 | 链接 |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/fwrYIHnp7wI/hqdefault.jpg" width="320"/>](https://youtu.be/fwrYIHnp7wI) | 基于 MCMCAN 内部回环的 CAN FD 急停，AI 用断点和实时变量调试运行中的板子，构建并烧录 | GPT-6 Luna · 约 20.8 AI credits | ~22 min | [▶ 观看](https://youtu.be/fwrYIHnp7wI) |

<details>
<summary>Prompt</summary>

```text
On the TC375 lite Kit (KIT_A2G_TC375_LITE), from this empty workspace, build a robot emergency-stop demo over CAN FD using MCMCAN internal loopback (no external wiring):

1. CAN node 0 is the controller. Every 10 ms it sends the potentiometer position (0-100 %) as the joint target. When BUTTON1 is pressed, it sends a high-priority E-STOP frame.
2. CAN node 1 is the joint. It sets LED1 brightness from the received target. On E-STOP it switches LED1 off and blinks LED2 fast until BUTTON1 is pressed again.
3. Over the USB virtual COM port at 115200 baud, print the target, the TX and RX frame counts and the joint state every 500 ms.
4. Build and flash. Then verify with the debugger, not just by build success: confirm the received target matches the sent one, the frame counts increase and the CAN error counters stay at zero. Set a breakpoint where E-STOP is received, ask me to press BUTTON1, and confirm it is hit and the joint state changes to STOP. If anything disagrees, find the cause, fix it, rebuild, reflash and verify again.
5. Report the changed files, the source of each pin, a table of each check with expected and measured values, and every fix made during the debug loop.
```

</details>

### Pose Game —— 摄像头 → 以太网 → TC375 → SPI TFT
AI 生成的姿态检测运行在 PC 摄像头上，经以太网串流到驱动 SPI TFT 触摸屏的
TC375，实现实时显示与一个小游戏 —— 全部由 AI agent 编写。

| | Prompt | 时长 | 链接 |
|---|---|---|---|
| [<img src="https://img.youtube.com/vi/MV0CGIHywlQ/hqdefault.jpg" width="320"/>](https://youtube.com/shorts/MV0CGIHywlQ) | *""* | ~60 s | [▶ 观看](https://youtube.com/shorts/MV0CGIHywlQ) |



---

## AI 调试（可选）

安装开源的 [AURIX TCF Debugger for VS Code](https://github.com/ZeZhan/vscode-aurix-tcf-debugger) 即可形成闭环。它内置的 **Debug MCP** 让 Copilot 在已连接的开发板上启动调试会话、设断点、单步执行，并读取变量、内核寄存器和外设寄存器，且与 VS Code 调试界面共用同一个会话。检查未通过时，agent 会修改代码、重新构建、烧录并再次检查（见 Demo 4）。写外设寄存器始终需要你确认。

---

## 环境要求

- **Windows x64。** 当前发布的 VSIX 仅支持 `win32-x64`。
- **VS Code** + **GitHub Copilot**(Agent 模式)。
- **无需安装 Python 或 uv。** Windows 扩展已内置 [uv](https://docs.astral.sh/uv/),首次使用时会自动下载独立的 Python 环境和经过测试的 MCP 依赖。
- 构建/烧录还需安装 **AURIX IDE**（[AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio) 或 [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio)），以提供 TriCore 工具链与烧录器。
- **AI 调试（可选）：** [AURIX TCF Debugger](https://github.com/ZeZhan/vscode-aurix-tcf-debugger) 扩展，以及 DAS 8.3.0.1 或更高版本。

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
  暴露 AURIX 工具：项目脚手架、iLLD 供给、构建、烧录、示例导入，以及带 PDF
  物理页码引用、按设备自动路由的 TC2xx/TC3xx/TC4Dx 离线文档检索。

各软件包的安装与配置详情请参见其各自的 README。

---

## 常见问题

<details>
<summary><b>agent 用到了哪些工具？</b></summary>

> 都来自 AURIX Development Studio（ADS）或 AURIX Configuration Studio（ACS）：TriCore GCC 编译器、AURIX Flasher 和 TCF 调试器。iLLD 和官方代码示例从 Infineon 的公开 GitHub 仓库下载。

</details>

<details>
<summary><b>AI 怎么找到这些工具？</b></summary>

> 打开 AURIX AI 侧边栏，进入 Configurator，选择板卡，填上本机 ADS 或 ACS 的安装路径。扩展会把这个路径交给 MCP server，编译器和烧录器它会自己找到。

</details>

<details>
<summary><b>支持哪些 AI 客户端？</b></summary>

> 主要支持 VS Code 里的 GitHub Copilot，扩展会自动配好。MCP server 和 skill 都是通用的，也可以手动配置到 Claude Code、Codex 等其他客户端：注册 [`aurix-mcp-server-py`](aurix-mcp-server-py/) 里的 server（`python -m aurix_mcp_server`，并把环境变量 `AURIX_ADS_STUDIO_PATH` 设为 IDE 路径），再把 [`skills/`](skills/) 里的 skill 拷过去。这种方式需要自己配置，测试也比较少。

</details>

<details>
<summary><b>支持哪些芯片？</b></summary>

> TC2xx、TC3xx 和 TC4xx。

</details>

<details>
<summary><b>需要 license 吗？</b></summary>

> 不需要。agent 依赖的是 ADS 或 ACS 里的免费工具，以及公开的 iLLD 和代码示例。你只需要一个 AI 客户端，比如 GitHub Copilot 订阅。

</details>

<details>
<summary><b>可以用于量产项目吗？</b></summary>

> 不可以。它定位于评估用途：借助现有的免费工具加快开发、提高效率。生成的代码在用于产品之前，请自行审查和测试。

</details>

---

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。内置的 Infineon 示例代码摘录保留
原文件版权声明及 Boost Software License 1.0 条款。

AURIX™ 和 TriCore™ 是 Infineon Technologies AG 的商标。本文中的商标仅用于
说明产品兼容性，不代表 Infineon Technologies AG 对本项目的认可或背书。
