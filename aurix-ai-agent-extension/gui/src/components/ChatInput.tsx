/**
 * ChatInput — Message composer with mode toggle, send/terminate, and @mention support.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { MentionDropdown, type MentionItem } from "./MentionDropdown";
import { SlashCommandDropdown, type SlashCommand, getSlashQuery } from "./SlashCommandDropdown";

type ChatMode = "ask" | "agent";

/** Context items attached to the message (from @mentions) */
export interface AttachedContext {
  provider: string;
  label: string;
}

interface ChatInputProps {
  onSend: (text: string, contextItems?: AttachedContext[]) => void;
  onTerminate: () => void;
  isStreaming: boolean;
  mode: ChatMode;
  onModeChange: (mode: ChatMode) => void;
  /** Pre-fill the textarea (e.g. when editing a message) */
  prefill?: string;
  onPrefillConsumed?: () => void;
}

export function ChatInput({ onSend, onTerminate, isStreaming, mode, onModeChange, prefill, onPrefillConsumed }: ChatInputProps) {
  const [text, setText] = useState("");
  const [contextItems, setContextItems] = useState<AttachedContext[]>([]);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionVisible, setMentionVisible] = useState(false);
  const [slashVisible, setSlashVisible] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Consume prefill when it changes
  useEffect(() => {
    if (prefill !== undefined && prefill !== "") {
      setText(prefill);
      onPrefillConsumed?.();
      // Auto-resize
      requestAnimationFrame(() => {
        const ta = textareaRef.current;
        if (ta) {
          ta.style.height = "auto";
          ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
          ta.focus();
          ta.setSelectionRange(ta.value.length, ta.value.length);
        }
      });
    }
  }, [prefill]);

  const handleSend = useCallback(() => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed, contextItems.length > 0 ? contextItems : undefined);
    setText("");
    setContextItems([]);
    setMentionVisible(false);
    setSlashVisible(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [text, contextItems, onSend]);

  // Detect @mention trigger
  const handleTextChange = useCallback((newText: string) => {
    setText(newText);

    // Slash command picker (only at the very start of the input, no whitespace yet)
    setSlashVisible(getSlashQuery(newText) !== null);

    // Find the last @ in the text
    const cursorPos = textareaRef.current?.selectionStart ?? newText.length;
    const textUpToCursor = newText.slice(0, cursorPos);
    const atIndex = textUpToCursor.lastIndexOf("@");

    if (atIndex >= 0) {
      const charBefore = atIndex > 0 ? textUpToCursor[atIndex - 1] : " ";
      // Only trigger if @ is at word boundary (start of line or after space)
      if (atIndex === 0 || charBefore === " " || charBefore === "\n") {
        const query = textUpToCursor.slice(atIndex + 1);
        // Don't show mention if there's a newline after @
        if (!query.includes("\n")) {
          setMentionQuery(query);
          setMentionVisible(true);
          return;
        }
      }
    }
    setMentionVisible(false);
  }, []);

  const handleMentionSelect = useCallback((item: MentionItem) => {
    // Replace the @query with a tag
    const cursorPos = textareaRef.current?.selectionStart ?? text.length;
    const textUpToCursor = text.slice(0, cursorPos);
    const atIndex = textUpToCursor.lastIndexOf("@");

    if (atIndex >= 0) {
      const before = text.slice(0, atIndex);
      const after = text.slice(cursorPos);
      const tag = `@${item.label} `;
      const newText = before + tag + after;
      setText(newText);
      setContextItems((prev) => [...prev, { provider: item.provider, label: item.label }]);

      // Move cursor after the tag
      requestAnimationFrame(() => {
        const ta = textareaRef.current;
        if (ta) {
          const newPos = before.length + tag.length;
          ta.setSelectionRange(newPos, newPos);
          ta.focus();
        }
      });
    }
    setMentionVisible(false);
  }, [text]);

  const handleSlashSelect = useCallback((cmd: SlashCommand) => {
    const insert = cmd.insert ?? `/${cmd.name} `;
    setText(insert);
    setSlashVisible(false);
    requestAnimationFrame(() => {
      const ta = textareaRef.current;
      if (ta) {
        ta.focus();
        ta.setSelectionRange(insert.length, insert.length);
        ta.style.height = "auto";
        ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
      }
    });
  }, []);

  const removeContext = useCallback((index: number) => {
    setContextItems((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      // Let dropdowns handle navigation keys when visible
      const dropdownOpen = mentionVisible || slashVisible;
      if (dropdownOpen && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Tab")) {
        return; // handled by dropdown's own listener
      }
      if (e.key === "Escape" && dropdownOpen) {
        e.preventDefault();
        setMentionVisible(false);
        setSlashVisible(false);
        return;
      }
      if (e.key === "Enter" && !e.shiftKey) {
        if (dropdownOpen) return; // let dropdown handle it
        e.preventDefault();
        if (isStreaming) return;
        handleSend();
      }
    },
    [handleSend, isStreaming, mentionVisible, slashVisible],
  );

  const handleInput = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, []);

  return (
    <div
      className={`px-3 py-2 chat-input-panel ${isStreaming ? "thinking" : ""}`}
      style={{
        borderTop: "1px solid var(--vscode-panel-border, #3c3c3c)",
        background: "rgba(255,255,255,0.015)",
        flexShrink: 0,
      }}
    >
      {/* Mode toggle row */}
      <div className="flex items-center gap-1 mb-1.5 px-0.5">
        <div className="mode-toggle">
          <button
            className={`mode-toggle-btn ${mode === "ask" ? "active" : ""}`}
            onClick={() => onModeChange("ask")}
          >
            Ask
          </button>
          <button
            className={`mode-toggle-btn ${mode === "agent" ? "active" : ""}`}
            onClick={() => onModeChange("agent")}
          >
            Agent
          </button>
        </div>
        <span className="text-[10px] ml-1.5" style={{ color: "var(--vscode-descriptionForeground, #888)" }}>
          {mode === "agent" ? "Can edit files, build & flash" : "Read-only answers"}
        </span>
      </div>

      {/* Input container with shimmer glow border */}
      <div className={`chat-input-glow ${isStreaming ? "thinking" : ""}`} style={{ position: "relative" }}>
        {/* Mention autocomplete dropdown */}
        <MentionDropdown
          query={mentionQuery}
          visible={mentionVisible}
          onSelect={handleMentionSelect}
          onClose={() => setMentionVisible(false)}
        />
        {/* Slash command dropdown */}
        <SlashCommandDropdown
          text={text}
          visible={slashVisible}
          onSelect={handleSlashSelect}
          onClose={() => setSlashVisible(false)}
        />
        <div
          className="flex items-end gap-2 chat-input-inner"
          style={{ padding: "4px" }}
        >
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => handleTextChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onInput={handleInput}
          placeholder={isStreaming ? "Agent is running…" : "Ask AURIX AI…  (↵ to send, @ context, / commands)"}
          disabled={isStreaming}
          rows={1}
          className="flex-1 resize-none text-sm focus:outline-none disabled:opacity-50"
          style={{
            background: "transparent",
            color: "var(--vscode-input-foreground, #e6e6e6)",
            padding: "6px 8px",
            minHeight: "32px",
            maxHeight: "200px",
            border: "none",
            fontFamily: "inherit",
          }}
        />
        {isStreaming ? (
          <button
            onClick={onTerminate}
            className="flex-shrink-0 flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium"
            title="Terminate"
            style={{
              background: "var(--vscode-inputValidation-errorBackground, #5a1d1d)",
              color: "#f48771",
              border: "1px solid rgba(244,135,113,0.3)",
            }}
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><rect width="10" height="10" rx="1.5"/></svg>
            Stop
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!text.trim()}
            className="flex-shrink-0 flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium transition-opacity disabled:opacity-30"
            style={{
              background: "var(--vscode-button-background, #0e639c)",
              color: "var(--vscode-button-foreground, #fff)",
            }}
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            Send
          </button>
        )}
        </div>
      </div>

      {/* Context items pills */}
      {contextItems.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5 px-1">
          {contextItems.map((ctx, i) => (
            <span
              key={`${ctx.provider}-${ctx.label}-${i}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px]"
              style={{
                background: "rgba(0,161,224,0.1)",
                color: "var(--aurix-accent)",
                border: "1px solid rgba(0,161,224,0.2)",
              }}
            >
              @{ctx.label}
              <button
                onClick={() => removeContext(i)}
                className="ml-0.5 hover:opacity-100 opacity-60"
                style={{ background: "none", border: "none", color: "inherit", cursor: "pointer", padding: 0, fontSize: "10px" }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between mt-1.5 px-1">
        <span className="text-[10px]" style={{ color: "var(--vscode-descriptionForeground, #888)" }}>
          Shift+Enter newline · @ context · / commands
        </span>
        <span className="text-[10px]" style={{ color: "var(--vscode-descriptionForeground, #888)" }}>
          Powered by Copilot
        </span>
      </div>
    </div>
  );
}
