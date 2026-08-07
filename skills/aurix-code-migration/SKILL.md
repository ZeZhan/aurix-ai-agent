---
name: aurix-code-migration
description: Migrate or port AURIX TriCore code between devices or families (e.g. TC4D7 to TC334, TC3xx to TC2xx, TC375 to TC397). Use when the user asks to port, migrate, convert, or adapt existing AURIX code to a different target device or board.
---

# Workflow for code migration (e.g. *migrate TC4D7 → TC334*)

1. **New directory.** `ads.create_project` in a **fresh** workspace for the
   target device. Never overwrite the source project in-place — leftover
   SSW configs and build artifacts cause link errors. Copy only your
   application `.c`/`.h` into the new workspace.
2. **Research API differences.** Search iLLD headers for both source and
   target devices to confirm peripheral names and API signatures (see
   skill `aurix-illd-lookup`). Do not guess — cross-family moves
   (TC4x↔TC3x↔TC2x) rename entire modules and change function signatures.
3. **Resolve pins.** Check iLLD PinMap headers for the **target** device
   to find the correct LED / UART / peripheral pins on the target board.
   Never assume pins are the same across boards.
4. **Global replace.** `grep_search` the workspace for every source-family
   API and fix **all files in one pass** (Cpu0–CpuN, all app files). Do not
   fix one file at a time.
5. **Clean build.** Delete `build/` before the first target build.
6. **Unsupported peripherals** — if the source uses a peripheral absent on
   the target, stop and inform the user before proceeding.