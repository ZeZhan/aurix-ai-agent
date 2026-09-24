# Reviewed Board Facts

This small index contains manually reviewed factual summaries, not complete manuals
or automatically extracted schematic connections. Original PDFs are not distributed.

## TC375 Lite V2

- Board: `KIT_A2G_TC375_LITE`, hardware `V2` only. No subrevision equivalence is assumed.
- Official directory: https://documentation.infineon.com/aurixtc3xx/docs/nmq1702364076336
- Manual: https://www.infineon.com/assets/row/public/documents/10/44/infineon-aurix-tc375-lite-kit-usermanual-en.pdf
- Title: AURIX lite Kit V2 Board User's Manual; document revision 2.2, 2022-04-14.
- PDF SHA-256: `319b88a14b719e122d236fdc40f0526c64e0d8a6e456a84d5cef282a82ec2195` (27 pages).
- Reviewed 2026-09-23: text extraction and rendered physical pages 10 and 11 checked independently.

| Signal | Pin | Active Level | Section / Physical PDF Page |
| --- | --- | --- | --- |
| LED1 | P00.5 | Low, on | 2.2 / Table 2 / 10 |
| LED2 | P00.6 | Low, on | 2.2 / Table 2 / 10 |
| BUTTON1 | P00.7 | Low, pressed | 2.2 / Table 4 / 11 |

Table 4's R33 footnote applies to the R32/AN0 potentiometer, not BUTTON1.
Reset, emergency-stop LED3, miniWiggler LEDs, voltage/current limits and pull-up
configuration are outside this reviewed subset. Missing hardware revision is not
inferred from a chip model, board selection, BPL filename, or document revision.

## TC4D7 Lite V2.x

- Board: `KIT_A3G_TC4D7_LITE`. The manual explicitly covers hardware `2.x` (physical page 1).
- Official page: https://www.infineon.com/evaluation-board/KIT-A3G-TC4D7-LITE
- Manual: https://www.infineon.com/assets/row/public/documents/10/44/infineon-kit-a3g-tc4d7-lite-aurix-lite-kit-user-guide-usermanual-en.pdf
- Document: `002-41555 Rev. *A`, 2026-05-12, not the website's listing revision/date.
- PDF SHA-256: `36b6084b77b8a35a2daa17d00ef05d01c0ef593f81e94f91dd2275e439f72572` (41 pages).
- Reviewed 2026-09-24: reused the existing chip-index excerpt and checked the official PDF text/rendered page 9.

| Signal | Pin | Active Level | Section / Physical PDF Page |
| --- | --- | --- | --- |
| LED1 | P03.9 | Low, on | 2.2 / Table 3 / 9 |
| LED2 | P03.10 | Low, on | 2.2 / Table 3 / 9 |
| BUTTON1 (manual: Button) | P03.11 | Low, pressed | 2.2 / Table 5 / 9 |

The local BSP names the single user button `BUTTON1`. R35 only concerns the
potentiometer. The documented `2.x` series accepts `2`, `2.0`, `2.1`, etc.; this
does not broaden other boards' exact revisions. BPL `V2.x` is compatible with a
requested `V2.0`; absent version evidence is still unconfirmed.

## TC397 5V TFT V2.0

- Board: `KIT_A2G_TC397_5V_TFT`, hardware `2.0` only. Not TriBoard, 3.3 V, or all TC397 boards.
- Official directory: https://documentation.infineon.com/aurixtc3xx/docs/nmq1702364076336
- Manual: https://www.infineon.com/assets/row/public/documents/10/44/infineon-applicationkitmanual-tc3x7-usermanual-en.pdf
- Title: Application Kit Manual TC3X7; document V2.0, 2018-06; page 9 section 3.1 lists the TC397 5 V variant.
- PDF SHA-256: `e375c5a29472a6c72b12e0d64ba628f09c36028ca5dc3a9baed8ac6ce481ab34` (33 pages).
- Reviewed 2026-09-24: sections 3.6/3.15/3.16 and rendered Figure 7-2. Schematic net connections were visually traced, not inferred from flattened PDF text.

| Signal | Connection | Active Level / Meaning | Evidence |
| --- | --- | --- | --- |
| D107 | P13.0 | Low, on | Section 3.15 p14; Figure 7-2 p25 |
| D108 | P13.1 | Low, on | Section 3.15 p14; Figure 7-2 p25 |
| D109 | P13.2 | Low, on | Section 3.15 p14; Figure 7-2 p25 |
| D110 | P13.3 | Low, on | Section 3.15 p14; Figure 7-2 p25 |
| S101 / RESET | MCU /PORST via Q103 | Low at /PORST, not at the switch contact | Section 3.16 p14; Figure 7-2 p25 |
| S102 / WAKE | TLF35584 WAK/ENA | High at PMIC enable/wakeup inputs | Section 3.16 p14; Figure 7-2 p25 |

Both buttons are dedicated circuits, not software-readable user GPIOs. The facts
retain `gpio: false`, `level_at`, and `usageRestriction: not_a_gpio`; do not generate
GPIO button handling from them. WAKE voltage limits and PMIC timing are not covered.
No LED1/BUTTON1 aliases are invented for this board. Use the D/S designators,
RESET/WAKE, or a generic LED/button query with `topK: 10` for all six facts.

The inspected ACS 1.0.22 TC397 BSP BPL has no LED/button labels or board header.
Installation-directory provenance can identify the board but cannot supply those
missing mappings. `bplCheck: not_mapped` preserves manual facts while requiring
confirmation; it is neither a successful match nor a conflicting pin. Project
files lacking board identity remain unverified and are never overwritten.

## Rebuild

From the standalone Python server directory, with `src` on `PYTHONPATH`:

```pwsh
python -m aurix_mcp_server.documentation_retrieval build src/aurix_mcp_server/data/board_manuals src/aurix_mcp_server/data/board_manuals/boards.sqlite
```

The JSONL records are the source of truth. Sync this directory and the modified
Python modules to the extension's bundled server after rebuilding. Existing chip
manual indexes are not modified. Runtime queries open the index without downloading
or extracting a PDF.