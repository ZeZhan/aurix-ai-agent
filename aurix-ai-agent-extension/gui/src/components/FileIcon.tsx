/**
 * FileIcon — Renders a colored icon for a filename based on its extension.
 * Lightweight: no external icon font — uses SVG codicons + extension-based colors.
 */

import { useMemo } from "react";

// ---------------------------------------------------------------------------
// Extension → icon / color mapping (covers AURIX-relevant files)
// ---------------------------------------------------------------------------

interface IconDef {
  /** SVG path data (16×16 viewBox). */
  path: string;
  /** Fill color. */
  color: string;
  /** Friendly label. */
  label: string;
}

// Generic file icon path (codicon: file)
const FILE_PATH = "M13.71 4.29l-3-3L10 1H4L3 2v12l1 1h9l1-1V5l-.29-.71zM13 14H4V2h5v4h4v8zm-1-9h-2V3l2 2z";
// Folder icon path
const FOLDER_PATH = "M14.5 3H7.71l-.85-.85L6.51 2h-5l-.5.5v11l.5.5h13l.5-.5v-10L14.5 3zm-.51 8.49V13h-12V3h4.29l.85.85.36.15H14v2.49l-.01 5z";
// Code file icon path
const CODE_PATH = "M11.46 4.81l-1.42-1.42-4.78 4.78-.21.29.21.29 4.78 4.78 1.42-1.42L7.87 7.92l3.59-3.11zM4.54 11.19l1.42 1.42 4.78-4.78.21-.29-.21-.29L5.96 2.47 4.54 3.89l3.59 3.11-3.59 4.19z";
// Gear icon for config files
const GEAR_PATH = "M9.1 4.4L8.6 2H7.4l-.5 2.4-.7.3-2-1.3-.9.8 1.3 2-.2.7-2.4.5v1.2l2.4.5.3.7-1.3 2 .8.8 2-1.3.7.3.5 2.4h1.2l.5-2.4.7-.3 2 1.3.8-.8-1.3-2 .3-.7 2.4-.5V6.8l-2.4-.5-.3-.7 1.3-2-.8-.8-2 1.3-.7-.3zM8 10a2 2 0 110-4 2 2 0 010 4z";

const ICON_MAP: Record<string, IconDef> = {
  // C / C++
  ".c":     { path: CODE_PATH, color: "#519aba", label: "C source" },
  ".h":     { path: CODE_PATH, color: "#a074c4", label: "C header" },
  ".cpp":   { path: CODE_PATH, color: "#519aba", label: "C++ source" },
  ".hpp":   { path: CODE_PATH, color: "#a074c4", label: "C++ header" },
  ".cc":    { path: CODE_PATH, color: "#519aba", label: "C++ source" },
  ".cxx":   { path: CODE_PATH, color: "#519aba", label: "C++ source" },

  // Assembly
  ".s":     { path: CODE_PATH, color: "#e37933", label: "Assembly" },
  ".S":     { path: CODE_PATH, color: "#e37933", label: "Assembly" },
  ".asm":   { path: CODE_PATH, color: "#e37933", label: "Assembly" },

  // Linker
  ".ld":    { path: GEAR_PATH, color: "#e37933", label: "Linker script" },
  ".lsl":   { path: GEAR_PATH, color: "#e37933", label: "Linker script" },
  ".lcf":   { path: GEAR_PATH, color: "#e37933", label: "Linker script" },

  // Build
  ".mk":    { path: GEAR_PATH, color: "#6d8086", label: "Makefile" },

  // TypeScript / JavaScript
  ".ts":    { path: CODE_PATH, color: "#519aba", label: "TypeScript" },
  ".tsx":   { path: CODE_PATH, color: "#519aba", label: "TypeScript React" },
  ".js":    { path: CODE_PATH, color: "#cbcb41", label: "JavaScript" },
  ".jsx":   { path: CODE_PATH, color: "#cbcb41", label: "JavaScript React" },

  // Data / Config
  ".json":  { path: GEAR_PATH, color: "#cbcb41", label: "JSON" },
  ".xml":   { path: GEAR_PATH, color: "#e37933", label: "XML" },
  ".yaml":  { path: GEAR_PATH, color: "#a074c4", label: "YAML" },
  ".yml":   { path: GEAR_PATH, color: "#a074c4", label: "YAML" },
  ".toml":  { path: GEAR_PATH, color: "#6d8086", label: "TOML" },
  ".cfg":   { path: GEAR_PATH, color: "#6d8086", label: "Config" },
  ".ini":   { path: GEAR_PATH, color: "#6d8086", label: "Config" },

  // Web
  ".html":  { path: CODE_PATH, color: "#e37933", label: "HTML" },
  ".css":   { path: CODE_PATH, color: "#519aba", label: "CSS" },

  // Python
  ".py":    { path: CODE_PATH, color: "#519aba", label: "Python" },

  // Markdown
  ".md":    { path: FILE_PATH, color: "#519aba", label: "Markdown" },

  // Binary / Output
  ".elf":   { path: FILE_PATH, color: "#4ec9b0", label: "ELF binary" },
  ".hex":   { path: FILE_PATH, color: "#4ec9b0", label: "HEX file" },
  ".bin":   { path: FILE_PATH, color: "#4ec9b0", label: "Binary" },
  ".o":     { path: FILE_PATH, color: "#6d8086", label: "Object file" },
  ".a":     { path: FILE_PATH, color: "#6d8086", label: "Archive" },
  ".map":   { path: FILE_PATH, color: "#6d8086", label: "Map file" },
};

/** Exact filename matches */
const NAME_MAP: Record<string, IconDef> = {
  "Makefile":       { path: GEAR_PATH, color: "#6d8086", label: "Makefile" },
  "makefile":       { path: GEAR_PATH, color: "#6d8086", label: "Makefile" },
  "CMakeLists.txt": { path: GEAR_PATH, color: "#6d8086", label: "CMake" },
  ".gitignore":     { path: GEAR_PATH, color: "#41535b", label: "Git ignore" },
};

function resolveIcon(filename: string): IconDef {
  // Try exact name match first
  const name = filename.split("/").pop() ?? filename;
  if (NAME_MAP[name]) return NAME_MAP[name];

  // Try extension
  const dotIdx = name.lastIndexOf(".");
  if (dotIdx >= 0) {
    const ext = name.slice(dotIdx).toLowerCase();
    if (ICON_MAP[ext]) return ICON_MAP[ext];
  }

  // Default
  return { path: FILE_PATH, color: "var(--vscode-descriptionForeground, #888)", label: "File" };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface FileIconProps {
  filename: string;
  size?: number;
  className?: string;
}

export function FileIcon({ filename, size = 16, className }: FileIconProps) {
  const icon = useMemo(() => resolveIcon(filename), [filename]);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill={icon.color}
      className={className}
      style={{ flexShrink: 0, display: "inline-block", verticalAlign: "middle" }}
      aria-label={icon.label}
    >
      <path d={icon.path} />
    </svg>
  );
}

/** Returns just the color for a filename (for use in styled text). */
export function getFileColor(filename: string): string {
  return resolveIcon(filename).color;
}

/** Folder icon variant. */
export function FolderIcon({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="#dcb67a"
      className={className}
      style={{ flexShrink: 0, display: "inline-block", verticalAlign: "middle" }}
      aria-label="Folder"
    >
      <path d={FOLDER_PATH} />
    </svg>
  );
}
