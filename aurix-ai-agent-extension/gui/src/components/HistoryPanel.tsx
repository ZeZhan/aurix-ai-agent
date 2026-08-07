/**
 * HistoryPanel — Browse, search, load, and delete past chat sessions.
 * Inspired by Continue's history page pattern.
 */

import { useCallback, useContext, useEffect, useState } from "react";
import { MessengerContext } from "../context/AurixMessenger";

interface SessionMeta {
  id: string;
  title: string;
  createdAt: number;
  messageCount: number;
}

interface HistoryPanelProps {
  onLoad: (sessionId: string) => void;
  onClose: () => void;
}

function formatDate(ts: number): string {
  const d = new Date(ts);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();

  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (isToday) return `Today ${time}`;
  if (isYesterday) return `Yesterday ${time}`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + ` ${time}`;
}

export function HistoryPanel({ onLoad, onClose }: HistoryPanelProps) {
  const messenger = useContext(MessengerContext);
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    messenger.request<SessionMeta[]>("history/list").then((list) => {
      setSessions((list ?? []).sort((a, b) => b.createdAt - a.createdAt));
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [messenger]);

  const handleDelete = useCallback((id: string) => {
    messenger.post("history/delete", { id });
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setConfirmDelete(null);
  }, [messenger]);

  const filtered = search.trim()
    ? sessions.filter((s) => s.title.toLowerCase().includes(search.toLowerCase()))
    : sessions;

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="flex items-center justify-between px-3 py-2 flex-shrink-0"
        style={{
          borderBottom: "1px solid var(--vscode-panel-border, #3c3c3c)",
          background: "rgba(255,255,255,0.015)",
        }}
      >
        <span className="text-sm font-semibold" style={{ color: "var(--vscode-editor-foreground)" }}>
          Chat History
        </span>
        <button
          onClick={onClose}
          className="text-xs px-2 py-1 rounded"
          style={{
            background: "rgba(255,255,255,0.06)",
            color: "var(--vscode-descriptionForeground)",
            border: "1px solid var(--vscode-panel-border, #3c3c3c)",
            cursor: "pointer",
          }}
        >
          ← Back
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 flex-shrink-0">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search sessions…"
          className="w-full text-xs px-2.5 py-1.5 rounded"
          style={{
            background: "var(--vscode-input-background, #3c3c3c)",
            color: "var(--vscode-input-foreground, #e6e6e6)",
            border: "1px solid var(--vscode-input-border, #3c3c3c)",
            outline: "none",
          }}
        />
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {loading && (
          <div className="text-center text-xs py-6" style={{ color: "var(--vscode-descriptionForeground)" }}>
            Loading…
          </div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="text-center text-xs py-6" style={{ color: "var(--vscode-descriptionForeground)" }}>
            {search ? "No matching sessions" : "No chat history yet"}
          </div>
        )}
        {filtered.map((session) => (
          <div
            key={session.id}
            className="rounded-md mb-1 text-xs"
            style={{
              border: "1px solid var(--vscode-panel-border, #3c3c3c)",
              background: "rgba(255,255,255,0.02)",
            }}
          >
            <div
              className="flex items-center justify-between px-3 py-2 cursor-pointer hover:opacity-80"
              onClick={() => onLoad(session.id)}
            >
              <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                <span
                  className="font-medium truncate"
                  style={{ color: "var(--vscode-editor-foreground)" }}
                >
                  {session.title || "Untitled"}
                </span>
                <span style={{ color: "var(--vscode-descriptionForeground)" }}>
                  {formatDate(session.createdAt)} · {session.messageCount} message{session.messageCount !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                {confirmDelete === session.id ? (
                  <>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(session.id); }}
                      className="px-2 py-0.5 rounded"
                      style={{ background: "rgba(244,135,113,0.15)", color: "#f48771", border: "1px solid rgba(244,135,113,0.3)", cursor: "pointer" }}
                    >
                      Delete
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }}
                      className="px-2 py-0.5 rounded"
                      style={{ background: "rgba(255,255,255,0.06)", color: "var(--vscode-descriptionForeground)", border: "1px solid var(--vscode-panel-border)", cursor: "pointer" }}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={(e) => { e.stopPropagation(); setConfirmDelete(session.id); }}
                    className="px-1.5 py-0.5 rounded opacity-50 hover:opacity-100"
                    style={{ background: "transparent", color: "var(--vscode-descriptionForeground)", border: "none", cursor: "pointer" }}
                    title="Delete session"
                  >
                    🗑
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
