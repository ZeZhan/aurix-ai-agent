/**
 * Chat message types for the GUI state.
 */

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  isStreaming?: boolean;
  isError?: boolean;
}

export interface ActivityItem {
  id: string;
  type: string;
  message: string;
  state: "running" | "done" | "error";
  detail?: string;
  /** Full tool output (e.g. compiler output for build). Shown in expandable section. */
  fullOutput?: string;
  /** Accumulated streaming output chunks (real-time CLI output). */
  streamingOutput?: string;
  timestamp: number;
}

export interface FileDiff {
  path: string;
  action: "write" | "replace" | "delete";
  original: string;
  proposed: string;
}

export interface ToolCallItem {
  toolCallId: string;
  toolName: string;
  args: Record<string, any>;
  autoApprove: boolean;
  result?: string;
  isError?: boolean;
  approved?: boolean;
  /** Diff data for write_code tool calls */
  diffs?: FileDiff[];
  timestamp: number;
}

export interface ChatSession {
  id: string;
  messages: ChatMessage[];
  activities: ActivityItem[];
  toolCalls: ToolCallItem[];
  isStreaming: boolean;
  title: string;
}

export interface TokenUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens?: number;
  cacheWriteTokens?: number;
  reasoningTokens?: number;
  model: string;
  duration?: number;
}
