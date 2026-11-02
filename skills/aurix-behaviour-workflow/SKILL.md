---
name: aurix-behaviour-workflow
description: Implement a hardware behaviour on AURIX (blink LED, configure PWM, UART, SPI, ADC, timer, interrupt, DMA, etc.) and hand requested runtime verification to AURIX Debug MCP. Use when the user asks to write code that drives a peripheral, generates output, reads sensors, or produces observable behaviour on an AURIX TriCore target, including build-flash-verify requests.
---

# Workflow for behaviour requests (e.g. *blink LED*, *configure PWM*)

**Route cross-vendor migrations first.** If the source project or example targets
a third-party MCU or SDK (for example NXP, ST, Renesas, or TI) and the requested
target is AURIX, read and follow the `aurix-cross-vendor-migration` skill instead
of treating the task as a normal AURIX behaviour implementation. That skill owns
feasibility grading, functional re-implementation, provenance, approval gates,
and the migration evidence ledger.

**Keep the work visible.** Before the first MCP call in a multi-step coding
task, use the available task-list/Todo tool to create a visible checklist.
Include research, setup/import, application edit, and build; include flash
and runtime verification when requested. Update each item as it starts and
completes. If verification is requested, read
[aurix-debug-workflow](../aurix-debug-workflow/SKILL.md) early to plan the
observations and resolve any existing session before programming.

1. **Decompose** the request into every concrete parameter (count, frequency,
   pin, peripheral, baud rate, etc.). Implementation must cover all of them.
   Also identify which **subsystems** are involved (display, comms, sensing …).
   For requested runtime verification, list each assertion, the variable or
   register to observe, and the needed samples. Source configuration, build
   success and flash success are not runtime evidence.
2. **Research in parallel.** In the first turn launch `examples_search`
   + `#codebase` together. Also call `documentation_search` with the explicit
   target `device` whenever implementation depends on hardware facts such as
   peripheral availability, clock/timing limits, pin or board connectivity,
   register behaviour, electrical constraints, or documented errata. Treat its
   physical-page citations as factual evidence; if it abstains, do not guess.
   Use `documentation_read` for truncated chunks. The board hardware revision
   is detected from the connected kit (shown in the result, or call
   `flash_list_devices`); ask the user only if no matching kit is connected.
   TC4x kits need no revision: their board documentation applies to all.
   Use examples and iLLD headers for implementation patterns and exact APIs,
   not as substitutes for device documentation. Route each fact to its source:
   - **iLLD in the project's `Libraries/`** (skill `aurix-illd-lookup`):
     function signatures, config struct fields and defaults, enums, pin-map
     symbols, register/bitfield names. Glob the header by name, then search
     inside it; never search the whole `Libraries/` tree.
   - **Board documentation / BPL / board example `pin.h`**: which pin a board
     signal uses and its active level; then take the symbol from the pin map
     of the project's package.
   - **`documentation_search`**: clock/timing/electrical limits, register
     behaviour, errata. Numbers in iLLD comments are not specifications.

   Cap follow-up research at 2–3 additional rounds; use
   `examples_read_source` only for the most relevant hit. For
   each subsystem, **classify** the best-matching example as *full-reuse*,
   *partial-reuse*, or *reference-only* (see Hard rule 5 in
   copilot-instructions.md).
3. **Setup** — follow Hard rule 1 based on the reuse classification from step 2.
   After a successful `examples_import`, use its Makefile-readiness line or
   `hasMakefile` field. Import attempts regeneration when dependencies, device
   configuration and ADS are available. If a Makefile exists, try building
   without another scan or scaffold solely to confirm/create it. A missing
   Makefile still requires `ads_create_project`; other missing dependencies or
   toolchain errors may also require setup repair.
4. **Write application code.** Start from the skeleton's or imported example's
   `Cpu0_Main.c`; extend the existing init sequence. Avoid unrelated cosmetic
   cleanup. Diagnose warnings that affect correctness, prototypes, types or
   ABI before flashing, including warnings in official examples.
5. **Build** (`build_run`). Its result already carries the exit code, the
   extracted error/warning lines and the output tail; do not re-read the raw
   log unless diagnostic context is missing. `logTruncated` marks a preview;
   `logFiles` points to full logs and `logFileErrors` reports incomplete or
   unavailable logs. On failure, read the **first** error and
   fix the root cause — typically a source typo, not the Makefile. Max 3 repair
   iterations; if a `-mcpu`/toolchain-flag error appears, regenerate via
   `ads_create_project` rather than hand-editing. Missing iLLD source ⇒
   `illd_provision`.
6. **Flash only when requested.** For *build only*, stop after a successful
   build and report the ELF. For *do not flash*, skip programming; if inspection
   is also requested, follow the Debug Skill without enabling flashing.
   Otherwise run `flash_program` when hardware programming is part of the request.
   If a debug session already owns the target, follow the Debug Skill's release
   and authorization rules before separate programming.
7. **Verify with the debugger when requested.** Discover AURIX Debug MCP and
   follow [aurix-debug-workflow](../aurix-debug-workflow/SKILL.md). Reuse an
   existing suitable session; otherwise hand off the built ELF, open workspace,
   actual DAS device selection and assertions for an authorized startup.
   Do not substitute the board name for the DAS device name.
   Keep this step even after successful separate flashing. Debug MCP 0.1.31+
   requires flashing and Agent `-f` for new sessions; do not send a `flash`
   parameter. Prior programming in step 6 does not skip this startup flash.
   If no-flash/preserve-scene instructions apply, reuse an existing suitable
   session or ask about manual UI startup; do not call `debug_start`.
   Confirm any outstanding startup/reprogramming authorization before acting.
   Only a request for runtime verification/debugging enters this step; the
   presence of Debug MCP alone does not turn a flash-only task into debugging.
8. **Report each requested assertion.** Separate implementation/build/programming
   results from debugger observations. Mark each assertion supported,
   contradicted or unverified, with actual values and limitations. For a
   counter "increasing", collect at least two fresh samples separated by
   authorized execution; one nonzero reading is insufficient. Use the Debug
   Skill for execution timing, register interpretation and final session state.
   On failure, preserve the actual tool input and structured error evidence;
   do not replace missing measurements with expected values.

**Tool discovery.** A tool search returns only about five tools, so search
with the exact names of the few tools needed next (for example
`ads_create_project examples_import`, then `build_run flash_program`), not one
long list. A server's tools are available together: if any tool of a server was
returned or called successfully, its other tools exist too; search for them by
exact name. Treat operations as unavailable only when an exact-name search
returns none of that server's tools; then report exactly which operations are
missing and suggest checking MCP server status or refreshing its tools. Do not
loop on searches, delegate discovery to subagents, or bypass the interface.

For factual questions (e.g. *max TOM frequency?*), call
`documentation_search` with the explicit device and answer from its cited
evidence. State any claim the evidence does not support. iLLD headers can
answer symbol-level facts (register/bitfield names, base addresses, instance
counts) and supplement API details, but not limits, timing or errata. Do
**not** scaffold a project. If the request implies behaviour on hardware, treat
it as a code task.