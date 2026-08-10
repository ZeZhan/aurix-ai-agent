/**
 * AURIX AI Agent — VS Code Extension (Configurator + MCP registration)
 *
 * This extension provides:
 * 1. A configurator sidebar for device/toolchain/skill selection
 * 2. Auto-registration of the AURIX MCP server with Copilot Chat
 *
 * All AI chat goes through Copilot Chat natively — no built-in chat UI.
 */
import * as fs from "fs";
import * as path from "path";
import { spawnSync } from "child_process";
import * as vscode from "vscode";
import { ConfiguratorProvider } from "./configurator/ConfiguratorProvider";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// The Python MCP server exposes a `__main__`, so it
// is launched with `python -m aurix_mcp_server`. We bundle / locate the source
// directory so PYTHONPATH can be set when the package is not pip-installed.
const BUNDLED_PY_SERVER_DIR_RELATIVE = "server/aurix-mcp-server-py";
const BUNDLED_DOCUMENTATION_DIR_RELATIVE = "server/aurix-mcp-server-py/data/documentation";
const DEFAULT_PY_SERVER_DIR_RELATIVE = "aurix-mcp-server-py";
const PY_MODULE = "aurix_mcp_server";

// The MCP server's tested runtime dependencies (kept in sync with pyproject.toml).
const UV_DEPS = ["mcp==1.28.1", "httpx==0.28.1"];

const DEFAULT_BOARD_OPTIONS: Array<{ family: string; name: string; description: string; part: string }> = [
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC297_TFT_BC-Step", description: "APPLICATION KIT TC2X7 V1.1", part: "TC297" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC277_TFT_DC-Step", description: "APPLICATION KIT TC2X7 V1.1", part: "TC277" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC275_LITE", description: "AURIX TC275 lite Kit", part: "TC275" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC275_ARD_SB", description: "hitex ShieldBuddy", part: "TC275" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC265_TFT_BC-Step", description: "APPLICATION KIT TC2X5 V2.0", part: "TC265" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC237_TFT_AC-Step", description: "APPLICATION KIT TC2X7 V1.1", part: "TC237" },
  { family: "AURIX TC2xx", name: "KIT_AURIX_TC234_TFT_AC-Step", description: "APPLICATION KIT TC2X4 V1.0", part: "TC234" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC397_5V_TFT", description: "APPLICATION KIT TC3X7 V2.0", part: "TC397" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC387_5V_TFT", description: "APPLICATION KIT TC3X7 V2.0", part: "TC387" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC377_5V_TFT", description: "APPLICATION KIT TC3X7 V2.0", part: "TC377" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC375_LITE", description: "AURIX TC375 lite Kit", part: "TC375" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC375_ARD_SB", description: "hitex ShieldBuddy", part: "TC375" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC367_5V_TFT", description: "APPLICATION KIT TC3X7 V2.0", part: "TC367" },
  { family: "AURIX TC3xx", name: "KIT_A2G_TC334_LITE", description: "AURIX TC334 lite Kit", part: "TC334" },
  { family: "AURIX TC4Dx", name: "KIT_A3G_TC4D7_LITE", description: "AURIX TC4D7 lite Kit", part: "TC4D7" },
];

