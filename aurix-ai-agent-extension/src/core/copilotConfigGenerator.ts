/**
 * copilotConfigGenerator.ts — On-demand generator for Copilot configuration files.
 *
 * Generates `.github/copilot-instructions.md` and `.github/skills/` files
 * based on user selections in the configurator panel. Replaces the old
 * auto-inject-on-activation approach with explicit user control.
 */
import * as fs from "fs";
import * as path from "path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface GeneratorConfig {
  device: string;
  idePath: string;
  skills: string[];
}

export interface GenerateResult {
  filesWritten: string[];
  errors: string[];
}

// ---------------------------------------------------------------------------
// Skill definitions
// ---------------------------------------------------------------------------

export interface SkillDefinition {
  id: string;
  label: string;
  description: string;
  content: string;
}

export const AVAILABLE_SKILLS: SkillDefinition[] = [
  {
    id: "aurix-behaviour-workflow",
    label: "Behaviour Workflow",
    description: "Step-by-step guide for implementing hardware behaviour (blink LED, PWM, UART, etc.)",
    content: [
      "---",
      "name: aurix-behaviour-workflow",
      "description: Implement a hardware behaviour on AURIX (blink LED, configure PWM, UART, SPI, ADC, timer, interrupt, DMA, etc.). Use when the user asks to write code that drives a peripheral, generates output, reads sensors, or produces observable behaviour on an AURIX TriCore target.",
      "---",
      "",
      "# Workflow for behaviour requests (e.g. *blink LED*, *configure PWM*)",
      "",
      "**Keep the work visible.** Before the first MCP call in a multi-step coding",
      "task, use the available task-list/Todo tool to create a visible checklist.",
      "Include research, setup/import, application edit, and build; include flash",
      "only when requested. Update each item as it starts and completes.",
      "",
      "1. **Decompose** the request into every concrete parameter (count, frequency,",
      "   pin, peripheral, baud rate, etc.). Implementation must cover all of them.",
      "   Also identify which **subsystems** are involved (display, comms, sensing …).",
      "2. **Research in parallel.** In the first turn launch `examples.search`",
      "   + `#codebase` together. If needed, search iLLD headers directly (see",
      "   skill `aurix-illd-lookup`). Cap follow-up research at 2–3 additional",
      "   rounds; use `examples.read_source` only for the most relevant hit. For",
      "   each subsystem, **classify** the best-matching example as *full-reuse*,",
      "   *partial-reuse*, or *reference-only* (see Hard rule 5 in",
      "   copilot-instructions.md).",
      "3. **Setup** — follow Hard rule 1 based on the reuse classification from step 2.",
      "4. **Write application code.** Start from the skeleton's or imported example's",
      "   `Cpu0_Main.c`; extend the existing init sequence.",
      "5. **Build** (`build.run`). On failure, read the **first** error and fix the",
      "   root cause — typically a source typo, not the Makefile. Max 3 repair",
      "   iterations; if a `-mcpu`/toolchain-flag error appears, regenerate via",
      "   `ads.create_project` rather than hand-editing. Missing iLLD source ⇒",
      "   `illd.provision`.",
      "6. **Flash only when requested.** If the user says *do not flash*, *build",
      "   only*, or equivalent, stop after a successful build and report the ELF.",
      "   Otherwise run `flash.program` when hardware programming is part of the request.",
      "",
      "For factual questions (e.g. *max TOM frequency?*), answer in chat from",
      "`examples.*` or by searching iLLD headers directly — do **not** scaffold a",
      "project. If the request implies behaviour on hardware, treat it as a code task.",
      "",
    ].join("\n"),
  },
  {
    id: "aurix-code-migration",
    label: "Code Migration",
    description: "Step-by-step guide for porting code between AURIX device families",
    content: [
      "---",
      "name: aurix-code-migration",
      "description: Migrate or port AURIX TriCore code between devices or families (e.g. TC4D7 to TC334, TC3xx to TC2xx, TC375 to TC397). Use when the user asks to port, migrate, convert, or adapt existing AURIX code to a different target device or board.",
      "---",
      "",
      "# Workflow for code migration (e.g. *migrate TC4D7 → TC334*)",
      "",
      "1. **New directory.** `ads.create_project` in a **fresh** workspace for the",
      "   target device. Never overwrite the source project in-place — leftover",
      "   SSW configs and build artifacts cause link errors. Copy only your",
      "   application `.c`/`.h` into the new workspace.",
      "2. **Research API differences.** Search iLLD headers for both source and",
      "   target devices to confirm peripheral names and API signatures (see",
      "   skill `aurix-illd-lookup`). Do not guess — cross-family moves",
      "   (TC4x↔TC3x↔TC2x) rename entire modules and change function signatures.",
      "3. **Resolve pins.** Check iLLD PinMap headers for the **target** device",
      "   to find the correct LED / UART / peripheral pins on the target board.",
      "   Never assume pins are the same across boards.",
      "4. **Global replace.** `grep_search` the workspace for every source-family",
      "   API and fix **all files in one pass** (Cpu0–CpuN, all app files). Do not",
      "   fix one file at a time.",
      "5. **Clean build.** Delete `build/` before the first target build.",
      "6. **Unsupported peripherals** — if the source uses a peripheral absent on",
      "   the target, stop and inform the user before proceeding.",
      "",
    ].join("\n"),
  },
  {
    id: "aurix-illd-lookup",
    label: "iLLD Lookup",
    description: "How to search iLLD headers for API signatures and register definitions",
    content: [
      "---",
      "name: aurix-illd-lookup",
      "description: Look up iLLD API signatures, structs, register definitions, or peripheral driver details by searching iLLD header files directly. Use when examples.read_source does not cover the needed API, or when you need to verify function signatures, config structs, or module availability for a specific AURIX device family.",
      "---",
      "",
      "# iLLD lookup (direct header search)",
      "",
      "When you need to look up iLLD API signatures, structs, or registers that are",
      "not covered by `examples.read_source`, search the iLLD headers **directly**",
      "using terminal commands or `grep_search` on the paths below.",
      "",
      "## iLLD locations (in priority order)",
      "",
      "1. Current workspace: `Libraries/iLLD/` (if project already has iLLD)",
      "2. ADS bundled iLLD: `C:\\\\Infineon\\\\<ADS-version>\\\\build_system\\\\bundled-artefacts-repo\\\\project-initializer\\\\tricore-tc<N>xx\\\\<ver>\\\\iLLDs\\\\Full_Set\\\\`",
      "3. GitHub cache: `~/.aurix-agent/illd_cache/illd_release_tc<N>x/src/`",
      "",
      "## iLLD directory structure",
      "",
      "```",
      "BaseSw/iLLD/TC<X>xx/Tricore/<Module>/<SubModule>/",
      "```",
      "",
      "Example: `BaseSw/iLLD/TC3xx/Tricore/Evadc/Adc/IfxEvadc_Adc.h`",
      "",
      "## Search strategy",
      "",
      "1. First try `grep_search` in the workspace `Libraries/iLLD/` path.",
      "2. If not found, check the ADS bundled path or GitHub cache.",
      "3. Search for the module name (e.g. `IfxGtm_Tom`) to find the relevant header.",
      "4. Once found, read the header to extract function signatures and config structs.",
      "5. Pay attention to the device family suffix (`TC2xx`, `TC3xx`, `TC4xx`) —",
      "   APIs differ across families.",
      "",
    ].join("\n"),
  },
];

