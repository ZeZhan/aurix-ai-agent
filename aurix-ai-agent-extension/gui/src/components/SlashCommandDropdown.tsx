/**
 * SlashCommandDropdown — Autocomplete for `/` slash commands at the start of
 * the chat input. Mirrors the chrome of MentionDropdown.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export interface SlashCommand {
  /** Command name without the leading slash, e.g. "edit". */
  name: string;
  /** Short one-line description shown in the picker. */
  description: string;
  /** Optional emoji / glyph. */
  icon?: string;
  /**
   * What to inject into the textarea when chosen. If omitted, the literal
   * "/<name> " is inserted, leaving the cursor at the end so the user can
   * type their argument.
   */
  insert?: string;
}

interface SlashCommandDropdownProps {
  /** Current text in the textarea (full value, not just the slash query). */
  text: string;
  visible: boolean;
  onSelect: (cmd: SlashCommand) => void;
  onClose: () => void;
  /** Optional override of the built-in command list. */
  commands?: SlashCommand[];
}

const DEFAULT_COMMANDS: SlashCommand[] = [
  { name: "edit",    icon: "✏️", description: "Edit the current selection or file" },
  { name: "explain", icon: "💡", description: "Explain the selected code or concept" },
  { name: "fix",     icon: "🩹", description: "Diagnose and fix the current error / diagnostic" },
  { name: "test",    icon: "🧪", description: "Generate unit tests for the current symbol" },
  { name: "review",  icon: "👀", description: "Review the current diff or file for issues" },
  { name: "build",   icon: "🔨", description: "Build the current AURIX project" },
  { name: "flash",   icon: "⚡", description: "Build and flash the connected AURIX board" },
  { name: "debug",   icon: "🐛", description: "Start a debug session and inspect halted core" },
  { name: "import",  icon: "📦", description: "Import an iLLD example into the workspace" },
  { name: "migrate", icon: "🔄", description: "Migrate code from TC3xx to TC4xx" },
  { name: "docs",    icon: "📖", description: "Search Infineon documentation" },
];

/**
 * Returns the active slash query if `text` begins with `/` and contains no
 * whitespace, otherwise null. Slash commands only trigger when they are the
 * first token of the input.
 */
export function getSlashQuery(text: string): string | null {
  if (!text.startsWith("/")) return null;
  const firstSpace = text.search(/\s/);
  if (firstSpace >= 0) return null; // user has moved past the command name
  return text.slice(1);
}

export function SlashCommandDropdown({
  text,
  visible,
  onSelect,
  onClose,
  commands = DEFAULT_COMMANDS,
}: SlashCommandDropdownProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const query = useMemo(() => getSlashQuery(text)?.toLowerCase() ?? "", [text]);

  const items = useMemo(() => {
    if (!query) return commands;
    return commands.filter((c) => c.name.startsWith(query));
  }, [commands, query]);

  // Reset selection when the candidate list changes
  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (!visible || items.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => Math.min(i + 1, items.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        onSelect(items[selectedIndex]);
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    },
    [visible, items, selectedIndex, onSelect, onClose],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [handleKeyDown]);

  // Scroll selected into view
  useEffect(() => {
    const el = listRef.current?.children[selectedIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!visible || items.length === 0) return null;

  return (
    <div ref={listRef} className="slash-dropdown" role="listbox" aria-label="Slash commands">
      {items.map((cmd, i) => (
        <div
          key={cmd.name}
          className={`slash-item ${i === selectedIndex ? "active" : ""}`}
          role="option"
          aria-selected={i === selectedIndex}
          onMouseEnter={() => setSelectedIndex(i)}
          onClick={() => onSelect(cmd)}
        >
          <span className="slash-icon">{cmd.icon ?? "›"}</span>
          <div className="slash-meta">
            <span className="slash-cmd">/{cmd.name}</span>
            <span className="slash-desc">{cmd.description}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
