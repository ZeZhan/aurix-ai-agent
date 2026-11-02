<div align="center">

# AURIX AI Agent | AI Firmware Development for Infineon AURIX

### From natural-language requirements to firmware running on Infineon AURIX™.

**AURIX AI Agent is a firmware development assistant powered by GitHub Copilot and the Model Context Protocol (MCP) in VS Code. Describe the behavior you need, and it uses Infineon AURIX documentation, iLLD drivers, and code examples to create or modify firmware, build it with GCC, and flash it to your board.**

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

### Demo 1 — Button & LED from an empty folder (TC375 lite Kit)
BUTTON1 toggles LED1 with software debounce; LED2 blinks as a 1 Hz heartbeat from an STM timer interrupt. The agent detects the board revision from the connected kit, takes every pin and active level from the board user's manual and cites the page in the code, then builds and flashes on the first try. No questions asked.

| | Task | Model | Time | |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/d2pNy5nRjvw/hqdefault.jpg" width="320"/>](https://youtu.be/d2pNy5nRjvw) | Button-toggled LED with debounce + STM-interrupt heartbeat, pins cited from the board manual, build and flash | GPT-6 Luna (medium) · ~2.8 AI credits | ~6 min | [▶ Watch](https://youtu.be/d2pNy5nRjvw) |

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

### Demo 2 — UART console from an empty folder (TC4D7 lite Kit)
A serial console over the board's USB port: it prints the chip and iLLD version on reset, a status line every second, and takes `led on`, `led off` and `status` commands. The agent starts from the official UART shell example, takes the LED and button pins from the board guide (with page reference), and builds and flashes on the first try.

| | Task | Model | Time | |
|---|---|---|---|---|
| [<img src="https://img.youtube.com/vi/h3ZbVIxtaIM/hqdefault.jpg" width="320"/>](https://youtu.be/h3ZbVIxtaIM) | USB UART console with periodic status, debounced button counter and LED commands, pin sources reported, build and flash | GPT-6 Luna (medium) · ~6.3 AI credits | ~10 min | [▶ Watch](https://youtu.be/h3ZbVIxtaIM) |

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
| `ads_create_project` | Create an iLLD project (Makefile + linker + startup) |
| `build_run` | Build with the free GCC compiler (finds it on PATH for you) |
| `flash_program` | Flash `.elf` / `.hex` to the board over USB with AURIX Flasher |
| `flash_list_devices` | List connected kits (`AURIXFlasher -detect all`): chip, board ID, board hardware version; used to fill in the board revision for board documentation |
| `examples_search` · `examples_import` · `examples_read_source` | Find, inspect, and import public iLLD code examples |
| `documentation_search` | Search bundled TC2xx/TC3xx/TC4Dx documentation with device-aware routing and physical PDF page citations |
| `documentation_read` | Read or continue cited source chunks when search evidence is truncated |
| `illd_provision` | Install / update the public iLLD driver library |
| `project_scan` | Look at the workspace structure |

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

## ❓ FAQ

<details>
<summary><b>Which tools does the agent use?</b></summary>

The ones from AURIX Development Studio (ADS) or AURIX Configuration Studio (ACS): the TriCore GCC compiler, AURIX Flasher and the TCF debugger. iLLD and the official code examples are downloaded from Infineon's public GitHub repositories.

</details>

<details>
<summary><b>How does the AI find these tools?</b></summary>

Open the AURIX AI sidebar, go to the Configurator, select your board and enter the local path of your ADS or ACS installation. The extension passes that path to the MCP server, which then finds the compiler and the flasher on its own.

</details>

<details>
<summary><b>Which AI clients are supported?</b></summary>

GitHub Copilot in VS Code is the main target; the extension sets everything up for it. The MCP server and the skills are generic, so you can use them with other clients such as Claude Code or Codex: register the server from [`aurix-mcp-server-py`](aurix-mcp-server-py/) (`python -m aurix_mcp_server`, with `AURIX_ADS_STUDIO_PATH` pointing to your IDE) and copy the skills from [`skills/`](skills/). This setup is manual and less tested.

</details>

<details>
<summary><b>Which devices are supported?</b></summary>

TC2xx, TC3xx and TC4xx.

</details>

<details>
<summary><b>Do I need a license?</b></summary>

No. The agent relies on the free tools in ADS or ACS, plus the public iLLD and code examples. You only need an AI client, such as a GitHub Copilot subscription.

</details>

<details>
<summary><b>Is it ready for production use?</b></summary>

No. It is meant for evaluation: it uses the existing free tools to speed up development and improve productivity. Review and test the generated code yourself before using it in a product.

</details>

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

Bundled Infineon code-example excerpts retain their original per-file notices
and Boost Software License 1.0 terms. See the package-level third-party notices.

AURIX™ and TriCore™ are trademarks of Infineon Technologies AG. Use of these
marks identifies product compatibility and does not imply endorsement.
