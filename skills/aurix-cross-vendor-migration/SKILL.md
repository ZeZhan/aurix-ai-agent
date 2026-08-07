---
name: aurix-cross-vendor-migration
description: Analyze a third-party automotive MCU demo (e.g. NXP, ST, Renesas, TI), decide whether a target Infineon AURIX device can reproduce the same observable behaviour, grade feasibility, design a functional-equivalent port with an approval gate, migrate + build + flash, and generate an evidence-backed PORTING_REPORT.md. Use when the user drops a source-vendor project/example into the workspace and asks to evaluate, benchmark, or port it to AURIX.
---

# Cross-vendor benchmarking + functional port to AURIX

**This is functional re-implementation, not source translation.** Startup flow,
interrupt model, peripheral ownership, cache coherency and hardware wiring rarely
transfer mechanically. Never present this as "any code, one-click port." Default
to re-implementing the *behaviour* against iLLD; the report must state which parts
are concept mappings and which code comes from official Infineon examples.

## Separation of concerns

- **This skill** owns: behaviour extraction, device selection, feasibility grading,
  resource-ownership analysis, phase orchestration, user approvals, exception
  decisions (repair / fall back / stop), the evidence ledger, and report generation.
- **Existing MCP tools** do the real work — do not re-implement them:
  `examples.*` (find/read examples), `illd.*` (provision/lookup), `ads.*`
  (scaffold), `build.*` (compile), `flash.*` (program), `aurix_debug_*` (inspect).

## Principle: behaviour first

Before any API mapping, write down **what the demo must be observed to do** —
inputs, outputs, timing, and exception behaviour. Map APIs only after that.
Skipping this yields code that compiles but is not behaviourally equivalent.

## Workflow

Create a visible checklist (task-list/Todo) before the first MCP call. **Your
first action is to write the evidence ledger file to disk** —
`.aurix-ai/migration/<task>.json` (pick `<task>` as a short slug, e.g.
`nxp-blinky-tc375`) — using the file-write tool, then append to it at every phase.
**The ledger is mandatory: create the file even for a trivial one-LED port.** It
is a real file, not in-memory state; the report in step 17 is rendered from it, so
it must already exist on disk. (Resumability = re-reading this file + the checklist.)

1. **Create the migration task + ledger file.** Write
   `.aurix-ai/migration/<task>.json` to disk **now** (full schema under *Evidence
   ledger* below) with the request, constraints, and empty `capabilities`/`claims`
   arrays. Every later step appends to this same file.
2. **Acquire & register the source example.** Read the folder the user placed
   in the workspace (`project.scan` + `#codebase`). Record source, and its
   **license / provenance / permitted use** (see governance below).
3. **Extract observable behaviour.** Inputs, outputs, timing, data flow, and
   exception/fault behaviour. This is the contract the port must satisfy.
4. **Analyse HW + SW dependencies.** Identify vendor / MCU / SDK (fingerprints
   below), peripherals, clocks, pins, ISR/DMA usage, external components.
5. **Match to AURIX device capability.** Select a target device (ask if not given
   — Hard rule 6; do not guess). Verify each capability with `aurix-illd-lookup`.
6. **Emit a feasibility grade** per capability and overall (5 levels below), each
   with evidence, assumptions, risks and confidence — written to the ledger.
7. **Produce the design.** Peripheral / pin / API / multi-core mapping + the
   resource-ownership table. Flag each mapping *equivalent / approximate / trade-off*.
8. **User approval of the design.** Stop and present the plan + ownership table;
   proceed only after explicit approval.
9. **Create a dedicated project folder — never scaffold at the workspace root.**
   Call `ads.create_project` with `workspace` = a **new subfolder** named
   `aurix-port-<task>/` (reuse the ledger `<task>` slug). All generated output
   (`Libraries/iLLD`, `Configurations`, `Lcf`, the Makefile, sources) must land
   **inside that subfolder** — never in the workspace root, and never inside the
   source-vendor sources (their SDK/linker/startup cause link errors). Copy only your
   new AURIX `.c`/`.h` into that subfolder.
10. **Implement.** Re-implement the behaviour with iLLD, per the concept map;
    verify every signature/struct/pin against iLLD headers (`examples.*`,
    `aurix-illd-lookup`). Reuse official example subsystems (Hard rule 5).
11. **Static check** → **12. Build** — run `build.run` with `workspace` set to the
    `aurix-port-<task>/` folder (first-error-first, max 3 repairs; missing iLLD ⇒
    `illd.provision`; `-mcpu` error ⇒ re-scaffold).
13. **Pre-flash diagnostics.** Run the prerequisite checklist below before asking
    to flash. (Until a `flash.preflight` MCP tool exists, verify verbally and
    report any item you could not confirm.)
14. **User confirmation to flash**, then **15. Flash** (`flash.program`). If the
    user said *build only* / *do not flash*, stop after build and report the ELF.
