/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        "vsc-bg": "var(--vscode-sideBar-background, #1e1e1e)",
        "vsc-fg": "var(--vscode-sideBar-foreground, #e6e6e6)",
        "vsc-editor-bg": "var(--vscode-editor-background, #1e1e1e)",
        "vsc-editor-fg": "var(--vscode-editor-foreground, #e6e6e6)",
        "vsc-input-bg": "var(--vscode-input-background, #3c3c3c)",
        "vsc-input-fg": "var(--vscode-input-foreground, #e6e6e6)",
        "vsc-input-border": "var(--vscode-input-border, #3c3c3c)",
        "vsc-button-bg": "var(--vscode-button-background, #0e639c)",
        "vsc-button-fg": "var(--vscode-button-foreground, #ffffff)",
        "vsc-button-hover": "var(--vscode-button-hoverBackground, #1177bb)",
        "vsc-border": "var(--vscode-panel-border, #3c3c3c)",
        "vsc-focus": "var(--vscode-focusBorder, #007fd4)",
        "vsc-badge-bg": "var(--vscode-badge-background, #4d4d4d)",
        "vsc-badge-fg": "var(--vscode-badge-foreground, #ffffff)",
        "vsc-error": "var(--vscode-errorForeground, #f48771)",
        "vsc-warning": "var(--vscode-editorWarning-foreground, #cca700)",
        "vsc-link": "var(--vscode-textLink-foreground, #3794ff)",
      },
    },
  },
  plugins: [],
  corePlugins: {
    preflight: false,
  },
};