let extensionInstallPath: string | undefined;
let output: vscode.OutputChannel | undefined;
let configuratorProvider: ConfiguratorProvider | undefined;

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext) {
  extensionInstallPath = context.extensionPath;
  output = vscode.window.createOutputChannel("AURIX AI Agent");
  context.subscriptions.push(output);

  // --- Configurator webview (sidebar) ---
  configuratorProvider = new ConfiguratorProvider();
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(
      ConfiguratorProvider.viewType,
      configuratorProvider,
    ),
  );

  // --- Auto-register AURIX MCP server with Copilot Chat ---
  registerAurixMcpProvider(context);

  // --- Commands ---
  context.subscriptions.push(
    vscode.commands.registerCommand("aurix-ai-agent.selectDevice", async () => {
      const folder = getPrimaryWorkspaceFolder();
      if (!folder) {
        void vscode.window.showWarningMessage("Open a workspace folder first.");
        return;
      }
      const boards = DEFAULT_BOARD_OPTIONS;
      const picked = await vscode.window.showQuickPick(
        boards.map((b) => ({
          label: b.name,
          description: b.description,
          detail: `${b.family} | ${b.part}`,
        })),
        { title: "AURIX AI Agent — Select Board", placeHolder: "Select target board" },
      );
      if (!picked) { return; }
      const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
      await cfg.update("selectedBoard", picked.label, vscode.ConfigurationTarget.WorkspaceFolder);
      configuratorProvider?.refresh();
      void vscode.window.showInformationMessage(`AURIX board: ${picked.label}`);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aurix-ai-agent.selectIdePath", async () => {
      const folder = getPrimaryWorkspaceFolder();
      if (!folder) {
        void vscode.window.showWarningMessage("Open a workspace folder first.");
        return;
      }
      const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
      const current = cfg.get<string>("buildToolchainPath", "");
      const result = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        openLabel: "Select IDE Folder",
        title: "AURIX AI Agent — Select IDE Installation Path",
        defaultUri: current ? vscode.Uri.file(current) : undefined,
      });
      if (!result || result.length === 0) { return; }
      await cfg.update("buildToolchainPath", result[0].fsPath, vscode.ConfigurationTarget.WorkspaceFolder);
      configuratorProvider?.refresh();
      void vscode.window.showInformationMessage(`IDE path: ${result[0].fsPath}`);
    }),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("aurix-ai-agent.generateConfig", async () => {
      // Trigger generate from command palette (same as clicking button in configurator)
      const folder = getPrimaryWorkspaceFolder();
      if (!folder) {
        void vscode.window.showWarningMessage("Open a workspace folder first.");
        return;
      }
      const { AVAILABLE_SKILLS, generateCopilotConfig } = await import("./core/copilotConfigGenerator");
      const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
      const result = generateCopilotConfig(folder.uri.fsPath, {
        device: cfg.get<string>("selectedBoard", "") || cfg.get<string>("selectedDevice", ""),
        idePath: cfg.get<string>("buildToolchainPath", ""),
        skills: AVAILABLE_SKILLS.map((s) => s.id),
      });
      if (result.errors.length > 0) {
        void vscode.window.showErrorMessage(`Errors: ${result.errors.join("; ")}`);
      } else {
        void vscode.window.showInformationMessage(
          `Generated ${result.filesWritten.length} file(s): ${result.filesWritten.join(", ")}`,
        );
      }
    }),
  );

  // Refresh configurator when settings change externally
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (
        e.affectsConfiguration("aurix-ai-agent.selectedBoard") ||
        e.affectsConfiguration("aurix-ai-agent.buildToolchainPath")
      ) {
        configuratorProvider?.refresh();
      }
    }),
  );

  output.appendLine("[aurix-ai-agent] Extension activated (configurator + MCP mode).");
}

export function deactivate() {
  extensionInstallPath = undefined;
}

// ---------------------------------------------------------------------------
// MCP Server Registration
// ---------------------------------------------------------------------------