// ---------------------------------------------------------------------------
// Instructions builder
// ---------------------------------------------------------------------------

function buildCopilotInstructions(config: GeneratorConfig): string {
  const lines: string[] = [
    "<!-- aurix-ai-agent:begin -->",
    "# AURIX development assistant",
    "",
    "Infineon AURIX (TriCore) workspace. The AURIX MCP server is auto-registered by",
    "the *AURIX AI Agent* extension. Prefer the MCP tools below over shell commands",
    "for anything involving AURIX hardware, building, flashing, or iLLD APIs.",
    "",
  ];

  // Device context
  if (config.device) {
    lines.push(`**Target device:** ${config.device}`, "");
  }

  lines.push(
    "## MCP tools (use dotted names verbatim)",
    "",
    "- `ads.create_project` — create a build-ready device skeleton (Makefile, linker,",
    "  `Ifx_Cfg.h`, `CpuN_Main.c` stubs). Pass `workspace` to deploy directly into",
    "  the project folder. **Use first for any new/empty workspace.**",
    "- `build.run` — build the project (auto-PATHs `tricore-gcc` + `make`).",
    "- `flash.program` — flash `.elf`/`.hex` (auto-locates `aurixflasher.exe`).",
    "- `examples.search` / `examples.read_source` — find and read official iLLD examples.",
    "- `examples.import` — copy an example's sources only (NOT build-ready; use for",
    "  reference files inside an existing project).",
    "- `illd.provision` — install/refresh iLLD libraries into a project.",
    "- `project.scan` — inspect workspace sources/includes/.cproject.",
    "",
  );

  lines.push(
    "## Task visibility",
    "",
    "For multi-step coding work, create a visible checklist with the available",
    "task-list/Todo tool before the first MCP call, then update item status while",
    "working. Do not add a flash step when the user explicitly says not to flash.",
    "",
    "## Hard rules",
    "",
    "1. **New/empty workspace — two paths:**",
    "   - **Writing code from scratch** → `ads.create_project` first (deploys",
    "     iLLD + linker + Makefile), then write application code.",
    "   - **Importing a complete example** → `examples.import` first, then",
    "     `ads.create_project` with `workspace` (generates only the Makefile;",
    "     it auto-skips iLLD/linker that the example already provides).",
    "2. **Before `build.run`, confirm a `Makefile` exists.** If unsure, run",
    "   `project.scan`. Don't blindly scan for purely factual questions.",
    "3. Never shell out to `make`, `tricore-gcc`, or `aurixflasher.exe`. Never",
    "   recursively search `C:\\Infineon` for toolchain binaries. For normal builds,",
    "   call `build.run` with `workspace` only (omit `command`). If an MCP build/flash",
    "   call fails, report or correct that call; do not fall back to terminal tools.",
    "4. After a generated skeleton, only write application files (`Cpu0_Main.c`,",
    "   user `.c`/`.h`). Do **not** touch `Makefile`, linker scripts, `Libraries/`,",
    "   or `Configurations/` unless the user explicitly asks to change build",
    "   configuration (extra source dirs, custom linker section, stack size, etc.).",
    "5. **Example reuse — tiered strategy:**",
    "   - If an example provides a **complete subsystem** the user needs (TFT",
    "     driver, UART shell, SPI init …), **import and adapt** it via",
    "     `examples.import` — do NOT rewrite working drivers from scratch.",
    "   - If an example is **narrower** than the user's scope (e.g. 1-LED vs.",
    "     4-LED), extract API patterns and design a proper multi-resource",
    "     implementation; do not duplicate a single-channel example N times.",
    "   - Otherwise, use the example only as an API reference.",
    "6. **Device must be known before scaffolding.** If the user's request requires",
    "   `ads.create_project` but does not specify a device, ask which AURIX",
    "   device/board to target before proceeding. Do not guess — the wrong device",
    "   wastes the entire skeleton.",
    "",
    "<!-- aurix-ai-agent:end -->",
    "",
  );

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Generate copilot-instructions.md and selected skill files into the workspace.
 * Called explicitly from the configurator UI.
 */
export function generateCopilotConfig(
  workspaceFsPath: string,
  config: GeneratorConfig,
): GenerateResult {
  const result: GenerateResult = { filesWritten: [], errors: [] };

  // --- Write copilot-instructions.md ---
  try {
    const instructionsDir = path.join(workspaceFsPath, ".github");
    fs.mkdirSync(instructionsDir, { recursive: true });
    const instructionsPath = path.join(instructionsDir, "copilot-instructions.md");
    const content = buildCopilotInstructions(config);
    fs.writeFileSync(instructionsPath, content, "utf8");
    result.filesWritten.push(".github/copilot-instructions.md");
  } catch (err) {
    result.errors.push(`copilot-instructions.md: ${String(err)}`);
  }

  // --- Write selected skill files ---
  const skillsDir = path.join(workspaceFsPath, ".github", "skills");
  for (const skillId of config.skills) {
    const skill = AVAILABLE_SKILLS.find((s) => s.id === skillId);
    if (!skill) { continue; }
    try {
      const skillDir = path.join(skillsDir, skill.id);
      fs.mkdirSync(skillDir, { recursive: true });
      const skillPath = path.join(skillDir, "SKILL.md");
      fs.writeFileSync(skillPath, skill.content, "utf8");
      result.filesWritten.push(`.github/skills/${skill.id}/SKILL.md`);
    } catch (err) {
      result.errors.push(`skill ${skill.id}: ${String(err)}`);
    }
  }

  // --- Remove skill files that were deselected ---
  for (const skill of AVAILABLE_SKILLS) {
    if (config.skills.includes(skill.id)) { continue; }
    const skillPath = path.join(skillsDir, skill.id, "SKILL.md");
    if (fs.existsSync(skillPath)) {
      try {
        fs.unlinkSync(skillPath);
        // Remove empty directory
        const dir = path.dirname(skillPath);
        if (fs.existsSync(dir) && fs.readdirSync(dir).length === 0) {
          fs.rmdirSync(dir);
        }
      } catch {
        // ignore cleanup errors
      }
    }
  }

  return result;
}
