/**
 * ActivityBadge — Shows an activity indicator (running, done, error)
 * with optional collapsible full output for build/flash results.
 */

import { useState } from "react";
import type { ActivityItem } from "../types";
import { TerminalOutput } from "./TerminalOutput";

const ICONS: Record<string, string> = {
  thinking: "🤔",
  reading: "📖",
  writing: "✏️",
  building: "🔨",
  flashing: "⚡",
  debugging: "🐛",
  searching: "🔍",
  status: "ℹ️",
};

export function ActivityBadge({ activity }: { activity: ActivityItem }) {
  const icon = ICONS[activity.type] ?? "⏳";
  const isDone = activity.state === "done";
  const isError = activity.state === "error";
  const isRunning = !isDone && !isError;
  const hasOutput = !!activity.fullOutput;
  const hasStreamingOutput = !!activity.streamingOutput;
  const isThinking = activity.type === "thinking" && isDone;
  const [expanded, setExpanded] = useState(false);
  // Auto-expand when streaming output arrives for running activities
  const showOutput = hasOutput || (isRunning && hasStreamingOutput);

  const borderColor = isError
    ? "var(--vscode-inputValidation-errorBorder, #f44747)"
    : "var(--vscode-panel-border, #3c3c3c)";

  // Thinking activities: show the reasoning text as a dim, wrapped block
  if (isThinking) {
    return (
      <div
        className="rounded-lg px-3 py-2 text-xs whitespace-pre-wrap"
        style={{
          background: "rgba(255,255,255,0.02)",
          border: "1px solid var(--vscode-panel-border, #2a2a2a)",
          color: "var(--vscode-descriptionForeground, #888)",
          lineHeight: "1.5",
        }}
      >
        <span style={{ opacity: 0.7 }}>💭 </span>
        {activity.message}
      </div>
    );
  }

  return (
    <div
      className="rounded-lg text-xs"
      style={{
        background: "rgba(255,255,255,0.03)",
        border: `1px solid ${borderColor}`,
        color: "var(--vscode-editor-foreground, #e6e6e6)",
      }}
    >
      <div
        className={`flex items-center gap-2.5 px-3 py-2 ${showOutput ? "cursor-pointer select-none" : ""}`}
        onClick={showOutput ? () => setExpanded(!expanded) : undefined}
      >
        {/* Spinner only for running */}
        {isRunning && (
          <svg className="animate-spin flex-shrink-0" width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="6" stroke="currentColor" strokeWidth="1.5" strokeDasharray="28" strokeDashoffset="8" strokeLinecap="round" opacity="0.6" />
          </svg>
        )}
        {isDone && <span className="flex-shrink-0">✅</span>}
        {isError && <span className="flex-shrink-0">❌</span>}
        <span>{icon}</span>
        <span className="font-medium">{activity.message}</span>
        {activity.detail && (
          <span style={{ color: "var(--vscode-descriptionForeground, #888)" }} className="truncate">
            {activity.detail}
          </span>
        )}
        {showOutput && (
          <span className="ml-auto flex-shrink-0" style={{ color: "var(--vscode-descriptionForeground, #888)" }}>
            {expanded ? "▲" : "▼"}
          </span>
        )}
      </div>
      {/* Streaming output (shown while running, auto-expanded) */}
      {isRunning && hasStreamingOutput && (
        <div style={{ borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)" }}>
          <TerminalOutput
            text={activity.streamingOutput!}
            maxLines={20}
            status="running"
            bordered={false}
          />
        </div>
      )}
      {/* Full output (shown when done/error, toggled by expand) */}
      {expanded && activity.fullOutput && !isRunning && (
        <div style={{ borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)" }}>
          <TerminalOutput
            text={activity.fullOutput}
            maxLines={20}
            status={isRunning ? "running" : isError ? "error" : "done"}
            bordered={false}
          />
        </div>
      )}
    </div>
  );
}
