/**
 * CodeDiffCard — Displays file diffs for write_code tool calls with accept/reject.
 * Inspired by Continue's FindAndReplaceDisplay pattern.
 */

import { useState } from "react";
import type { FileDiff } from "../types";
import { FileIcon } from "./FileIcon";

interface DiffLine {
  type: "added" | "removed" | "context";
  content: string;
  lineNum?: number;
}

function computeDiffLines(original: string, proposed: string): DiffLine[] {
  const oldLines = original.split("\n");
  const newLines = proposed.split("\n");
  const result: DiffLine[] = [];

  // Simple LCS-based diff
  const maxLen = Math.max(oldLines.length, newLines.length);
  let oi = 0;
  let ni = 0;

  while (oi < oldLines.length || ni < newLines.length) {
    if (oi < oldLines.length && ni < newLines.length && oldLines[oi] === newLines[ni]) {
      result.push({ type: "context", content: oldLines[oi], lineNum: ni + 1 });
      oi++;
      ni++;
    } else {
      // Look ahead for a matching line
      let foundOld = -1;
      let foundNew = -1;
      const lookAhead = Math.min(20, maxLen);

      for (let k = 1; k <= lookAhead; k++) {
        if (ni + k < newLines.length && oi < oldLines.length && oldLines[oi] === newLines[ni + k]) {
          foundNew = ni + k;
          break;
        }
      }
      for (let k = 1; k <= lookAhead; k++) {
        if (oi + k < oldLines.length && ni < newLines.length && oldLines[oi + k] === newLines[ni]) {
          foundOld = oi + k;
          break;
        }
      }

      if (foundNew >= 0 && (foundOld < 0 || foundNew - ni <= foundOld - oi)) {
        // Added lines
        while (ni < foundNew) {
          result.push({ type: "added", content: newLines[ni], lineNum: ni + 1 });
          ni++;
        }
      } else if (foundOld >= 0) {
        // Removed lines
        while (oi < foundOld) {
          result.push({ type: "removed", content: oldLines[oi] });
          oi++;
        }
      } else {
        // No match found — treat as replace
        if (oi < oldLines.length) {
          result.push({ type: "removed", content: oldLines[oi] });
          oi++;
        }
        if (ni < newLines.length) {
          result.push({ type: "added", content: newLines[ni], lineNum: ni + 1 });
          ni++;
        }
      }
    }
  }

  return result;
}

function DiffStats({ lines }: { lines: DiffLine[] }) {
  const added = lines.filter((l) => l.type === "added").length;
  const removed = lines.filter((l) => l.type === "removed").length;
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-mono">
      {added > 0 && <span style={{ color: "#4ec9b0" }}>+{added}</span>}
      {removed > 0 && <span style={{ color: "#f48771" }}>−{removed}</span>}
    </span>
  );
}

const MAX_CONTEXT_LINES = 3;

