import React, { useState, useCallback, useContext } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { MessengerContext } from "../context/AurixMessenger";

interface CodeBlockProps {
  language?: string;
  children: string;
}

/** Render a single diff line with +/- coloring */
function DiffLine({ line }: { line: string }) {
  let cls = "diff-line";
  if (/^\+(?!\+\+)/.test(line)) cls += " diff-add";
  else if (/^-(?!--)/.test(line)) cls += " diff-remove";
  else if (/^@@/.test(line)) cls += " diff-hunk";
  return <div className={cls}>{line}</div>;
}

/** Detect if code looks like a shell/terminal command */
function isTerminalCommand(lang: string, code: string): boolean {
  const termLangs = ["bash", "sh", "shell", "zsh", "powershell", "ps1", "cmd", "bat", "terminal", "console"];
  if (termLangs.includes(lang.toLowerCase())) return true;
  // Heuristic: single-line starting with $ or > or common commands
  const trimmed = code.trim();
  if (!trimmed.includes("\n") && /^[$>]\s/.test(trimmed)) return true;
  if (!trimmed.includes("\n") && /^(make|gcc|tricore|flash|npm|pip|cd|ls|dir|cat)\b/.test(trimmed)) return true;
  return false;
}

const CodeBlock: React.FC<CodeBlockProps> = ({ language, children }) => {
  const messenger = useContext(MessengerContext);
  const [copied, setCopied] = useState(false);
  const [applied, setApplied] = useState(false);
  const [inserted, setInserted] = useState(false);
  const [ran, setRan] = useState(false);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(children).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  }, [children]);

  const lang = language?.replace(/^language-/, "") || "";

  const handleApply = useCallback(() => {
    messenger.post("ide/applyCode", { code: children, language: lang });
    setApplied(true);
    setTimeout(() => setApplied(false), 2500);
  }, [children, lang, messenger]);

  const handleInsert = useCallback(() => {
    messenger.post("ide/insertAtCursor", { code: children });
    setInserted(true);
    setTimeout(() => setInserted(false), 2500);
  }, [children, messenger]);

  const handleRunInTerminal = useCallback(() => {
    // Strip leading $ or > prompt markers
    const command = children.trim().replace(/^[$>]\s*/, "");
    messenger.post("ide/runInTerminal", { command });
    setRan(true);
    setTimeout(() => setRan(false), 2500);
  }, [children, messenger]);

  const isDiff = lang === "diff" || lang === "patch";
  const isTerminal = !isDiff && isTerminalCommand(lang, children);

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="lang-label">{lang || "text"}</span>
        <div className="flex items-center gap-1">
          {isTerminal && (
            <button
              className={`code-action-btn ${ran ? "applied" : ""}`}
              onClick={handleRunInTerminal}
              title="Run in terminal"
            >
              {ran ? "✓ Ran" : "▶ Run"}
            </button>
          )}
          {!isDiff && !isTerminal && (
            <>
              <button
                className={`code-action-btn ${inserted ? "applied" : ""}`}
                onClick={handleInsert}
                title="Insert at cursor"
              >
                {inserted ? "✓ Inserted" : "Insert"}
              </button>
              <button
                className={`code-action-btn ${applied ? "applied" : ""}`}
                onClick={handleApply}
                title="Apply to active editor"
              >
                {applied ? "✓ Applied" : "Apply"}
              </button>
            </>
          )}
          <button
            className={`copy-btn ${copied ? "copied" : ""}`}
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            {copied ? "✓ Copied" : "Copy"}
          </button>
        </div>
      </div>
      {isDiff ? (
        <div className="diff-block">
          {children.split("\n").map((line, i) => (
            <DiffLine key={i} line={line} />
          ))}
        </div>
      ) : (
        <SyntaxHighlighter
          language={lang || "text"}
          style={vscDarkPlus}
          customStyle={{
            margin: 0,
            padding: "10px 14px",
            background: "transparent",
            fontSize: "inherit",
            lineHeight: "1.5",
          }}
          codeTagProps={{
            style: {
              fontFamily: "var(--vscode-editor-font-family, 'Cascadia Code', 'Fira Code', monospace)",
              fontSize: "var(--vscode-editor-font-size, 13px)",
            },
          }}
        >
          {children}
        </SyntaxHighlighter>
      )}
    </div>
  );
};

export default CodeBlock;
