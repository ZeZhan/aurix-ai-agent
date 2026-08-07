/**
 * ToolCallCard — Displays a pending tool call with specialized rendering
 * based on tool name (build, flash, search_*, read_file, etc.)
 */

import { useState, useContext } from "react";
import { MessengerContext } from "../context/AurixMessenger";
import type { ToolCallItem } from "../types";
import { TerminalOutput } from "./TerminalOutput";
import { FileIcon } from "./FileIcon";

interface ToolCallCardProps {
  toolCall: ToolCallItem;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}

/** Tool icon/label mapping */
const TOOL_META: Record<string, { icon: string; label: string; color: string }> = {
  build:                { icon: "🔨", label: "Build Project",        color: "#cca700" },
  flash:                { icon: "⚡", label: "Flash to Board",       color: "#f97316" },
  debug_start:          { icon: "🐛", label: "Start Debug",         color: "#4ec9b0" },
  debug_stop:           { icon: "⏹",  label: "Stop Debug",          color: "#f48771" },
  debug_pause:          { icon: "⏸",  label: "Pause Target",        color: "#cca700" },
  debug_resume:         { icon: "▶",  label: "Resume Target",       color: "#4ec9b0" },
  search_docs:          { icon: "📖", label: "Search Docs",         color: "#3794ff" },
  search_examples:      { icon: "📦", label: "Search Examples",     color: "#3794ff" },
  search_device:        { icon: "🔍", label: "Search Device",       color: "#3794ff" },
  read_file:            { icon: "📄", label: "Read File",           color: "#888" },
  analyse_code:         { icon: "🔬", label: "Analyse Code",        color: "#888" },
  write_code:           { icon: "✏️", label: "Write Code",          color: "#4ec9b0" },
  generate_makefile:    { icon: "📋", label: "Generate Makefile",   color: "#cca700" },
  create_device_project:{ icon: "🏗",  label: "Create Project",     color: "#f97316" },
  provision_illd:       { icon: "📦", label: "Provision iLLD",      color: "#3794ff" },
  import_example:       { icon: "📥", label: "Import Example",      color: "#4ec9b0" },
  read_example_source:  { icon: "📖", label: "Read Example",        color: "#3794ff" },
  list_examples:        { icon: "📋", label: "List Examples",       color: "#3794ff" },
};

function getToolMeta(name: string) {
  return TOOL_META[name] ?? { icon: "🔧", label: name, color: "var(--vscode-descriptionForeground)" };
}

