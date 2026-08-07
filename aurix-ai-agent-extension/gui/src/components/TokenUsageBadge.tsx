/**
 * TokenUsageBadge — Compact token usage display shown after each turn.
 * Accumulates per-turn totals and shows a collapsible breakdown.
 */

import { useState } from "react";
import type { TokenUsage } from "../types";

interface TokenUsageBadgeProps {
  /** All usage events collected for the current turn. */
  usages: TokenUsage[];
}

function formatNum(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "k";
  return String(n);
}

function formatDuration(ms: number): string {
  if (ms >= 1_000) return (ms / 1_000).toFixed(1) + "s";
  return Math.round(ms) + "ms";
}

export function TokenUsageBadge({ usages }: TokenUsageBadgeProps) {
  const [expanded, setExpanded] = useState(false);

  if (usages.length === 0) return null;

  // Aggregate totals
  const totals = usages.reduce(
    (acc, u) => ({
      input: acc.input + u.inputTokens,
      output: acc.output + u.outputTokens,
      cacheRead: acc.cacheRead + (u.cacheReadTokens ?? 0),
      cacheWrite: acc.cacheWrite + (u.cacheWriteTokens ?? 0),
      reasoning: acc.reasoning + (u.reasoningTokens ?? 0),
      duration: acc.duration + (u.duration ?? 0),
    }),
    { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, reasoning: 0, duration: 0 },
  );

  const totalTokens = totals.input + totals.output;
  const models = [...new Set(usages.map((u) => u.model).filter(Boolean))];
  const modelLabel = models.length === 1 ? models[0] : `${models.length} models`;
  const calls = usages.length;

  return (
    <div className="token-usage-badge">
      <button
        type="button"
        className="token-usage-summary"
        onClick={() => setExpanded((v) => !v)}
        title="Click to see token breakdown"
      >
        <span className="token-usage-icon">⚡</span>
        <span className="token-usage-total">{formatNum(totalTokens)} tokens</span>
        <span className="token-usage-sep">·</span>
        <span className="token-usage-detail">
          ↑{formatNum(totals.input)} ↓{formatNum(totals.output)}
        </span>
        {totals.duration > 0 && (
          <>
            <span className="token-usage-sep">·</span>
            <span className="token-usage-detail">{formatDuration(totals.duration)}</span>
          </>
        )}
        <span className="token-usage-chevron">{expanded ? "▾" : "▸"}</span>
      </button>

      {expanded && (
        <div className="token-usage-breakdown">
          <div className="token-usage-row">
            <span className="token-usage-label">Model</span>
            <span className="token-usage-value">{modelLabel}</span>
          </div>
          <div className="token-usage-row">
            <span className="token-usage-label">API calls</span>
            <span className="token-usage-value">{calls}</span>
          </div>
          <div className="token-usage-row">
            <span className="token-usage-label">Input tokens</span>
            <span className="token-usage-value">{totals.input.toLocaleString()}</span>
          </div>
          <div className="token-usage-row">
            <span className="token-usage-label">Output tokens</span>
            <span className="token-usage-value">{totals.output.toLocaleString()}</span>
          </div>
          {totals.cacheRead > 0 && (
            <div className="token-usage-row">
              <span className="token-usage-label">Cache read</span>
              <span className="token-usage-value hit">{totals.cacheRead.toLocaleString()}</span>
            </div>
          )}
          {totals.cacheWrite > 0 && (
            <div className="token-usage-row">
              <span className="token-usage-label">Cache write</span>
              <span className="token-usage-value">{totals.cacheWrite.toLocaleString()}</span>
            </div>
          )}
          {totals.reasoning > 0 && (
            <div className="token-usage-row">
              <span className="token-usage-label">Reasoning</span>
              <span className="token-usage-value">{totals.reasoning.toLocaleString()}</span>
            </div>
          )}
          {totals.duration > 0 && (
            <div className="token-usage-row">
              <span className="token-usage-label">Duration</span>
              <span className="token-usage-value">{formatDuration(totals.duration)}</span>
            </div>
          )}

          {/* Visual bar: input vs output proportion */}
          <div className="token-usage-bar-wrap">
            <div
              className="token-usage-bar-input"
              style={{ width: `${totalTokens > 0 ? (totals.input / totalTokens) * 100 : 50}%` }}
            />
            <div
              className="token-usage-bar-output"
              style={{ width: `${totalTokens > 0 ? (totals.output / totalTokens) * 100 : 50}%` }}
            />
          </div>
          <div className="token-usage-bar-legend">
            <span className="token-usage-legend-item"><span className="legend-dot input" /> Input</span>
            <span className="token-usage-legend-item"><span className="legend-dot output" /> Output</span>
          </div>
        </div>
      )}
    </div>
  );
}