function registerAurixMcpProvider(context: vscode.ExtensionContext): void {
  const lmAny = vscode.lm as unknown as {
    registerMcpServerDefinitionProvider?: (
      id: string,
      provider: vscode.McpServerDefinitionProvider,
    ) => vscode.Disposable;
  };
  if (typeof lmAny.registerMcpServerDefinitionProvider !== "function") {
    output?.appendLine("[mcp] vscode.lm.registerMcpServerDefinitionProvider not available; skipping.");
    return;
  }

  const onDidChange = new vscode.EventEmitter<void>();
  context.subscriptions.push(onDidChange);

  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => onDidChange.fire()),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (
        event.affectsConfiguration("aurix-ai-agent.mcpServerArgs") ||
        event.affectsConfiguration("aurix-ai-agent.mcpServerCwd") ||
        event.affectsConfiguration("aurix-ai-agent.mcpRuntime") ||
        event.affectsConfiguration("aurix-ai-agent.uvPath") ||
        event.affectsConfiguration("aurix-ai-agent.uvPython") ||
        event.affectsConfiguration("aurix-ai-agent.pythonPath") ||
        event.affectsConfiguration("aurix-ai-agent.pythonServerDir") ||
        event.affectsConfiguration("aurix-ai-agent.buildToolchainPath") ||
        event.affectsConfiguration("aurix-ai-agent.selectedBoard") ||
        event.affectsConfiguration("aurix-ai-agent.selectedDevice")
      ) {
        if (
          event.affectsConfiguration("aurix-ai-agent.uvPath") ||
          event.affectsConfiguration("aurix-ai-agent.mcpRuntime")
        ) {
          uvProbeCache.clear();
        }
        onDidChange.fire();
      }
    }),
  );

  const provider: vscode.McpServerDefinitionProvider = {
    onDidChangeMcpServerDefinitions: onDidChange.event,
    provideMcpServerDefinitions: () => {
      const folder = getPrimaryWorkspaceFolder();
      if (!folder) { return []; }
      output?.appendLine(`[mcp] folder=${folder.uri.fsPath}, runtime=python`);
      const spec = resolveMcpLaunchSpec(folder);
      if (!spec) {
        output?.appendLine("[mcp] Could not resolve MCP launch spec; skipping.");
        return [];
      }
      const def = new vscode.McpStdioServerDefinition(
        "AURIX MCP Server",
        spec.command,
        spec.args,
        spec.env ?? {},
        context.extension.packageJSON.version,
      );
      try { def.cwd = vscode.Uri.file(spec.cwd); } catch { /* ignore */ }
      output?.appendLine(`[mcp] Registered: ${spec.command} ${spec.args.join(" ")}`);
      return [def];
    },
  };

  context.subscriptions.push(
    lmAny.registerMcpServerDefinitionProvider!("aurix-ai-agent.mcp", provider),
  );
  output?.appendLine("[mcp] AURIX MCP server provider registered.");
}



// ---------------------------------------------------------------------------
// MCP Launch Spec Resolution
// ---------------------------------------------------------------------------

function resolveMcpLaunchSpec(folder: vscode.WorkspaceFolder): {
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
} | undefined {
  const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);

  // Pass the configured IDE path to the Python MCP server.
  const baseEnv: Record<string, string> = {};
  const idePath = resolveIdePath(folder);
  if (idePath) {
    baseEnv.AURIX_ADS_STUDIO_PATH = idePath;
    baseEnv.AURIX_IDE_PATH = idePath;
  }
  const selectedDevice = (
    cfg.get<string>("selectedBoard", "") || cfg.get<string>("selectedDevice", "")
  ).trim();
  if (selectedDevice) {
    baseEnv.AURIX_SELECTED_DEVICE = selectedDevice;
  }
  if (extensionInstallPath) {
    const documentationDir = path.join(extensionInstallPath, BUNDLED_DOCUMENTATION_DIR_RELATIVE);
    if (fs.existsSync(documentationDir)) {
      baseEnv.AURIX_DOCUMENTATION_INDEX_DIR = documentationDir;
    }
  }

  const runtime = (cfg.get<string>("mcpRuntime", "auto") || "auto").toLowerCase();

  // Prefer uv unless the user forced the "python" runtime.
  if (runtime !== "python") {
    const uvCommand = findUvCommand(folder, cfg);
    if (uvCommand) {
      const spec = resolveUvLaunchSpec(folder, cfg, baseEnv, uvCommand);
      if (spec) {
        return spec;
      }
    } else if (runtime === "uv") {
      // Runtime explicitly forced to uv but uv is missing — surface guidance.
      output?.appendLine("[mcp] runtime=uv but uv not found; cannot launch.");
      notifyUvMissing(folder);
      return undefined;
    }
    // runtime === "auto" and uv missing → fall through to Python fallback.
    if (runtime === "auto") {
      output?.appendLine("[mcp] uv not found; falling back to Python interpreter.");
      notifyUvMissing(folder);
    }
  }

  return resolvePythonLaunchSpec(folder, cfg, baseEnv);
}