16. **Runtime verification.** Use `aurix_debug_*` for L5. When the user supplies
    later evidence (L5/L6 results, waveform/timing/bandwidth confirmed), **update
    the ledger** (`verificationReached` + a new claim) **and re-render
    `PORTING_REPORT.md`** so every affected part reflects the new result — including
    `verificationReached`, the Verification section, and any "to verify on HW" items
    that are now confirmed. Raise the level as far as evidence allows (see L0–L6).
17. **Write `PORTING_REPORT.md` to the workspace root** — an actual file, using
    the file-write tool, rendered from the on-disk ledger (not an ad-hoc chat
    summary). Confirm `.aurix-ai/migration/<task>.json` is current first. **Always
    write this file — even on NO-GO, INSUFFICIENT_EVIDENCE, or build-only.** The
    task is complete only when **both** the ledger JSON **and** `PORTING_REPORT.md`
    exist on disk; do not report success until both files are written. Include the
    AURIX-vs-source comparison section only if the port is non-trivial (see
    *AURIX-vs-source comparison* below); for a trivial single-peripheral demo,
    omit it with a one-line note.

## Feasibility levels (not just yes/no)

- `SUPPORTED_DIRECTLY` — AURIX + iLLD cover it with equivalent peripherals.
- `SUPPORTED_WITH_ADAPTATION` — achievable by re-architecting (different
  peripheral, pin, or software approach).
- `SUPPORTED_WITH_EXTERNAL_HARDWARE` — needs an added component (transceiver,
  PHY, level shifter, external ADC, etc.).
- `INSUFFICIENT_EVIDENCE` — cannot decide yet; state exactly what is missing.
- `NOT_SUPPORTED` — a required capability has no AURIX path on the target device;
  name the blocker and, if known, an AURIX device that would support it.

Every conclusion carries **evidence, assumptions, risks, confidence**.

## Resource-ownership check (do this before design approval)

Structure ownership explicitly — this is where AURIX ports fail silently:

| Resource | Owner (core/module) | Notes / conflicts |
|---|---|---|
| Peripheral instances | | overlap across cores? |
| ISR / interrupt priorities | | vector/SRC assignment, priority clashes |
| DMA channels | | channel ownership, triggers |
| Pins / ports | | alt-function, board mapping |
| Shared memory / buffers | | which core writes, sync |
| Cache regions | | coherency / non-cached buffers for DMA |
| CPU cores | | who runs what; no cross-core register writes |

Cross-core register access, unowned ISR handling, or DMA/pin double-ownership
must be caught here — not at runtime.

## Evidence ledger

**Mandatory, on-disk file** at `.aurix-ai/migration/<task>.json`. Create it in
step 1 and append at every phase. The report (step 17) is a rendered view of this
file — if the file does not exist, the port is not complete. Full schema:

```json
{
  "task": "nxp-blinky-tc375",
  "source": { "vendor": "NXP", "mcu": "S32K144", "sdk": "MCUXpresso",
              "license": "<license>", "use": "<permitted use>" },
  "target": "KIT_A2G_TC375_LITE",
  "overallFeasibility": "SUPPORTED_DIRECTLY",
  "verificationReached": "L4",
  "capabilities": [
    { "name": "LED GPIO output", "sourceApi": "GPIO_PinWrite",
      "aurixIlld": "IfxPort", "level": "SUPPORTED_DIRECTLY" }
  ],
  "claims": [
    { "claim": "TC375 can reproduce the blinky behaviour", "status": "verified",
      "evidence": ["device capability", "iLLD API", "build", "flash"],
      "confidence": 0.95 }
  ]
}
```

Each claim records evidence, status and confidence. Add a claim as each phase
produces evidence (capability match, build success, flash success, debugger).

## Verification levels (flash success != demo success)

- **L0** capability & documentation match
- **L1** design & resource-ownership check pass
- **L2** static check pass
- **L3** build success
- **L4** flash success
- **L5** debugger observes expected state (`aurix_debug_*`)
- **L6** external instrument confirms waveform / bandwidth / timing (user-only)

Report the highest level reached. L4 alone does not mean the demo runs. The report
is a **live view of the ledger** — whenever verification evidence changes (e.g. the
user confirms L6 after the initial run), update the ledger and **re-render the whole
`PORTING_REPORT.md`**; never leave any part of the report stale or contradicting
the latest evidence.

## Pre-flash diagnostics (prerequisite checklist)

Confirm before flashing (verbally until a dedicated MCP checker exists): Makefile
and ELF present · debug probe connected · `icas` service running · Flasher path &
version · target chip matches the selected device · chip is connectable · user
authorised the flash. Report any item you could not verify.

## License / provenance governance

Record the source project's origin, license, and permitted use in the ledger.
Default to **functional re-implementation**; do not copy source-vendor code into
the AURIX project. In the report, clearly separate concept mappings from code that
originates in official Infineon examples.

## Vendor / SDK fingerprints

- **NXP** — MCUXpresso: `fsl_*.h`, `GPIO_PinWrite`, `CLOCK_*`, `SDK_DelayAtLeastUs`,
  `FLEXCAN_*`, `LPUART_*`, `LPSPI_*`, `edma_*`. S32 SDK: `Siul2_*`, `PINS_DRV_*`,
  `FLEXCAN_DRV_*`, `.mex` config.
