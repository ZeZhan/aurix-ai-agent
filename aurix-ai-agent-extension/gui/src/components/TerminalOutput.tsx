/**
 * TerminalOutput — Renders terminal/build output with ANSI escape code coloring.
 * Inspired by Continue's UnifiedTerminal. Uses `anser` for ANSI parsing.
 */

import Anser, { type AnserJsonEntry } from "anser";
import { escapeCarriageReturn } from "escape-carriage";
import { useMemo, useState } from "react";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fixBackspace(txt: string): string {
  let tmp = txt;
  do {
    txt = tmp;
    tmp = txt.replace(/[^\n]\x08/gm, "");
  } while (tmp.length < txt.length);
  return txt;
}

function parseAnsi(input: string): AnserJsonEntry[] {
  return Anser.ansiToJson(escapeCarriageReturn(fixBackspace(input)), {
    json: true,
    remove_empty: true,
    use_classes: false,
  });
}

// ---------------------------------------------------------------------------
// AnsiLine — renders one ANSI-colored span
// ---------------------------------------------------------------------------

function AnsiSpan({ entry, idx }: { entry: AnserJsonEntry; idx: number }) {
  const style: React.CSSProperties = {};
  if (entry.bg) style.backgroundColor = `rgb(${entry.bg})`;
  if (entry.fg) style.color = `rgb(${entry.fg})`;
  if (entry.decoration) {
    switch (entry.decoration) {
      case "bold": style.fontWeight = "bold"; break;
      case "dim": style.opacity = 0.5; break;
      case "italic": style.fontStyle = "italic"; break;
      case "underline": style.textDecoration = "underline"; break;
      case "strikethrough": style.textDecoration = "line-through"; break;
    }
  }
  return <span key={idx} style={style}>{entry.content}</span>;
}

// ---------------------------------------------------------------------------
// TerminalOutput component
// ---------------------------------------------------------------------------

interface TerminalOutputProps {
  /** Raw terminal text (may contain ANSI escape codes). */
  text: string;
  /** Max lines to show before collapsing (default 15). 0 = unlimited. */
  maxLines?: number;
  /** Show status indicator. */
  status?: "running" | "done" | "error";
  /** Optional command that produced this output. */
  command?: string;
  /** If true the outer container has a border (standalone mode). Default true. */
  bordered?: boolean;
}

export function TerminalOutput({
  text,
  maxLines = 15,
  status,
  command,
  bordered = true,
}: TerminalOutputProps) {
  const [expanded, setExpanded] = useState(false);

  const { entries, totalLines, isTruncated, hiddenCount } = useMemo(() => {
    const all = parseAnsi(text);
    // Count newlines to estimate line count
    let lineCount = 1;
    for (const e of all) {
      for (const ch of e.content) {
        if (ch === "\n") lineCount++;
      }
    }

    if (maxLines > 0 && lineCount > maxLines && !expanded) {
      // Keep only the last `maxLines` lines worth of text
      const lines = text.split("\n");
      const tail = lines.slice(-maxLines).join("\n");
      return {
        entries: parseAnsi(tail),
        totalLines: lineCount,
        isTruncated: true,
        hiddenCount: lineCount - maxLines,
      };
    }
    return { entries: all, totalLines: lineCount, isTruncated: false, hiddenCount: 0 };
  }, [text, maxLines, expanded]);

  const statusColor =
    status === "running" ? "#4ec9b0"
    : status === "error" ? "#f48771"
    : status === "done" ? "#4ec9b0"
    : undefined;

  return (
    <div
      className="rounded-md overflow-hidden text-xs"
      style={{
        border: bordered ? "1px solid var(--vscode-panel-border, #3c3c3c)" : "none",
        background: "var(--vscode-terminal-background, var(--vscode-editor-background, #1e1e1e))",
      }}
    >
      {/* Optional header bar */}
      {(command || status) && (
        <div
          className="flex items-center gap-2 px-2.5 py-1.5"
          style={{
            borderBottom: "1px solid var(--vscode-panel-border, #3c3c3c)",
            background: "rgba(255,255,255,0.02)",
          }}
        >
          {status && (
            <span
              className="inline-block w-2 h-2 rounded-full flex-shrink-0"
              style={{
                background: statusColor,
                animation: status === "running" ? "pulse 1.5s infinite" : "none",
              }}
            />
          )}
          <span
            className="text-[11px] select-none"
            style={{ color: "var(--vscode-descriptionForeground, #888)" }}
          >
            Terminal
          </span>
          {command && (
            <code
              className="truncate ml-1"
              style={{
                color: "var(--vscode-terminal-foreground, var(--vscode-editor-foreground, #ccc))",
                fontFamily: "var(--vscode-editor-font-family, 'Cascadia Code', Consolas, monospace)",
                fontSize: "11px",
              }}
            >
              $ {command}
            </code>
          )}
        </div>
      )}

      {/* Expand indicator */}
      {isTruncated && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="w-full text-center py-1 text-[10px]"
          style={{
            background: "rgba(255,255,255,0.04)",
            color: "var(--vscode-descriptionForeground, #888)",
            border: "none",
            borderBottom: "1px solid var(--vscode-panel-border, #3c3c3c)",
            cursor: "pointer",
          }}
        >
          ↑ {hiddenCount} more lines — click to expand
        </button>
      )}
      {expanded && isTruncated && (
        <button
          onClick={() => setExpanded(false)}
          className="w-full text-center py-1 text-[10px]"
          style={{
            background: "rgba(255,255,255,0.04)",
            color: "var(--vscode-descriptionForeground, #888)",
            border: "none",
            borderBottom: "1px solid var(--vscode-panel-border, #3c3c3c)",
            cursor: "pointer",
          }}
        >
          ↑ Collapse
        </button>
      )}

      {/* Terminal body */}
      <pre
        className="m-0 overflow-x-auto"
        style={{
          padding: "8px 10px",
          fontFamily: "var(--vscode-editor-font-family, 'Cascadia Code', Consolas, monospace)",
          fontSize: "12px",
          lineHeight: "1.45",
          color: "var(--vscode-terminal-foreground, var(--vscode-editor-foreground, #ccc))",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          maxHeight: expanded ? "500px" : "300px",
          overflowY: "auto",
        }}
      >
        {entries.map((e, i) => (
          <AnsiSpan key={i} entry={e} idx={i} />
        ))}
        {status === "running" && (
          <span className="terminal-cursor">█</span>
        )}
      </pre>
    </div>
  );
}
