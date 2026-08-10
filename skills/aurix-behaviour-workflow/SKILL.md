---
name: aurix-behaviour-workflow
description: Implement a hardware behaviour on AURIX (blink LED, configure PWM, UART, SPI, ADC, timer, interrupt, DMA, etc.). Use when the user asks to write code that drives a peripheral, generates output, reads sensors, or produces observable behaviour on an AURIX TriCore target.
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
only when requested. Update each item as it starts and completes.

1. **Decompose** the request into every concrete parameter (count, frequency,
   pin, peripheral, baud rate, etc.). Implementation must cover all of them.
   Also identify which **subsystems** are involved (display, comms, sensing …).
2. **Research in parallel.** In the first turn launch `examples.search`
   + `#codebase` together. Also call `documentation.search` with the explicit
   target `device` whenever implementation depends on hardware facts such as
   peripheral availability, clock/timing limits, pin or board connectivity,
   register behaviour, electrical constraints, or documented errata. Treat its
   physical-page citations as factual evidence; if it abstains, do not guess.
   Use examples and iLLD headers for implementation patterns and exact APIs (see
   skill `aurix-illd-lookup`), not as substitutes for device documentation.
   Cap follow-up research at 2–3 additional rounds; use
   `examples.read_source` only for the most relevant hit. For
   each subsystem, **classify** the best-matching example as *full-reuse*,
   *partial-reuse*, or *reference-only* (see Hard rule 5 in
   copilot-instructions.md).
3. **Setup** — follow Hard rule 1 based on the reuse classification from step 2.
4. **Write application code.** Start from the skeleton's or imported example's
   `Cpu0_Main.c`; extend the existing init sequence.
5. **Build** (`build.run`). On failure, read the **first** error and fix the
   root cause — typically a source typo, not the Makefile. Max 3 repair
   iterations; if a `-mcpu`/toolchain-flag error appears, regenerate via
   `ads.create_project` rather than hand-editing. Missing iLLD source ⇒
   `illd.provision`.
6. **Flash only when requested.** If the user says *do not flash*, *build
   only*, or equivalent, stop after a successful build and report the ELF.
   Otherwise run `flash.program` when hardware programming is part of the request.

For factual questions (e.g. *max TOM frequency?*), call
`documentation.search` with the explicit device and answer from its cited
evidence; use `examples.*` or iLLD headers only to supplement API details. Do
**not** scaffold a project. If the request implies behaviour on hardware, treat
it as a code task.