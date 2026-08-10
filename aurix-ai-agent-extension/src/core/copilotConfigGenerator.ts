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
}

export const AVAILABLE_SKILLS: SkillDefinition[] = [
  {
    id: "aurix-behaviour-workflow",
    label: "Behaviour Workflow",
    description: "Step-by-step guide for implementing hardware behaviour (blink LED, PWM, UART, etc.)",
  },
  {
    id: "aurix-code-migration",
    label: "Code Migration",
    description: "Step-by-step guide for porting code between AURIX device families",
  },
  {
    id: "aurix-illd-lookup",
    label: "iLLD Lookup",
    description: "How to search iLLD headers for API signatures and register definitions",
  },
  {
    id: "aurix-cross-vendor-migration",
    label: "Cross-Vendor Migration",
    description: "Evaluate and functionally port NXP, ST, Renesas, or TI MCU demos to AURIX",
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
    "- `documentation.search` — search bundled TC2xx/TC3xx/TC4Dx manuals with",
    "  device-aware routing and physical PDF page citations.",
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
      const templatePath = path.join(__dirname, "..", "skills", skill.id, "SKILL.md");
      fs.copyFileSync(templatePath, skillPath);
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
