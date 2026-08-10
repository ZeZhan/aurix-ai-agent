<div align="center">

# ⚡ AI Agent for Infineon AURIX™ Microcontrollers

### From one sentence to a blinking LED — in about 2 minutes.

**Tell GitHub Copilot what you want. The agent writes the firmware, builds it with the free GCC compiler, and flashes your Infineon AURIX™ MCU over USB — no manual setup.**

**Built entirely on free tools:** the GCC compiler, AURIX Flasher, and the public iLLD driver library and code examples.

<b>English</b> | <a href="./README.zh-CN.md">简体中文</a>

</div>

---

## 🚀 Blink your first LED in 2 minutes

> **You need:** VS Code + GitHub Copilot · an **AURIX IDE** installed ([AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio) *or* [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio)) · your board plugged in over **USB**.

1. **Install** the [`aurix-ai-agent-extension`](aurix-ai-agent-extension/) VSIX.
2. Open **AURIX AI** in the sidebar.
3. Select your **Target Device**, set the **IDE Path**, and click **Generate Copilot Config**.
4. Open **Copilot Chat** in **Agent** mode.
5. Open **Configure Tools** and make sure **`aurix-mcp-server`** is checked.
6. Type one sentence:

   > *"Create a TC375 blinky and flash it."*

That's it. The agent creates an empty project for your target device, generates the required code, builds it with GCC, and flashes it to your board with AURIX Flasher — and the LED starts blinking. 💡

<div align="center">

**`your prompt`  ➜  🧠 generate  ➜  🔨 build  ➜  ⚡ flash  ➜  💡 blink**

</div>

Prefer a guided setup? Open the **AURIX AI Configurator** in the sidebar, fill in your device + IDE path, and click **Generate Copilot Config** — it writes `.github/copilot-instructions.md` and registers the AURIX MCP server. In Copilot Chat, open **Configure Tools** and enable **`aurix-mcp-server`**.

---

## 🎬 See it in action

### Blinky — one sentence, ~2 minutes
One prompt to make every LED blink on a TC387 — generate, build, and flash.

| | Prompt | Time | |
|---|---|---|---|
| [<img src="https://img.youtube.com/vi/mf0XcYsMz_o/hqdefault.jpg" width="320"/>](https://youtu.be/mf0XcYsMz_o) | *"Make all LEDs blink on TC387"* | ~2 min | [▶ Watch](https://youtu.be/mf0XcYsMz_o) |

### Pose Game — webcam → Ethernet → TC375 → SPI TFT
AI-generated pose detection on a PC webcam, streamed over Ethernet to a TC375 driving an SPI TFT touchscreen — real-time display and a mini game, all coded by the agent.

| | | Time | |
|---|---|---|---|
| [<img src="https://img.youtube.com/vi/MV0CGIHywlQ/hqdefault.jpg" width="320"/>](https://youtube.com/shorts/MV0CGIHywlQ) | Real-time pose game on TC375 | ~60 s | [▶ Watch](https://youtube.com/shorts/MV0CGIHywlQ) |

---

## 🛠️ What the agent can do

Copilot calls these AURIX MCP tools automatically when relevant:

| Tool | What it does |
|---|---|
| `ads.create_project` | Create an iLLD project (Makefile + linker + startup) |
| `build.run` | Build with the free GCC compiler (finds it on PATH for you) |
| `flash.program` | Flash `.elf` / `.hex` to the board over USB with AURIX Flasher |
| `examples.search` · `examples.import` · `examples.read_source` | Find, inspect, and import public iLLD code examples |
| `illd.provision` | Install / update the public iLLD driver library |
| `project.scan` | Look at the workspace structure |

---

## 🧠 Built-in AURIX skills

The agent ships with expert AURIX workflows. The open skill files live in [`skills/`](skills/). **Generate Copilot Config** copies the selected skills into your project under `.github/skills/`, so Copilot follows proven, AURIX-specific steps instead of guessing.

| Skill | What it teaches Copilot |
|---|---|
| [Behaviour Workflow](skills/aurix-behaviour-workflow/SKILL.md) | Implement hardware behaviour — blink LED, PWM, UART, SPI, ADC, timers, interrupts, DMA |
| [Code Migration](skills/aurix-code-migration/SKILL.md) | Port code between AURIX devices and families (e.g. TC4D7 → TC334) |
| [Cross-Vendor Migration](skills/aurix-cross-vendor-migration/SKILL.md) | Evaluate and functionally port NXP, ST, Renesas, or TI MCU demos to AURIX |
| [iLLD Lookup](skills/aurix-illd-lookup/SKILL.md) | Search iLLD headers for API signatures, registers, and pin maps |

---

## ✅ Requirements

- **Windows x64.** The packaged VSIX is currently built for `win32-x64` only.
- **VS Code** with **GitHub Copilot** (Agent mode).
- An **AURIX IDE** — [AURIX Development Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-development-studio) *or* [AURIX Configuration Studio](https://www.infineon.com/design-resources/platforms/aurix-software-tools/aurix-tools/aurix-configuration-studio). Both are free and give you the **GCC compiler** and **AURIX Flasher**.
- **No Python or uv setup needed.** The Windows extension includes [uv](https://docs.astral.sh/uv/) and automatically downloads an isolated Python runtime and the tested MCP packages on first use.

The iLLD driver library and code examples are public and downloaded for you — nothing extra to buy.

---

## 📦 Packages

- **[aurix-ai-agent-extension](aurix-ai-agent-extension/)** — VS Code extension: Configurator UI, `copilot-instructions.md` + skill generator, and MCP server auto-registration.
- **[aurix-mcp-server-py](aurix-mcp-server-py/)** — Model Context Protocol server (Python) exposing the AURIX tools above.

See each package's README for installation and configuration details.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

Bundled Infineon code-example excerpts retain their original per-file notices
and Boost Software License 1.0 terms. See the package-level third-party notices.

AURIX™ and TriCore™ are trademarks of Infineon Technologies AG. Use of these
marks identifies product compatibility and does not imply endorsement.