/**
 * Locate the uv executable.
 * Priority: configured uvPath (absolute) → command on PATH (verified) → common install dirs.
 * Result is cached per resolved command to avoid repeated process spawns.
 */
const uvProbeCache = new Map<string, string | undefined>();
function findUvCommand(
  folder: vscode.WorkspaceFolder,
  cfg: vscode.WorkspaceConfiguration,
): string | undefined {
  const configured = resolveWorkspaceToken(folder, cfg.get<string>("uvPath", "uv").trim() || "uv");

  // Explicit absolute path wins if it exists.
  if (configured !== "uv" && path.isAbsolute(configured)) {
    return fs.existsSync(configured) ? configured : undefined;
  }

  if (uvProbeCache.has(configured)) {
    return uvProbeCache.get(configured);
  }

  const candidates = [configured];
  if (extensionInstallPath) {
    candidates.unshift(path.join(extensionInstallPath, "out", "vendor", "uv", "win32-x64", "uv.exe"));
  }
  const home = process.env.USERPROFILE || process.env.HOME || "";
  if (home) {
    candidates.push(
      path.join(home, ".local", "bin", "uv.exe"),
      path.join(home, ".cargo", "bin", "uv.exe"),
    );
  }
  const localAppData = process.env.LOCALAPPDATA;
  if (localAppData) {
    candidates.push(path.join(localAppData, "Microsoft", "WinGet", "Links", "uv.exe"));
  }

  let found: string | undefined;
  for (const candidate of candidates) {
    // Absolute candidates: quick existence check.
    if (path.isAbsolute(candidate)) {
      if (fs.existsSync(candidate)) { found = candidate; break; }
      continue;
    }
    // Bare command (e.g. "uv"): verify it actually runs.
    try {
      const res = spawnSync(candidate, ["--version"], { timeout: 5000, windowsHide: true });
      if (res.status === 0) { found = candidate; break; }
    } catch { /* not on PATH */ }
  }

  uvProbeCache.set(configured, found);
  return found;
}

/** Build a launch spec that runs the bundled server via `uv run`. */
function resolveUvLaunchSpec(
  folder: vscode.WorkspaceFolder,
  cfg: vscode.WorkspaceConfiguration,
  baseEnv: Record<string, string>,
  uvCommand: string,
): {
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
} | undefined {
  const serverDir = resolvePythonServerDir(folder);
  const cwd = resolveWorkspaceToken(folder, cfg.get<string>("mcpServerCwd", "${workspaceFolder}"));
  const env: Record<string, string> = { ...baseEnv };

  // The bundled server ships as source; make it importable via PYTHONPATH.
  if (serverDir) {
    const srcDir = path.join(serverDir, "src");
    if (fs.existsSync(srcDir)) {
      const existing = process.env.PYTHONPATH ?? "";
      env.PYTHONPATH = existing ? `${srcDir}${path.delimiter}${existing}` : srcDir;
    }
  }

  const uvPython = (cfg.get<string>("uvPython", "3.12") || "3.12").trim();
  const args: string[] = ["run", "--isolated", "--no-project", "--managed-python"];
  for (const dep of UV_DEPS) {
    args.push("--with", dep);
  }
  if (uvPython) {
    args.push("--python", uvPython);
  }

  // Allow custom module args; default to `python -m aurix_mcp_server`.
  const argsConfig = cfg.get<string[]>("mcpServerArgs", []);
  if (Array.isArray(argsConfig) && argsConfig.length > 0) {
    args.push("python", ...argsConfig.map((v) => resolveWorkspaceToken(folder, v)));
  } else {
    args.push("python", "-m", PY_MODULE);
  }

  return {
    command: uvCommand,
    args,
    cwd,
    env: Object.keys(env).length > 0 ? env : undefined,
  };
}

