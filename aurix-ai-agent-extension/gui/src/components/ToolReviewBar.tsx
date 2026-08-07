/**
 * ToolReviewBar — Sticky bar above the input that shows pending tool calls
 * count plus Accept All / Reject All actions. Hidden when nothing is pending.
 */

interface ToolReviewBarProps {
  pendingCount: number;
  onAcceptAll: () => void;
  onRejectAll: () => void;
}

export function ToolReviewBar({ pendingCount, onAcceptAll, onRejectAll }: ToolReviewBarProps) {
  if (pendingCount <= 0) return null;

  const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
  const mod = isMac ? "⌘" : "Ctrl";

  return (
    <div className="tool-review-bar" role="region" aria-label="Pending tool calls">
      <span className="pending-count">
        <span className="pending-dot" />
        {pendingCount} pending action{pendingCount !== 1 ? "s" : ""}
      </span>
      <span className="spacer" />
      <button
        type="button"
        className="tool-review-btn reject"
        onClick={onRejectAll}
        title={`Reject all (${mod}+Shift+Backspace)`}
      >
        ✗ Reject all
      </button>
      <button
        type="button"
        className="tool-review-btn accept"
        onClick={onAcceptAll}
        title={`Accept all (${mod}+Shift+Enter)`}
      >
        ✓ Accept all
        <span className="kbd">{mod}+⇧+↵</span>
      </button>
    </div>
  );
}
