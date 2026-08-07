/**
 * Chat — Main chat interface component, enhanced UI.
 */

import React, { useCallback, useContext, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { MessengerContext } from "../context/AurixMessenger";
import type { ActivityItem, ChatMessage, ToolCallItem, TokenUsage } from "../types";
import { v4 as uuidv4 } from "uuid";
import { ActivityBadge } from "./ActivityBadge";
import { ToolCallCard } from "./ToolCallCard";
import { CodeDiffCard } from "./CodeDiffCard";
import { ChatInput } from "./ChatInput";
import { HistoryPanel } from "./HistoryPanel";
import CodeBlock from "./CodeBlock";
import { AssistantActions } from "./AssistantActions";
import { ToolReviewBar } from "./ToolReviewBar";
import { TokenUsageBadge } from "./TokenUsageBadge";

/* ─── Welcome prompts (AURIX-specific) ─── */
const STARTER_PROMPTS = [
  { icon: "🔍", label: "iLLD lookup",        text: "Find the iLLD API to configure QSPI on TC375 with 10 MHz baud rate." },
  { icon: "📥", label: "Import TC375 demo",  text: "Import the QSPI master example for TC375 into my workspace." },
  { icon: "⚡", label: "Build & flash",      text: "Build my AURIX project with the default Tasking config and flash it to the connected board." },
  { icon: "🔄", label: "TC3xx → TC4xx",     text: "Migrate this file from TC3xx to TC4xx and explain the breaking changes." },
  { icon: "🐛", label: "Debug halted core", text: "The core is halted. Read PSW, PC and the top of the call stack and tell me what went wrong." },
  { icon: "📖", label: "Explain register", text: "Explain the bitfields of the SCU_OSCCON register on TC375." },
];

/* ─── Custom markdown components for code blocks ─── */
const markdownComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || "");
    const codeText = String(children).replace(/\n$/, "");
    // Multi-line → full code block; single line → inline
    if (match || codeText.includes("\n")) {
      return <CodeBlock language={match?.[1]}>{codeText}</CodeBlock>;
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    );
  },
  pre({ children }) {
    // We handle <pre> via the code component, so just pass through
    return <>{children}</>;
  },
};

