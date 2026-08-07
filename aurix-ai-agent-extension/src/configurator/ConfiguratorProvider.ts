/**
 * ConfiguratorProvider — VS Code webview that shows a configuration form.
 *
 * Users select device, IDE path, and skills, then click
 * "Generate" to write copilot-instructions.md + skill files into the workspace.
 */
import * as vscode from "vscode";
import { AVAILABLE_SKILLS, generateCopilotConfig } from "../core/copilotConfigGenerator";

export class ConfiguratorProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "aurixAiAgent.chatView";

  private _view: vscode.WebviewView | undefined;

  constructor() {}

  resolveWebviewView(
    webviewView: vscode.WebviewView,
    _resolveContext: vscode.WebviewViewResolveContext,
    _token: vscode.CancellationToken,
  ): void {
    this._view = webviewView;
    webviewView.webview.options = { enableScripts: true };
    webviewView.webview.html = this._getHtml(webviewView.webview);

    webviewView.webview.onDidReceiveMessage((msg) => {
      this._handleMessage(msg);
    });

    // Push initial state when view becomes visible
    webviewView.onDidChangeVisibility(() => {
      if (webviewView.visible) {
        this._sendCurrentState();
      }
    });

    this._sendCurrentState();
  }

  /** Refresh the webview state (e.g. after settings change externally). */
  refresh(): void {
    if (this._view?.visible) {
      this._sendCurrentState();
    }
  }

  private _sendCurrentState(): void {
    const folder = vscode.workspace.workspaceFolders?.[0];
    if (!folder || !this._view) { return; }

    const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
    this._view.webview.postMessage({
      type: "setState",
      state: {
        device: cfg.get<string>("selectedBoard", "") || cfg.get<string>("selectedDevice", ""),
        idePath: cfg.get<string>("buildToolchainPath", ""),
        skills: AVAILABLE_SKILLS.map((s) => s.id), // all selected by default
        workspace: folder.uri.fsPath,
      },
    });
  }

  private async _handleMessage(msg: any): Promise<void> {
    switch (msg.type) {
      case "generate": {
        const folder = vscode.workspace.workspaceFolders?.[0];
        if (!folder) {
          void vscode.window.showWarningMessage("Open a workspace folder first.");
          return;
        }

        // Persist settings
        const cfg = vscode.workspace.getConfiguration("aurix-ai-agent", folder.uri);
        if (msg.config.device) {
          await cfg.update("selectedBoard", msg.config.device, vscode.ConfigurationTarget.WorkspaceFolder);
        }
        if (msg.config.idePath) {
          await cfg.update("buildToolchainPath", msg.config.idePath, vscode.ConfigurationTarget.WorkspaceFolder);
        }

        // Generate files
        const result = generateCopilotConfig(folder.uri.fsPath, {
          device: msg.config.device ?? "",
          idePath: msg.config.idePath ?? "",
          skills: msg.config.skills ?? [],
        });

        if (result.errors.length > 0) {
          void vscode.window.showErrorMessage(
            `Config generation errors: ${result.errors.join("; ")}`,
          );
        } else {
          void vscode.window.showInformationMessage(
            `Generated ${result.filesWritten.length} file(s): ${result.filesWritten.join(", ")}`,
          );
        }

        // Notify webview of success
        this._view?.webview.postMessage({
          type: "generateResult",
          success: result.errors.length === 0,
          filesWritten: result.filesWritten,
          errors: result.errors,
        });
        break;
      }

      case "selectDevice": {
        void vscode.commands.executeCommand("aurix-ai-agent.selectDevice");
        break;
      }

      case "selectIdePath": {
        void vscode.commands.executeCommand("aurix-ai-agent.selectIdePath");
        break;
      }

      case "requestState": {
        this._sendCurrentState();
        break;
      }

    }
  }

  private _getHtml(webview: vscode.Webview): string {
    const nonce = getNonce();
    const skillCheckboxes = AVAILABLE_SKILLS.map(
      (s) =>
        `<label class="skill-item">
          <input type="checkbox" name="skill" value="${s.id}" checked />
          <div class="skill-info">
            <span class="skill-label">${s.label}</span>
            <span class="skill-desc">${s.description}</span>
          </div>
        </label>`,
    ).join("\n");

    return /*html*/ `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="Content-Security-Policy"
    content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AURIX AI Configurator</title>
  <style nonce="${nonce}">
    :root {
      --vscode-font: var(--vscode-font-family, system-ui, sans-serif);
      --card-bg: var(--vscode-editorWidget-background, var(--vscode-sideBar-background));
      --card-border: var(--vscode-widget-border, var(--vscode-panel-border, rgba(128,128,128,0.2)));
      --accent: var(--vscode-button-background);
      --accent-hover: var(--vscode-button-hoverBackground);
      --accent-fg: var(--vscode-button-foreground);
      --brand-1: #4f8cff;
      --brand-2: #8a5cff;
      --radius: 10px;
      --radius-sm: 6px;
      --shadow-sm: 0 1px 2px rgba(0,0,0,0.10);
      --shadow-md: 0 6px 20px rgba(0,0,0,0.22);
    }
    * { box-sizing: border-box; }
    body {
      font-family: var(--vscode-font);
      font-size: var(--vscode-font-size, 13px);
      color: var(--vscode-foreground);
      background: var(--vscode-sideBar-background);
      padding: 14px;
      margin: 0;
      line-height: 1.45;
    }

    /* Hero header */
    .header {
      position: relative;
      display: flex;
      align-items: center;
      gap: 12px;
      margin: -14px -14px 16px;
      padding: 18px 16px;
      border-bottom: 1px solid var(--card-border);
      background:
        linear-gradient(135deg, rgba(79,140,255,0.16), rgba(138,92,255,0.10)),
        var(--vscode-sideBar-background);
      overflow: hidden;
    }
    .header::after {
      content: '';
      position: absolute;
      top: -45px;
      right: -25px;
      width: 130px;
      height: 130px;
      background: radial-gradient(circle, rgba(138,92,255,0.22), transparent 70%);
      pointer-events: none;
    }
    .header-icon {
      position: relative;
      width: 38px;
      height: 38px;
      border-radius: 10px;
      background: linear-gradient(135deg, var(--brand-1), var(--brand-2));
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      box-shadow: 0 4px 12px rgba(79,140,255,0.40);
    }
    .header-icon svg {
      width: 20px;
      height: 20px;
      fill: #fff;
    }
    .header-text h2 {
      font-size: 15px;
      margin: 0;
      font-weight: 650;
      letter-spacing: 0.2px;
      color: var(--vscode-foreground);
    }
    .header-text p {
      font-size: 11px;
      margin: 3px 0 0;
      color: var(--vscode-descriptionForeground);
    }

    /* Cards */
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 14px;
      margin-bottom: 12px;
      box-shadow: var(--shadow-sm);
      transition: border-color 0.15s ease, box-shadow 0.2s ease;
    }
    .card:hover {
      border-color: var(--vscode-focusBorder, var(--card-border));
      box-shadow: var(--shadow-md);
    }
    .card-title {
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.6px;
      color: var(--vscode-descriptionForeground);
      margin: 0 0 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .card-title .step {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 18px;
      height: 18px;
      border-radius: 6px;
      background: linear-gradient(135deg, var(--brand-1), var(--brand-2));
      color: #fff;
      font-size: 10px;
      font-weight: 700;
      flex-shrink: 0;
      box-shadow: 0 2px 6px rgba(79,140,255,0.35);
    }

    /* Fields */
    .field {
      margin-bottom: 12px;
    }
    .field:last-child {
      margin-bottom: 0;
    }
    label.field-label {
      display: block;
      font-size: 12px;
      margin-bottom: 5px;
      color: var(--vscode-foreground);
      font-weight: 500;
    }
    input[type="text"], input[type="password"] {
      width: 100%;
      padding: 6px 10px;
      background: var(--vscode-input-background);
      color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, transparent);
      border-radius: 4px;
      font-size: 12px;
      outline: none;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }
    input[type="text"]:focus, input[type="password"]:focus {
      border-color: var(--vscode-focusBorder);
      box-shadow: 0 0 0 1px var(--vscode-focusBorder);
    }
    input::placeholder {
      color: var(--vscode-input-placeholderForeground, var(--vscode-descriptionForeground));
      opacity: 0.7;
    }
    .btn-row {
      display: flex;
      gap: 6px;
      align-items: center;
    }
    .btn-row input { flex: 1; }

    /* Buttons */
    button {
      padding: 6px 12px;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border: none;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
      transition: background 0.15s ease, transform 0.1s ease;
      font-weight: 500;
    }
    button:hover {
      background: var(--vscode-button-hoverBackground);
    }
    button:active {
      transform: scale(0.97);
    }
    button.secondary {
      background: var(--vscode-button-secondaryBackground);
      color: var(--vscode-button-secondaryForeground);
      min-width: 32px;
    }
    button.secondary:hover {
      background: var(--vscode-button-secondaryHoverBackground);
    }

    /* Skills */
    .skill-item {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 8px 10px;
      margin-bottom: 6px;
      border-radius: 4px;
      cursor: pointer;
      transition: background 0.12s ease;
      border: 1px solid transparent;
    }
    .skill-item:last-child {
      margin-bottom: 0;
    }
    .skill-item:hover {
      background: var(--vscode-list-hoverBackground, rgba(128,128,128,0.08));
    }
    .skill-item:has(input:checked) {
      background: linear-gradient(135deg, rgba(79,140,255,0.12), rgba(138,92,255,0.08));
      border-color: rgba(79,140,255,0.32);
    }
    .skill-item input[type="checkbox"] {
      margin-top: 2px;
      accent-color: var(--accent);
      width: 14px;
      height: 14px;
      flex-shrink: 0;
    }
    .skill-info {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .skill-label {
      font-weight: 500;
      font-size: 12px;
      color: var(--vscode-foreground);
    }
    .skill-desc {
      font-size: 11px;
      color: var(--vscode-descriptionForeground);
      line-height: 1.35;
    }

    /* Generate button */
    .generate-btn {
      width: 100%;
      padding: 11px 16px;
      font-size: 13px;
      font-weight: 650;
      margin-top: 8px;
      border-radius: 8px;
      letter-spacing: 0.3px;
      color: #fff;
      background: linear-gradient(135deg, var(--brand-1), var(--brand-2));
      box-shadow: 0 4px 14px rgba(79,140,255,0.35);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      transition: filter 0.15s ease, box-shadow 0.2s ease, transform 0.1s ease;
    }
    .generate-btn::before {
      content: '⚡';
    }
    .generate-btn:hover {
      filter: brightness(1.08);
      background: linear-gradient(135deg, var(--brand-1), var(--brand-2));
      box-shadow: 0 6px 22px rgba(79,140,255,0.55);
    }
    .generate-btn:active {
      transform: translateY(1px) scale(0.99);
    }
    .generate-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    /* Status */
    .status {
      margin-top: 12px;
      padding: 10px 12px;
      border-radius: 5px;
      font-size: 12px;
      display: none;
      line-height: 1.4;
      animation: fadeIn 0.2s ease;
    }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .status.success {
      display: block;
      background: var(--vscode-inputValidation-infoBackground, rgba(0,100,0,0.1));
      border: 1px solid var(--vscode-inputValidation-infoBorder, #2ea043);
      color: var(--vscode-foreground);
    }
    .status.error {
      display: block;
      background: var(--vscode-inputValidation-errorBackground, rgba(100,0,0,0.1));
      border: 1px solid var(--vscode-inputValidation-errorBorder, #f85149);
      color: var(--vscode-foreground);
    }

    /* Divider */
    .divider {
      height: 1px;
      background: var(--card-border);
      margin: 14px 0;
    }

    /* Footer */
    .footer {
      margin-top: 16px;
      padding-top: 12px;
      border-top: 1px solid var(--card-border);
      font-size: 10.5px;
      color: var(--vscode-descriptionForeground);
      text-align: center;
      line-height: 1.5;
      opacity: 0.85;
    }

    /* MCP tools reference */
    .tools-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
    }
    .tool-item {
      display: flex;
      align-items: flex-start;
      gap: 8px;
      padding: 6px 8px;
      border-radius: 4px;
      font-size: 11px;
      line-height: 1.35;
    }
    .tool-item:hover {
      background: var(--vscode-list-hoverBackground, rgba(128,128,128,0.08));
    }
    .tool-name {
      font-family: var(--vscode-editor-font-family, monospace);
      font-size: 11px;
      color: var(--vscode-textLink-foreground, #3794ff);
      white-space: nowrap;
      flex-shrink: 0;
      min-width: 110px;
    }
    .tool-desc {
      color: var(--vscode-descriptionForeground);
    }
    .server-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border-radius: 10px;
      font-size: 11px;
      font-weight: 500;
      margin-bottom: 8px;
      background: rgba(128, 128, 128, 0.1);
      color: var(--vscode-descriptionForeground);
      border: 1px solid var(--card-border);
    }
    .server-badge::before {
      content: '';
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: currentColor;
    }
    .mcp-section {
      margin-bottom: 12px;
    }
    .mcp-section:last-child {
      margin-bottom: 0;
    }
    .mcp-section-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--vscode-foreground);
      margin-bottom: 6px;
    }
    .card.collapsed .card-body {
      display: none;
    }
    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      cursor: pointer;
    }
    .card-header .toggle-icon {
      font-size: 10px;
      color: var(--vscode-descriptionForeground);
      transition: transform 0.15s ease;
    }
    .card.collapsed .toggle-icon {
      transform: rotate(-90deg);
    }
  </style>
</head>
<body>
  <div class="header">
    <div class="header-icon">
      <svg viewBox="0 0 16 16"><path d="M8 1l2 4.5L15 6l-3.5 3.5L12.5 15 8 12.5 3.5 15l1-5.5L1 6l5-0.5z"/></svg>
    </div>
    <div class="header-text">
      <h2>AURIX AI Configurator</h2>
      <p>Configure Copilot for your AURIX project</p>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><span class="step">1</span>Project Settings</div>

    <div class="field">
      <label class="field-label">Target Device / Board</label>
      <div class="btn-row">
        <input type="text" id="device" placeholder="e.g. KIT_A2G_TC375_LITE" />
        <button class="secondary" id="btnSelectDevice" title="Browse devices">…</button>
      </div>
    </div>

    <div class="field">
      <label class="field-label">IDE Path</label>
      <div class="btn-row">
        <input type="text" id="idePath" placeholder="C:\\Infineon\\ide" />
        <button class="secondary" id="btnSelectIde" title="Browse folders">…</button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-title"><span class="step">2</span>Skills</div>
    ${skillCheckboxes}
  </div>

  <div class="card" id="mcpCard">
    <div class="card-header" id="mcpToggle">
      <div class="card-title" style="margin-bottom:0"><span class="step">3</span>MCP Servers &amp; Tools</div>
      <span class="toggle-icon">▼</span>
    </div>
    <div class="card-body">
      <div class="mcp-section">
        <div class="server-badge">Registered server: aurix-mcp-server</div>
        <div class="tools-grid">
          <div class="tool-item">
            <span class="tool-name">ads.create_project</span>
            <span class="tool-desc">Create project skeleton (iLLD + Makefile + linker)</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">build.run</span>
            <span class="tool-desc">Build project (auto-PATHs toolchain)</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">flash.program</span>
            <span class="tool-desc">Flash .elf/.hex to target board</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">examples.search</span>
            <span class="tool-desc">Search official iLLD examples</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">examples.read_source</span>
            <span class="tool-desc">Read example source files</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">examples.import</span>
            <span class="tool-desc">Import example into workspace</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">illd.provision</span>
            <span class="tool-desc">Install/refresh iLLD libraries</span>
          </div>
          <div class="tool-item">
            <span class="tool-name">project.scan</span>
            <span class="tool-desc">Inspect workspace structure</span>
          </div>
        </div>
      </div>
      <p style="font-size:11px; color:var(--vscode-descriptionForeground); margin:10px 0 0; line-height:1.4;">
        The extension registers this server. In Copilot Chat, open
        <strong>Configure Tools</strong> and enable <code>aurix-mcp-server</code>.
      </p>
    </div>
  </div>

  <button class="generate-btn" id="btnGenerate">Generate Copilot Config</button>

  <div class="status" id="status"></div>

  <div class="footer">AURIX™ AI Agent · configures GitHub Copilot for embedded AURIX development</div>

  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();

    const deviceInput = document.getElementById('device');
    const idePathInput = document.getElementById('idePath');
    const statusEl = document.getElementById('status');

    document.getElementById('btnSelectDevice').addEventListener('click', () => {
      vscode.postMessage({ type: 'selectDevice' });
    });
    document.getElementById('btnSelectIde').addEventListener('click', () => {
      vscode.postMessage({ type: 'selectIdePath' });
    });

    document.getElementById('btnGenerate').addEventListener('click', () => {
      const skills = Array.from(document.querySelectorAll('input[name="skill"]:checked'))
        .map(el => el.value);
      vscode.postMessage({
        type: 'generate',
        config: {
          device: deviceInput.value.trim(),
          idePath: idePathInput.value.trim(),
          skills,
        },
      });
    });

    window.addEventListener('message', (event) => {
      const msg = event.data;
      if (msg.type === 'setState') {
        deviceInput.value = msg.state.device || '';
        idePathInput.value = msg.state.idePath || '';
        // Update skill checkboxes
        document.querySelectorAll('input[name="skill"]').forEach(el => {
          el.checked = (msg.state.skills || []).includes(el.value);
        });
      } else if (msg.type === 'generateResult') {
        statusEl.className = 'status ' + (msg.success ? 'success' : 'error');
        statusEl.textContent = msg.success
          ? '✓ Generated: ' + msg.filesWritten.join(', ')
          : '✗ Errors: ' + msg.errors.join('; ');
      }
    });

    // MCP card toggle
    document.getElementById('mcpToggle').addEventListener('click', () => {
      document.getElementById('mcpCard').classList.toggle('collapsed');
    });

    // Request initial state
    vscode.postMessage({ type: 'requestState' });
  </script>
</body>
</html>`;
  }
}

function getNonce(): string {
  let text = "";
  const possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) {
    text += possible.charAt(Math.floor(Math.random() * possible.length));
  }
  return text;
}