/** Render build/flash-specific summary from result */
function BuildSummary({ result, isError }: { result: string; isError?: boolean }) {
  // Extract key metrics from build output
  const lines = result.split("\n");
  const errorLines = lines.filter((l) => /error[:\s]/i.test(l) && !/0 error/i.test(l)).slice(0, 5);
  const warningCount = (result.match(/(\d+)\s+warning/i)?.[1]) || "0";
  const sizeMatch = result.match(/text\s+data\s+bss[\s\S]*?(\d+)\s+(\d+)\s+(\d+)/);

  return (
    <div className="px-3 py-2 text-xs" style={{ borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)" }}>
      {isError && errorLines.length > 0 && (
        <div className="mb-1.5">
          <span className="font-semibold" style={{ color: "#f48771" }}>Errors:</span>
          <pre className="mt-0.5 whitespace-pre-wrap" style={{ color: "#f48771", fontFamily: "var(--vscode-editor-font-family, monospace)" }}>
            {errorLines.join("\n")}
          </pre>
        </div>
      )}
      {!isError && sizeMatch && (
        <div className="flex gap-3" style={{ color: "var(--vscode-descriptionForeground)" }}>
          <span>text: <b style={{ color: "#4ec9b0" }}>{Number(sizeMatch[1]).toLocaleString()}</b></span>
          <span>data: <b>{Number(sizeMatch[2]).toLocaleString()}</b></span>
          <span>bss: <b>{Number(sizeMatch[3]).toLocaleString()}</b></span>
          <span>warnings: <b style={{ color: Number(warningCount) > 0 ? "#cca700" : "inherit" }}>{warningCount}</b></span>
        </div>
      )}
      {!isError && !sizeMatch && (
        <span style={{ color: "#4ec9b0" }}>✓ Success</span>
      )}
    </div>
  );
}

/** Render file path args nicely */
function FileArgsPreview({ args }: { args: Record<string, any> }) {
  const path = args.path || args.file;
  const query = args.query;
  const device = args.device;
  const files = args.files;
  return (
    <div className="flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: "var(--vscode-descriptionForeground)" }}>
      {path && (
        <span className="inline-flex items-center gap-1 font-mono px-1.5 py-0.5 rounded" style={{ background: "rgba(255,255,255,0.06)" }}>
          <FileIcon filename={path} size={12} />
          {path}
        </span>
      )}
      {query && <span className="italic">"{query}"</span>}
      {device && <span className="font-mono">[{device}]</span>}
      {files && Array.isArray(files) && (
        <span className="inline-flex items-center gap-1">
          {files.length <= 3 ? (
            files.map((f: string, i: number) => (
              <span key={i} className="inline-flex items-center gap-0.5 font-mono px-1 py-0.5 rounded" style={{ background: "rgba(255,255,255,0.06)" }}>
                <FileIcon filename={f} size={11} />
                {f.split("/").pop()}
              </span>
            ))
          ) : (
            <span>{files.length} files</span>
          )}
        </span>
      )}
    </div>
  );
}

export function ToolCallCard({ toolCall, onApprove, onReject }: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isPending = toolCall.approved === undefined;
  const meta = getToolMeta(toolCall.toolName);
  const isBuildLike = toolCall.toolName === "build" || toolCall.toolName === "flash";
  const isSearchLike = toolCall.toolName.startsWith("search_") || toolCall.toolName === "list_examples";
  const isReadOnly = isSearchLike || toolCall.toolName === "read_file" || toolCall.toolName === "analyse_code" || toolCall.toolName === "read_example_source";

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
          <span className="text-xs">{meta.icon}</span>
          <span className="font-semibold" style={{ color: "var(--vscode-editor-foreground)" }}>
            {meta.label}
          </span>
          {/* Inline args preview */}
          <FileArgsPreview args={toolCall.args} />
        </div>
        <div className="flex items-center gap-2">
          {isPending && !isReadOnly && (
            <>
              <button
                onClick={() => onApprove(toolCall.toolCallId)}
                className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
                style={{ background: "rgba(78,201,176,0.15)", color: "#4ec9b0", border: "1px solid rgba(78,201,176,0.3)" }}
              >
                ✓ Allow
              </button>
              <button
                onClick={() => onReject(toolCall.toolCallId)}
                className="rounded-md px-2.5 py-1 text-xs font-medium transition-colors"
                style={{ background: "rgba(244,135,113,0.12)", color: "#f48771", border: "1px solid rgba(244,135,113,0.3)" }}
              >
                ✗ Deny
              </button>
            </>
          )}
          {toolCall.approved === true && (
            <span className="text-xs font-medium" style={{ color: "#4ec9b0" }}>✓ Allowed</span>
          )}
          {toolCall.approved === false && (
            <span className="text-xs font-medium" style={{ color: "#f48771" }}>✗ Denied</span>
          )}
        </div>
      </div>

      {/* Toggle for raw args (only show for non-trivial args) */}
      {Object.keys(toolCall.args).length > 0 && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full text-left px-3 py-1.5 text-[11px] flex items-center gap-1"
          style={{ color: "var(--vscode-descriptionForeground, #888)", background: "transparent", border: "none", cursor: "pointer" }}
        >
          <span style={{ transform: expanded ? "rotate(90deg)" : "none", transition: "transform 0.15s", display: "inline-block" }}>▶</span>
          {expanded ? "Hide" : "Show"} arguments
        </button>
      )}

      {expanded && (
        <pre
          className="whitespace-pre-wrap text-xs px-3 pb-2 max-h-40 overflow-auto"
          style={{
            color: "var(--vscode-editor-foreground, #e6e6e6)",
            fontFamily: "var(--vscode-editor-font-family, monospace)",
          }}
        >
          {JSON.stringify(toolCall.args, null, 2)}
        </pre>
      )}

      {/* Result — ANSI-rendered terminal output for build/flash */}
      {toolCall.result && isBuildLike && (
        <div style={{ borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)" }}>
          <BuildSummary result={toolCall.result} isError={toolCall.isError} />
          <TerminalOutput
            text={toolCall.result}
            maxLines={12}
            status={toolCall.isError ? "error" : "done"}
            bordered={false}
          />
        </div>
      )}

      {/* ANSI-rendered result for other tools */}
      {toolCall.result && !isBuildLike && (
        <div style={{ borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)" }}>
          <TerminalOutput
            text={toolCall.result}
            maxLines={15}
            status={toolCall.isError ? "error" : "done"}
            bordered={false}
          />
        </div>
      )}
    </div>
  );
}