/* ─── Time formatter ─── */
function formatTime(ts: number): string {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

type ChatMode = "ask" | "agent";

export function Chat() {
  const messenger = useContext(MessengerContext);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [toolCalls, setToolCalls] = useState<ToolCallItem[]>([]);
  const [streamingText, setStreamingText] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [mode, setMode] = useState<ChatMode>("ask");
  const [prefill, setPrefill] = useState<string | undefined>(undefined);
  const [showHistory, setShowHistory] = useState(false);
  const [sessionId, setSessionId] = useState<string>(uuidv4());
  const [feedbackMap, setFeedbackMap] = useState<Record<string, "up" | "down">>({});
  const [tokenUsages, setTokenUsages] = useState<TokenUsage[]>([]);
  const chatBoxRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);

  // Keep messagesRef in sync with state
  useEffect(() => { messagesRef.current = messages; }, [messages]);

  // Global keyboard shortcuts for accept/reject tool calls
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (!mod || !e.shiftKey) return;

      // Ctrl/Cmd + Shift + Enter → Accept all pending tool calls
      if (e.key === "Enter") {
        e.preventDefault();
        setToolCalls((prev) => {
          const pending = prev.filter((tc) => tc.approved === undefined && !tc.autoApprove);
          for (const tc of pending) {
            messenger.post("tools/approve", { toolCallId: tc.toolCallId, approved: true });
          }
          return prev.map((tc) =>
            tc.approved === undefined && !tc.autoApprove ? { ...tc, approved: true } : tc,
          );
        });
      }

      // Ctrl/Cmd + Shift + Backspace → Reject all pending tool calls
      if (e.key === "Backspace") {
        e.preventDefault();
        setToolCalls((prev) => {
          const pending = prev.filter((tc) => tc.approved === undefined && !tc.autoApprove);
          for (const tc of pending) {
            messenger.post("tools/approve", { toolCallId: tc.toolCallId, approved: false });
          }
          return prev.map((tc) =>
            tc.approved === undefined && !tc.autoApprove ? { ...tc, approved: false } : tc,
          );
        });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [messenger]);

  // Fetch initial mode from extension config
  useEffect(() => {
    messenger.request("config/getState").then((cfg: any) => {
      if (cfg?.chatMode === "agent" || cfg?.chatMode === "ask") {
        setMode(cfg.chatMode);
      }
    }).catch(() => {});
  }, [messenger]);

  const handleModeChange = useCallback((newMode: ChatMode) => {
    setMode(newMode);
    messenger.post("config/update", { key: "chatMode", value: newMode });
  }, [messenger]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (chatBoxRef.current) {
      chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    }
  }, [messages, activities, toolCalls, streamingText]);

  // Listen for push messages from extension
  useEffect(() => {
    const handler = (event: MessageEvent) => {
      const { messageType, data } = event.data ?? {};
      if (!messageType) return;
      const payload = data?.content ?? data;

      switch (messageType) {
        case "activity":
          setStreamingText("");  // Clear streaming text when tool activity starts
          setActivities((prev) => {
            const idx = prev.findIndex((a) => a.id === payload.id);
            if (idx >= 0) {
              const updated = [...prev];
              // When activity completes (done/error), clear streamingOutput
              // since fullOutput now replaces it. While running, preserve streaming.
              const keepStreaming = payload.state === "running"
                ? updated[idx].streamingOutput
                : undefined;
              updated[idx] = { ...payload, timestamp: Date.now(), streamingOutput: keepStreaming };
              return updated;
            }
            return [...prev, { ...payload, timestamp: Date.now() }];
          });
          break;
        case "activityChunk":
          setActivities((prev) => {
            const idx = prev.findIndex((a) => a.id === payload.activityId);
            if (idx < 0) return prev;
            const updated = [...prev];
            updated[idx] = {
              ...updated[idx],
              streamingOutput: (updated[idx].streamingOutput ?? "") + payload.chunk,
            };
            return updated;
          });
          break;
        case "toolCall":
          setToolCalls((prev) => [...prev, { ...payload, timestamp: Date.now() }]);
          break;
        case "toolResult":
          setToolCalls((prev) =>
            prev.map((tc) =>
              tc.toolCallId === payload.toolCallId
                ? { ...tc, result: payload.content, isError: payload.isError }
                : tc,
            ),
          );
          break;
        case "streamText":
          if (payload.done) {
            setStreamingText("");
          } else {
            setStreamingText(payload.text ?? "");
          }
          break;
        case "agentDone":
          setIsStreaming(false);
          setStreamingText("");
          // Mark all running activities as done so spinners stop
          setActivities((prev) =>
            prev.map((a) => (a.state === "running" ? { ...a, state: "done" as const } : a)),
          );
          if (payload.summary) {
            setMessages((prev) => [
              ...prev,
              { id: uuidv4(), role: "assistant", content: payload.summary, timestamp: Date.now() },
            ]);
          }
          break;
        case "tokenUsage":
          setTokenUsages((prev) => [...prev, payload as TokenUsage]);
          break;
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, []);

  const handleSend = useCallback(
    async (text: string, contextItems?: Array<{ provider: string; label: string }>) => {
      if (!text.trim() || isStreaming) return;

      const userMsg: ChatMessage = { id: uuidv4(), role: "user", content: text, timestamp: Date.now() };

      // Capture current history BEFORE adding the new user message
      // (messagesRef holds the latest state without needing messages in the dep array)
      const history = messagesRef.current
        .filter((m) => !m.isStreaming)
        .map((m) => ({ role: m.role, content: m.content }));

      setMessages((prev) => [...prev, userMsg]);
      setActivities([]);
      setToolCalls([]);
      setTokenUsages([]);
      setIsStreaming(true);

      if (mode === "agent") {
        // Agent mode: fire-and-forget; updates arrive via push events
        // (activity, toolCall, toolResult, agentDone)
        messenger.post("agent/run", { text, mode: "agent", history, contextItems });
        // isStreaming stays true until "agentDone" event arrives
        return;
      }

      // Ask mode: stream LLM response
      const assistantId = uuidv4();
      setMessages((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "", timestamp: Date.now(), isStreaming: true },
      ]);

      const ac = new AbortController();
      abortRef.current = ac;

      try {
        const gen = messenger.streamChat(text, ac.signal, history);
        for await (const chunks of gen) {
          const newText = chunks.join("");
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + newText } : m)),
          );
        }
      } catch (err: any) {
        if (err.name !== "AbortError") {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + `\n\n**Error:** ${err.message}` } : m,
            ),
          );
        }
      } finally {
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, isStreaming: false } : m)),
        );
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [messenger, isStreaming, mode],
  );

  const handleTerminate = useCallback(() => {
    abortRef.current?.abort();
    messenger.post("agent/terminate");
    setIsStreaming(false);
  }, [messenger]);

  const handleToolApproval = useCallback(
    (toolCallId: string, approved: boolean) => {
      messenger.post("tools/approve", { toolCallId, approved });
      setToolCalls((prev) =>
        prev.map((tc) => (tc.toolCallId === toolCallId ? { ...tc, approved } : tc)),
      );
    },
    [messenger],
  );

  const handleBulkToolApproval = useCallback(
    (approved: boolean) => {
      setToolCalls((prev) => {
        const pending = prev.filter((tc) => tc.approved === undefined && !tc.autoApprove);
        for (const tc of pending) {
          messenger.post("tools/approve", { toolCallId: tc.toolCallId, approved });
        }
        return prev.map((tc) =>
          tc.approved === undefined && !tc.autoApprove ? { ...tc, approved } : tc,
        );
      });
    },
    [messenger],
  );

  const handleFeedback = useCallback(
    (msgId: string, value: "up" | "down") => {
      setFeedbackMap((prev) => {
        const next = { ...prev };
        if (next[msgId] === value) {
          delete next[msgId]; // toggle off
        } else {
          next[msgId] = value;
        }
        // Best-effort: report to extension; ignored if handler not implemented
        messenger.post("feedback/submit", { messageId: msgId, value: next[msgId] ?? null });
        return next;
      });
    },
    [messenger],
  );

  // Edit: put message text back into input, remove that message + everything after it
  const handleEdit = useCallback((msgId: string) => {
    if (isStreaming) return;
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === msgId);
      if (idx < 0) return prev;
      setPrefill(prev[idx].content);
      return prev.slice(0, idx);
    });
  }, [isStreaming]);

  // Retry: re-send the same user message, remove it + everything after it, then send again
  const handleRetry = useCallback((msgId: string) => {
    if (isStreaming) return;
    setMessages((prev) => {
      const idx = prev.findIndex((m) => m.id === msgId);
      if (idx < 0) return prev;
      const text = prev[idx].content;
      // Schedule send after state update
      setTimeout(() => handleSend(text), 0);
      return prev.slice(0, idx);
    });
  }, [isStreaming, handleSend]);

  const showWelcome = messages.length === 0;

  // Auto-save session when messages change (debounced via agentDone / stream end)
  const saveSession = useCallback(() => {
    if (messages.length === 0) return;
    const title = messages.find((m) => m.role === "user")?.content.slice(0, 80) || "Untitled";
    messenger.post("history/save", {
      id: sessionId,
      title,
      createdAt: messages[0]?.timestamp ?? Date.now(),
      messages,
      activities,
      toolCalls,
      isStreaming: false,
      messageCount: messages.length,
    });
  }, [messages, activities, toolCalls, sessionId, messenger]);

  // Save after streaming ends
  useEffect(() => {
    if (!isStreaming && messages.length > 0) {
      saveSession();
    }
  }, [isStreaming]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleNewSession = useCallback(() => {
    if (isStreaming) return;
    saveSession();
    setMessages([]);
    setActivities([]);
    setToolCalls([]);
    setTokenUsages([]);
    setStreamingText("");
    setSessionId(uuidv4());
  }, [isStreaming, saveSession]);

  const handleLoadSession = useCallback((id: string) => {
    if (isStreaming) return;
    messenger.request("history/load", { id }).then((data: any) => {
      if (!data) return;
      setMessages(data.messages ?? []);
      setActivities(data.activities ?? []);
      setToolCalls(data.toolCalls ?? []);
      setSessionId(data.id ?? id);
      setShowHistory(false);
    }).catch(() => {});
  }, [isStreaming, messenger]);

  // Show history panel
  if (showHistory) {
    return (
      <div className="flex h-full flex-col">
        <HistoryPanel
          onLoad={handleLoadSession}
          onClose={() => setShowHistory(false)}
        />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* ─── Status bar ─── */}
      <div className="status-bar">
        <span className="status-dot green" />
        <span>Copilot SDK</span>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "8px" }}>
          <button
            onClick={handleNewSession}
            disabled={isStreaming || messages.length === 0}
            className="status-bar-btn"
            title="New chat"
            style={{ opacity: (isStreaming || messages.length === 0) ? 0.4 : 1 }}
          >
            ＋ New
          </button>
          <button
            onClick={() => setShowHistory(true)}
            disabled={isStreaming}
            className="status-bar-btn"
            title="Chat history"
            style={{ opacity: isStreaming ? 0.4 : 1 }}
          >
            📋 History
          </button>
        </div>
      </div>

      {/* ─── Message area ─── */}
      <div ref={chatBoxRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-4">

        {/* Welcome screen */}
        {showWelcome && (
          <div className="flex flex-col items-center justify-center h-full gap-5 px-4">
            <div className="welcome-logo">A</div>
            <div className="text-center">
              <div className="text-base font-semibold mb-1" style={{ color: "var(--vscode-editor-foreground)" }}>
                AURIX AI Agent
              </div>
              <div className="text-xs" style={{ color: "var(--vscode-descriptionForeground)" }}>
                Write code, search docs, build, flash &amp; debug your AURIX project.
              </div>
            </div>
            <div className="flex flex-wrap justify-center gap-2 mt-2 max-w-[360px]">
              {STARTER_PROMPTS.map((sp) => (
                <button
                  key={sp.label}
                  className="welcome-chip"
                  onClick={() => handleSend(sp.text)}
                >
                  <span>{sp.icon}</span>
                  <span>{sp.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Unified timeline: messages, activities, and tool calls sorted by time */}
        {(() => {
          // Build timeline entries
          type TimelineEntry =
            | { kind: "message"; data: ChatMessage; ts: number }
            | { kind: "activity"; data: ActivityItem; ts: number }
            | { kind: "toolCall"; data: ToolCallItem; ts: number };

          const entries: TimelineEntry[] = [
            ...messages.map((m) => ({ kind: "message" as const, data: m, ts: m.timestamp })),
            // Show running activities, completed with output, streaming output, and agent thinking
            ...activities
              .filter((a) => a.state === "running" || a.fullOutput || a.streamingOutput || a.type === "thinking")
              .map((a) => ({ kind: "activity" as const, data: a, ts: a.timestamp })),
            // Show tool calls that need approval OR have been resolved
            ...toolCalls
              .filter((tc) => !tc.autoApprove)
              .map((tc) => ({ kind: "toolCall" as const, data: tc, ts: tc.timestamp })),
          ];
          entries.sort((a, b) => a.ts - b.ts);

          return entries.map((entry) => {
            if (entry.kind === "message") {
              const msg = entry.data;
              return (
                <div key={msg.id} className={`flex gap-2 ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}>
                  <div
                    className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold"
                    style={{
                      background: msg.role === "user"
                        ? "var(--vscode-button-background, #0e639c)"
                        : "linear-gradient(135deg, #0e639c, #00a1e0)",
                      color: "#fff",
                    }}
                  >
                    {msg.role === "user" ? "U" : "A"}
                  </div>
                  <div className={`max-w-[88%] flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                    <div className={`msg-bubble-wrap ${msg.role === "user" ? "msg-bubble-user" : "msg-bubble-wrap-assistant"}`}>
                      <div className={`px-3 py-2 text-sm ${msg.role === "user" ? "msg-user" : "msg-assistant"}`}>
                        {msg.role === "assistant" ? (
                          <div className="markdown-body">
                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{msg.content}</ReactMarkdown>
                            {msg.isStreaming && <span className="streaming-cursor" />}
                          </div>
                        ) : (
                          <div className="whitespace-pre-wrap">{msg.content}</div>
                        )}
                      </div>
                      {msg.role === "user" && !isStreaming && (
                        <div className="msg-actions">
                          <button className="msg-action-btn" title="Edit" onClick={() => handleEdit(msg.id)}>✏️</button>
                          <button className="msg-action-btn" title="Retry" onClick={() => handleRetry(msg.id)}>🔄</button>
                        </div>
                      )}
                      {msg.role === "assistant" && !msg.isStreaming && msg.content.trim().length > 0 && (
                        <AssistantActions
                          messageId={msg.id}
                          content={msg.content}
                          feedback={feedbackMap[msg.id]}
                          onFeedback={(v) => handleFeedback(msg.id, v)}
                        />
                      )}
                    </div>
                    <span className="text-[10px] mt-1 px-1" style={{ color: "var(--vscode-descriptionForeground)" }}>
                      {formatTime(msg.timestamp)}
                    </span>
                  </div>
                </div>
              );
            }

            if (entry.kind === "activity") {
              return <ActivityBadge key={entry.data.id} activity={entry.data} />;
            }

            // Tool call — show full CodeDiffCard if pending, collapsed summary if resolved
            const tc = entry.data;
            if (tc.approved === undefined) {
              // Pending: show full card
              return tc.diffs && tc.diffs.length > 0 ? (
                <CodeDiffCard
                  key={tc.toolCallId}
                  toolCallId={tc.toolCallId}
                  diffs={tc.diffs}
                  approved={tc.approved}
                  onApprove={(id) => handleToolApproval(id, true)}
                  onReject={(id) => handleToolApproval(id, false)}
                />
              ) : (
                <ToolCallCard
                  key={tc.toolCallId}
                  toolCall={tc}
                  onApprove={(id) => handleToolApproval(id, true)}
                  onReject={(id) => handleToolApproval(id, false)}
                />
              );
            }

            // Resolved: collapsed one-line summary
            const statusIcon = tc.approved ? "✓" : "✗";
            const statusColor = tc.approved ? "var(--aurix-success)" : "var(--aurix-error)";
            const statusLabel = tc.approved ? "Applied" : "Rejected";
            const fileCount = tc.diffs?.length ?? 0;
            const fileNames = tc.diffs?.map((d) => d.path.split("/").pop()).join(", ") ?? tc.toolName;
            return (
              <div
                key={tc.toolCallId}
                className="flex items-center gap-2 rounded-md px-3 py-1.5 text-xs"
                style={{
                  background: "var(--aurix-surface-1)",
                  border: "1px solid var(--aurix-border-subtle)",
                  color: "var(--aurix-text-secondary)",
                }}
              >
                <span style={{ color: statusColor, fontWeight: 600 }}>{statusIcon} {statusLabel}</span>
                <span>·</span>
                <span className="font-mono">{fileNames}</span>
                {fileCount > 0 && <span>({fileCount} file{fileCount !== 1 ? "s" : ""})</span>}
              </div>
            );
          });
        })()}

        {/* Streaming LLM text (live typing) */}
        {streamingText && (() => {
          // Strip tool-call JSON from display — only show the "thinking" portion
          const jsonStart = streamingText.search(/\{\s*"tool"\s*:/);
          const displayText = (jsonStart > 0 ? streamingText.slice(0, jsonStart) : streamingText).trim();
          if (!displayText) return null;
          return (
            <div
              className="rounded-lg px-3 py-2 text-xs whitespace-pre-wrap"
              style={{
                background: "var(--aurix-surface-1)",
                border: "1px solid var(--aurix-border-subtle)",
                color: "var(--aurix-text-secondary)",
                lineHeight: "1.5",
                animation: "fadeIn 0.15s ease-in",
              }}
            >
              <span style={{ opacity: 0.5 }}>💭 </span>
              {displayText}
              <span className="inline-block w-1.5 h-3 ml-0.5 align-middle" style={{ background: "var(--aurix-text-primary)", opacity: 0.6, animation: "blink 1s step-end infinite" }} />
            </div>
          );
        })()}

        {/* Token usage summary (shown when not streaming and has data) */}
        {!isStreaming && tokenUsages.length > 0 && (
          <TokenUsageBadge usages={tokenUsages} />
        )}
      </div>

      {/* Pending tool-call review bar (Accept all / Reject all) */}
      <ToolReviewBar
        pendingCount={toolCalls.filter((tc) => tc.approved === undefined && !tc.autoApprove).length}
        onAcceptAll={() => handleBulkToolApproval(true)}
        onRejectAll={() => handleBulkToolApproval(false)}
      />

      {/* Input */}
      <ChatInput onSend={handleSend} onTerminate={handleTerminate} isStreaming={isStreaming} mode={mode} onModeChange={handleModeChange} prefill={prefill} onPrefillConsumed={() => setPrefill(undefined)} />
    </div>
  );
}