function DiffView({ original, proposed }: { original: string; proposed: string }) {
  const lines = computeDiffLines(original, proposed);

  // Collapse long context sections
  const rendered: Array<DiffLine | { type: "ellipsis"; count: number }> = [];
  let contextRun: DiffLine[] = [];

  const flushContext = () => {
    if (contextRun.length <= MAX_CONTEXT_LINES * 2 + 1) {
      rendered.push(...contextRun);
    } else {
      rendered.push(...contextRun.slice(0, MAX_CONTEXT_LINES));
      rendered.push({ type: "ellipsis", count: contextRun.length - MAX_CONTEXT_LINES * 2 });
      rendered.push(...contextRun.slice(-MAX_CONTEXT_LINES));
    }
    contextRun = [];
  };

  for (const line of lines) {
    if (line.type === "context") {
      contextRun.push(line);
    } else {
      flushContext();
      rendered.push(line);
    }
  }
  flushContext();

  return (
    <div className="text-xs font-mono overflow-x-auto" style={{ fontFamily: "var(--vscode-editor-font-family, monospace)" }}>
      <DiffStats lines={lines} />
      <div className="mt-1">
        {rendered.map((item, i) => {
          if ("count" in item) {
            return (
              <div
                key={`e-${i}`}
                className="px-2 py-0.5 text-center text-[10px]"
                style={{ color: "var(--vscode-descriptionForeground)", background: "rgba(255,255,255,0.02)" }}
              >
                ⋯ {item.count} unchanged lines ⋯
              </div>
            );
          }
          const bg =
            item.type === "added"
              ? "rgba(78,201,176,0.10)"
              : item.type === "removed"
                ? "rgba(244,135,113,0.10)"
                : "transparent";
          const borderColor =
            item.type === "added"
              ? "rgba(78,201,176,0.5)"
              : item.type === "removed"
                ? "rgba(244,135,113,0.5)"
                : "transparent";
          const prefix = item.type === "added" ? "+" : item.type === "removed" ? "−" : " ";
          return (
            <div
              key={i}
              className="flex"
              style={{ background: bg, borderLeft: `3px solid ${borderColor}` }}
            >
              <span
                className="w-5 text-center flex-shrink-0 select-none"
                style={{ color: item.type === "added" ? "#4ec9b0" : item.type === "removed" ? "#f48771" : "var(--vscode-descriptionForeground)" }}
              >
                {prefix}
              </span>
              <span className="px-1 whitespace-pre" style={{ color: "var(--vscode-editor-foreground)" }}>
                {item.content}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface CodeDiffCardProps {
  toolCallId: string;
  diffs: FileDiff[];
  approved?: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

export function CodeDiffCard({ toolCallId, diffs, approved, onApprove, onReject }: CodeDiffCardProps) {
  const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set(diffs.map((d) => d.path)));
  const isPending = approved === undefined;

  const toggleFile = (path: string) => {
    setExpandedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(path)) { next.delete(path); } else { next.add(path); }
      return next;
    });
  };

  const actionLabel = (a: string) => a === "delete" ? "Delete" : a === "replace" ? "Modify" : "Create/Overwrite";

  return (
    <div
      className="rounded-lg text-sm overflow-hidden"
      style={{
        border: `1px solid ${isPending ? "var(--aurix-accent-dim, #006d99)" : "var(--vscode-panel-border, #3c3c3c)"}`,
        background: "var(--vscode-editor-background, #1e1e1e)",
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2"
        style={{
          background: isPending ? "rgba(0,161,224,0.07)" : "rgba(255,255,255,0.02)",
          borderBottom: "1px solid var(--vscode-panel-border, #3c3c3c)",
        }}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(255,255,255,0.06)" }}>
            ✏️
          </span>
          <span className="font-semibold" style={{ color: "var(--vscode-editor-foreground)" }}>
            Code Changes
          </span>
          <span className="text-xs" style={{ color: "var(--vscode-descriptionForeground)" }}>
            {diffs.length} file{diffs.length !== 1 ? "s" : ""}
          </span>
        </div>

        <div className="flex items-center gap-2">
          {isPending && (
            <>
              <button
                onClick={() => onApprove(toolCallId)}
                className="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
                style={{ background: "rgba(78,201,176,0.15)", color: "#4ec9b0", border: "1px solid rgba(78,201,176,0.3)" }}
                title="Accept All (Ctrl+Shift+Enter)"
              >
                ✓ Accept All
              </button>
              <button
                onClick={() => onReject(toolCallId)}
                className="rounded-md px-3 py-1.5 text-xs font-medium transition-colors"
                style={{ background: "rgba(244,135,113,0.12)", color: "#f48771", border: "1px solid rgba(244,135,113,0.3)" }}
                title="Reject (Ctrl+Shift+Backspace)"
              >
                ✗ Reject
              </button>
            </>
          )}
          {approved === true && (
            <span className="text-xs font-medium" style={{ color: "#4ec9b0" }}>✓ Applied</span>
          )}
          {approved === false && (
            <span className="text-xs font-medium" style={{ color: "#f48771" }}>✗ Rejected</span>
          )}
        </div>
      </div>

      {/* File diffs */}
      {diffs.map((diff) => (
        <div key={diff.path} className="border-t" style={{ borderColor: "var(--vscode-panel-border, #3c3c3c)" }}>
          {/* File header */}
          <button
            onClick={() => toggleFile(diff.path)}
            className="w-full text-left px-3 py-1.5 flex items-center gap-2 hover:opacity-80"
            style={{ background: "rgba(255,255,255,0.02)", border: "none", cursor: "pointer" }}
          >
            <span
              className="text-[10px]"
              style={{
                transform: expandedFiles.has(diff.path) ? "rotate(90deg)" : "none",
                transition: "transform 0.15s",
                display: "inline-block",
                color: "var(--vscode-descriptionForeground)",
              }}
            >
              ▶
            </span>
            <FileIcon filename={diff.path} size={14} />
            <span className="text-xs font-mono" style={{ color: "var(--vscode-editor-foreground)" }}>
              {diff.path}
            </span>
            <span
              className="text-[10px] px-1.5 py-0.5 rounded"
              style={{
                background: diff.action === "delete" ? "rgba(244,135,113,0.12)" : diff.action === "replace" ? "rgba(78,201,176,0.08)" : "rgba(0,161,224,0.08)",
                color: diff.action === "delete" ? "#f48771" : diff.action === "replace" ? "#4ec9b0" : "#00a1e0",
              }}
            >
              {actionLabel(diff.action)}
            </span>
          </button>

          {/* Diff content */}
          {expandedFiles.has(diff.path) && (
            <div className="px-2 pb-2 max-h-[400px] overflow-auto">
              {diff.action === "delete" ? (
                <div className="text-xs px-2 py-1" style={{ color: "#f48771" }}>
                  File will be deleted
                </div>
              ) : (
                <DiffView original={diff.original} proposed={diff.proposed} />
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
