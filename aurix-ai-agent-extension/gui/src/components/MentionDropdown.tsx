/**
 * MentionDropdown — Autocomplete dropdown for @file mentions in chat input.
 * Shows available context providers (files, docs, device) when user types @.
 */

import { useCallback, useContext, useEffect, useRef, useState } from "react";
import { MessengerContext } from "../context/AurixMessenger";

export interface MentionItem {
  provider: string;
  label: string;
  description?: string;
  icon?: string;
}

interface MentionDropdownProps {
  query: string;
  /** Position relative to input (bottom-left of caret) */
  visible: boolean;
  onSelect: (item: MentionItem) => void;
  onClose: () => void;
}

const PROVIDERS: MentionItem[] = [
  { provider: "file", label: "file", description: "Reference a workspace file", icon: "📄" },
  { provider: "docs", label: "docs", description: "Search Infineon documentation", icon: "📖" },
  { provider: "device", label: "device", description: "Search device headers", icon: "🔍" },
  { provider: "example", label: "example", description: "Reference a code example", icon: "📦" },
];

export function MentionDropdown({ query, visible, onSelect, onClose }: MentionDropdownProps) {
  const messenger = useContext(MessengerContext);
  const [items, setItems] = useState<MentionItem[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  // Determine if we're picking a provider or querying within one
  const parts = query.split(" ", 2);
  const providerPart = parts[0]?.toLowerCase() ?? "";
  const activeProvider = PROVIDERS.find((p) => p.label === providerPart);

  useEffect(() => {
    if (!visible) return;
    if (!activeProvider) {
      // Show matching providers
      const filtered = providerPart
        ? PROVIDERS.filter((p) => p.label.startsWith(providerPart))
        : PROVIDERS;
      setItems(filtered);
      setSelectedIndex(0);
    } else {
      // Query the provider for items
      const subQuery = parts.slice(1).join(" ");
      if (subQuery.length < 1) {
        setItems([]);
        return;
      }
      messenger.request("context/getItems", { provider: activeProvider.provider, query: subQuery })
        .then((results: any[]) => {
          const mapped = (results ?? []).slice(0, 8).map((r: any) => ({
            provider: activeProvider.provider,
            label: r.name || r.label || r.path || String(r),
            description: r.description || r.path || "",
            icon: activeProvider.icon,
          }));
          setItems(mapped);
          setSelectedIndex(0);
        })
        .catch(() => setItems([]));
    }
  }, [query, visible, messenger]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
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
  }, [visible, items, selectedIndex, onSelect, onClose]);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown, true);
    return () => window.removeEventListener("keydown", handleKeyDown, true);
  }, [handleKeyDown]);

  // Scroll selected into view
  useEffect(() => {
    const el = listRef.current?.children[selectedIndex] as HTMLElement;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!visible || items.length === 0) return null;

  return (
    <div
      ref={listRef}
      className="mention-dropdown"
      style={{
        position: "absolute",
        bottom: "100%",
        left: "8px",
        marginBottom: "4px",
        maxHeight: "200px",
        overflowY: "auto",
        background: "var(--vscode-editorSuggestWidget-background, #252526)",
        border: "1px solid var(--vscode-editorSuggestWidget-border, #454545)",
        borderRadius: "6px",
        boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
        zIndex: 100,
        minWidth: "220px",
      }}
    >
      {items.map((item, i) => (
        <div
          key={`${item.provider}-${item.label}-${i}`}
          className="flex items-center gap-2 px-3 py-1.5 cursor-pointer text-xs"
          style={{
            background: i === selectedIndex ? "var(--vscode-list-hoverBackground, rgba(255,255,255,0.06))" : "transparent",
            color: "var(--vscode-editor-foreground)",
          }}
          onMouseEnter={() => setSelectedIndex(i)}
          onClick={() => onSelect(item)}
        >
          <span>{item.icon || "📌"}</span>
          <div className="flex flex-col min-w-0">
            <span className="font-medium truncate">{item.label}</span>
            {item.description && (
              <span className="truncate" style={{ color: "var(--vscode-descriptionForeground)", fontSize: "10px" }}>
                {item.description}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