/** Build a launch spec for the Python MCP server (`python -m aurix_mcp_server`). */
function resolvePythonLaunchSpec(
  folder: vscode.WorkspaceFolder,
  cfg: vscode.WorkspaceConfiguration,
  baseEnv: Record<string, string>,
): {
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
} | undefined {
  const configuredPython = cfg.get<string>("pythonPath", "python").trim() || "python";
  const command = resolvePythonCommand(folder, configuredPython);
  if (!command) {
    output?.appendLine("[mcp] No compatible Python runtime found (requires Python 3.10+ with mcp and httpx).");
    notifyPythonUnavailable();
    return undefined;
  }
  const env: Record<string, string> = { ...baseEnv };

  const serverDir = resolvePythonServerDir(folder);
  const cwd = resolveWorkspaceToken(folder, cfg.get<string>("mcpServerCwd", "${workspaceFolder}"));

  // Custom args override the default module launch.
  const argsConfig = cfg.get<string[]>("mcpServerArgs", []);
  let args: string[];
  if (Array.isArray(argsConfig) && argsConfig.length > 0) {
    args = argsConfig.map((v) => resolveWorkspaceToken(folder, v));
  } else {
    args = ["-m", PY_MODULE];
  }

  // When the package is not pip-installed, prepend its src/ to PYTHONPATH so the
  // module is importable. Harmless when the package is already installed.
  if (serverDir) {
    const srcDir = path.join(serverDir, "src");
    if (fs.existsSync(srcDir)) {
      const existing = process.env.PYTHONPATH ?? "";
      env.PYTHONPATH = existing ? `${srcDir}${path.delimiter}${existing}` : srcDir;
    }
  }

  return {
    command,
    args,
    cwd,
    env: Object.keys(env).length > 0 ? env : undefined,
  };
}

/**
 * Resolve which Python executable to use.
 * Priority: configured path → workspace .venv → dev repo .venv → "python" on PATH.
 */
function resolvePythonCommand(folder: vscode.WorkspaceFolder, configured: string): string | undefined {
  const resolved = resolveWorkspaceToken(folder, configured);
  const candidates: string[] = [];

  if (resolved !== "python" && fs.existsSync(resolved)) { candidates.push(resolved); }

  const wsVenv = path.join(folder.uri.fsPath, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(wsVenv)) { candidates.push(wsVenv); }

  const serverDir = resolvePythonServerDir(folder);
  if (serverDir) {
    const devVenv = path.join(path.dirname(serverDir), ".venv", "Scripts", "python.exe");
    if (fs.existsSync(devVenv)) { candidates.push(devVenv); }
  }

  candidates.push(resolved, "python", "python3");
  for (const candidate of [...new Set(candidates)]) {
    try {
      const probe = spawnSync(candidate, [
        "-c",
        "import sys; assert sys.version_info >= (3, 10); import httpx; from mcp.server.fastmcp import FastMCP",
      ], { timeout: 5000, windowsHide: true });
      if (probe.status === 0) { return candidate; }
    } catch { /* unavailable or incompatible */ }
  }
  return undefined;
}