- **ST** — SPC5 / Chorus / Stellar: `spc5*`, `SIUL2`, `LINFlexD`, `DSPI`. (STM32
  HAL: `HAL_GPIO_*`, `stm32*_hal.h`, `TIM_HandleTypeDef`.)
- **Renesas** — RH850: `r_*`, e2 studio / SC, `Port`, `TAUB/TAUD`, `RLIN3`, `CSIH`,
  `RS-CANFD`. RA/RX FSP: `R_IOPORT_*`, `R_GPT_*`, `R_SCI_*`, `R_SPI_*`.
- **TI** — Hercules TMS570/RM (HALCoGen): `gioSetBit`, `sciSend`, `hetInit`,
  `canTransmit`. C2000: `GPIO_writePin`, `EPWM_*`, `SCI_*`, `driverlib`.

## Peripheral concept map -> AURIX iLLD

| Source concept (NXP / ST / Renesas / TI) | AURIX iLLD |
|---|---|
| GPIO / Port / SIUL2 / gio | `IfxPort` |
| PWM / timer output — eMIOS, FTM, ePWM, GPT, TAUx, HET | `IfxGtm_Tom`, `IfxGtm_Atom` |
| UART — LPUART, LINFlexD, SCI, RLIN3, R_SCI | `IfxAsclin_Asc` |
| SPI — LPSPI, DSPI, CSIH, R_SPI | `IfxQspi_SpiMaster` |
| I2C — LPI2C, IIC | `IfxI2c` |
| ADC — ADC ETC, EQADC, SARADC | `IfxEvadc_Adc`, `IfxEdsadc` |
| CAN / CAN-FD — FlexCAN, M_CAN, RS-CANFD, DCAN | `IfxCan` (MCMCAN) |
| DMA — eDMA, DMA | `IfxDma` |
| Clock / RCC / CGM / MC_CGM | `IfxScuCcu` |
| Interrupt — NVIC, INTC | `IfxSrc` + CPU ISR (`IFX_INTERRUPT`) |
| Ethernet — ENET, GMAC | `IfxGeth` |
| Watchdog | `IfxScuWdt` |
| Delay / busy-wait | `wait()` / `IfxStm` |

Module names differ across AURIX families (`TC2xx`/`TC3xx`/`TC4xx`) — always
confirm for the *target* device before writing code.

## AURIX-vs-source comparison (conditional)

Add a comparison of our AURIX port against the original source-vendor demo **only
when the port is non-trivial**. Non-trivial = any of: ≥2 peripherals/subsystems,
multicore, DMA, a comms/networking peripheral (UART/SPI/I2C/CAN/Ethernet), a
real-time/timing constraint, safety relevance, or any capability graded below
`SUPPORTED_DIRECTLY`. For a trivial single-peripheral demo (e.g. blinky, one GPIO
toggle), **omit it** and add a one-line note ("trivial demo; comparison omitted").

Keep it **evidence-based and honest — not marketing**. Only claim an AURIX
advantage the port actually uses or benefits from; record each point in the ledger
with evidence/confidence. Cover both sides:
- **Advantages leveraged** by the AURIX port (e.g. lockstep safety cores, extra
  cores, GTM timer flexibility, EVADC/EDSADC, HSM, memory protection) — only if
  the port genuinely exercises or gains from them.
- **Disadvantages / trade-offs** of the port (approximations, external hardware
  needed, more complex init, different pins, higher resource cost, items still to
  verify on hardware).

## `PORTING_REPORT.md` template (write this file to the workspace root, rendered from the ledger)

```markdown
# Cross-Vendor Migration Report

- **Source:** <vendor> <MCU> (<SDK>) — license: <license> / use: <permitted use>
- **Target:** <AURIX device / board>
- **Overall feasibility:** SUPPORTED_DIRECTLY | SUPPORTED_WITH_ADAPTATION |
  SUPPORTED_WITH_EXTERNAL_HARDWARE | INSUFFICIENT_EVIDENCE | NOT_SUPPORTED
- **Verification reached:** L0..L6
- **Build:** success (<elf>) | failed | not attempted   **Flash:** success | not requested | failed

## Observable behaviour (the contract)
<inputs / outputs / timing / exception behaviour>

## Feasibility per capability
| Capability | Source API | AURIX iLLD | Level | Evidence | Confidence | Risk |
|---|---|---|---|---|---|---|

## Resource ownership
<peripheral / ISR / DMA / pin / shared-mem / cache / core table>

## Design decisions & trade-offs
<pin/clock/multi-core plan; equivalent vs approximate vs trade-off; example reuse>

## Verification
<what each level confirmed; what the user must still verify (L6)>

## AURIX vs source (include only if non-trivial; else "trivial demo; comparison omitted")
| Aspect | Source demo | Our AURIX port | Note |
|---|---|---|---|
| Functional equivalence | | | |
| Advantages leveraged | | | |
| Trade-offs / disadvantages | | | |

## Provenance
<what is concept-mapped vs sourced from Infineon official examples>

## Open items / NO-GO reason
<blockers, missing evidence, or an AURIX device that would support it>
```
