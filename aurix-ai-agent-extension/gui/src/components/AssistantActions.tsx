/**
 * AssistantActions — Hover toolbar shown beneath assistant messages.
 * Provides Copy, 👍, 👎.
 */

import { useCallback, useState } from "react";

interface AssistantActionsProps {
  messageId: string;
  content: string;
  feedback?: "up" | "down";
  onFeedback: (value: "up" | "down") => void;
}

export function AssistantActions({ content, feedback, onFeedback }: AssistantActionsProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }, [content]);

  return (
    <div className="assistant-actions" role="toolbar" aria-label="Message actions">
      <button
        type="button"
        className={`assistant-action-btn ${copied ? "copied" : ""}`}
        title="Copy message"
        onClick={handleCopy}
      >
        {copied ? "✓ Copied" : "📋 Copy"}
      </button>
      <button
        type="button"
        className={`assistant-action-btn ${feedback === "up" ? "active up" : ""}`}
        title="Helpful"
        aria-pressed={feedback === "up"}
        onClick={() => onFeedback("up")}
      >
        👍
      </button>
      <button
        type="button"
        className={`assistant-action-btn ${feedback === "down" ? "active down" : ""}`}
        title="Not helpful"
        aria-pressed={feedback === "down"}
        onClick={() => onFeedback("down")}
      >
        👎
      </button>
    </div>
  );
}