/** Locate the Python MCP server directory (containing src/aurix_mcp_server). */
function resolvePythonServerDir(folder: vscode.WorkspaceFolder): string | undefined {
  const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
  const configured = cfg.get<string>("pythonServerDir", `\${extensionPath}/${BUNDLED_PY_SERVER_DIR_RELATIVE}`);
  const configuredPath = asAbsoluteUnderWorkspace(folder, resolveWorkspaceToken(folder, configured));
  const workspaceDefault = path.join(folder.uri.fsPath, DEFAULT_PY_SERVER_DIR_RELATIVE);
  const bundled = extensionInstallPath ? path.join(extensionInstallPath, BUNDLED_PY_SERVER_DIR_RELATIVE) : "";

  for (const candidate of [configuredPath, workspaceDefault, bundled]) {
    if (candidate && fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function getPrimaryWorkspaceFolder(): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.workspaceFolders?.[0];
}

function resolveWorkspaceToken(folder: vscode.WorkspaceFolder, value: string): string {
  return value
    .replaceAll("${workspaceFolder}", folder.uri.fsPath)
    .replaceAll("${workspaceRoot}", folder.uri.fsPath)
    .replaceAll("${extensionPath}", extensionInstallPath ?? "");
}

function asAbsoluteUnderWorkspace(folder: vscode.WorkspaceFolder, value: string): string {
  if (path.isAbsolute(value)) { return value; }
  return path.resolve(folder.uri.fsPath, value);
}

function resolveIdePath(folder: vscode.WorkspaceFolder): string {
  const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
  return cfg.get<string>("buildToolchainPath", "").trim();
}

// ---------------------------------------------------------------------------
// uv guidance
// ---------------------------------------------------------------------------

let uvMissingNotified = false;
let pythonUnavailableNotified = false;

/**
 * Show a one-time, actionable notification when uv is not found. uv is the
 * recommended runtime because it auto-provisions Python + the server's
 * dependencies. Users can install it, switch to a system Python, or dismiss.
 */
function notifyUvMissing(folder: vscode.WorkspaceFolder): void {
  if (uvMissingNotified) { return; }
  uvMissingNotified = true;

  const INSTALL = "Install uv";
  const USE_PYTHON = "Use system Python";
  const LEARN = "Learn more";
  void vscode.window
    .showWarningMessage(
      "AURIX AI Agent: 'uv' was not found. uv lets the AURIX MCP server run without any manual Python setup (it provisions Python and dependencies automatically).",
      INSTALL,
      USE_PYTHON,
      LEARN,
    )
    .then((choice) => {
      if (choice === INSTALL) {
        const term = vscode.window.createTerminal("Install uv");
        term.show();
        // Official standalone installer (installs to the user profile, no admin).
        term.sendText('powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"');
        void vscode.window.showInformationMessage(
          "After uv finishes installing, reload VS Code (or reopen the folder) so the AURIX MCP server can use it.",
        );
      } else if (choice === USE_PYTHON) {
        const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
        void cfg.update("mcpRuntime", "python", vscode.ConfigurationTarget.WorkspaceFolder);
        void vscode.window.showInformationMessage(
          "AURIX MCP runtime set to 'python'. Ensure your Python has the server dependencies (mcp, httpx) installed.",
        );
      } else if (choice === LEARN) {
        void vscode.env.openExternal(vscode.Uri.parse("https://docs.astral.sh/uv/getting-started/installation/"));
      }
    });
}

function notifyPythonUnavailable(): void {
  if (pythonUnavailableNotified) { return; }
  pythonUnavailableNotified = true;

  const INSTALL = "Install uv";
  void vscode.window.showWarningMessage(
    "AURIX AI Agent: No compatible Python runtime was found. Python mode requires Python 3.10+ with mcp and httpx installed. Using uv is recommended.",
    INSTALL,
  ).then((choice) => {
    if (choice !== INSTALL) { return; }
    const term = vscode.window.createTerminal("Install uv");
    term.show();
    term.sendText('powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"');
    void vscode.window.showInformationMessage(
      "After uv finishes installing, reload VS Code so the AURIX MCP server can use it.",
    );
  });
}
