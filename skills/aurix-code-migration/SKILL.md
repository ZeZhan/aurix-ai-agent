---
name: aurix-code-migration
description: Migrate or port AURIX TriCore code between devices or families (e.g. TC4D7 to TC334, TC3xx to TC2xx, TC375 to TC397). Use when the user asks to port, migrate, convert, or adapt existing AURIX code to a different target device or board.
---

# Workflow for code migration (e.g. *migrate TC4D7 → TC334*)

1. **New directory.** `ads_create_project` in a **fresh** workspace for the
   target device. Never overwrite the source project in-place — leftover
   SSW configs and build artifacts cause link errors. Copy only your
   application `.c`/`.h` into the new workspace.
2. **Research device differences.** Call `documentation_search` separately for
   the explicit source and target `device` to verify peripheral availability,
   architectural differences, limits, register behaviour, board connectivity,
   and relevant errata. Base migration claims on its physical-page citations;
   if evidence is absent or the tool abstains, report the uncertainty and do not
   guess. Then search iLLD headers for both devices to confirm peripheral names
   and exact API signatures (see skill `aurix-illd-lookup`). Cross-family moves
   (TC4x↔TC3x↔TC2x) can rename entire modules and change function signatures.
3. **Resolve pins.** Use `documentation_search` for target-board schematics or
   connectivity, then confirm the software symbol in the target project's iLLD
   pin map for its package (see skill `aurix-illd-lookup`). Never assume pins
   are the same across devices or boards.
4. **Global replace.** `grep_search` the workspace for every source-family
   API and fix **all files in one pass** (Cpu0–CpuN, all app files). Do not
   fix one file at a time.
5. **Clean build.** Delete `build/` before the first target build.
6. **Unsupported peripherals** — if cited target documentation shows that a
   source peripheral is absent, stop and inform the user before proceeding. Do
   not infer absence only because an example or iLLD symbol search had no hit.
7. **Requested runtime verification.** If the user asks to validate or debug the
   port, read and follow [aurix-debug-workflow](../aurix-debug-workflow/SKILL.md).
   Discover AURIX Debug MCP, reuse a suitable session or prepare an authorized
   startup for the target ELF, and check the requested behaviour with fresh
   observations. New Debug MCP sessions require flashing; omit the removed
   `flash` input. Follow the Debug Skill's preservation rules when programming
   is forbidden, rather than requesting a no-flash MCP startup.
   Report build/flash results separately from runtime evidence and identify
   unverified assertions. Build-only or flash-only requests do not authorize
   automatic debugger verification. If tools are missing, follow the tool
   discovery rule in the workspace instructions.