---
name: aurix-behaviour-workflow
description: Implement a hardware behaviour on AURIX (blink LED, configure PWM, UART, SPI, ADC, timer, interrupt, DMA, etc.) and hand requested runtime verification to AURIX Debug MCP. Use when the user asks to write code that drives a peripheral, generates output, reads sensors, or produces observable behaviour on an AURIX TriCore target, including build-flash-verify requests.
---

# Behaviour workflow (e.g. blink LED, PWM, UART, ADC)

If the source project targets another vendor's MCU (NXP, ST, Renesas, TI), use
`aurix-cross-vendor-migration` instead.

1. **Research.** In the first turn, run `examples_search` and `#codebase`
   together. Then look up only the facts the code needs, each from its source:
   - **Board pins and active levels**, when the code uses a board signal (LED,
     button, potentiometer, transceiver …): `documentation_search` with `board`,
     the project's `board_pin_label.bpl`, or the official board example's
     `pin.h`. Cite the page in a code comment.
   - **APIs, config structs, enums, pin symbols, registers:** iLLD in the
     project's `Libraries/` (skill `aurix-illd-lookup`). Find the header by name
     and search inside it; never search all of `Libraries/`.
   - **Clock, timing or electrical limits and errata** that the examples and
     iLLD do not settle: `documentation_search` with the device. Numbers in iLLD
     comments are not specifications. If the documentation does not cover a
     fact, say so instead of guessing.

   Read only the most relevant example; at most 2–3 further research rounds.
2. **Set up** the project with Hard rule 1, reusing examples per Hard rule 5.
3. **Write the code.** Build on the generated or imported code: keep its startup
   sequence, put peripheral code in its own `.c`/`.h` (or the example's), and run
   on CPU0 unless the request asks for other cores. Cover every requested
   parameter. Before the first build, also update comments and READMEs from an
   imported example that no longer describe the code.
4. **Build** with `build_run`. Fix the first error first, at most 3 rounds. For
   compiler-flag or Makefile errors, rerun `ads_create_project`; do not edit the
   Makefile.
5. **Flash and verify only when asked.** Runtime verification follows
   [aurix-debug-workflow](../aurix-debug-workflow/SKILL.md); build and flash
   success are not runtime evidence.
6. **Report** the changed files, the source of each pin, the build and flash
   results and, if verified, each check with the values read. After flashing,
   change code only to fix a real defect.