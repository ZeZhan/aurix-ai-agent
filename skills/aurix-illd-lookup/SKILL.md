---
name: aurix-illd-lookup
description: Find exact iLLD symbols in the project's own Libraries/ - driver function signatures, config struct fields and defaults, enums, pin-map symbols for the board's package, register and bitfield names, base addresses and instance counts. Use before writing or fixing iLLD calls, when choosing a pin symbol, or when a build reports an undeclared iLLD identifier. Not for clock/timing/electrical limits, errata or board wiring (use documentation_search).
---

# iLLD lookup

iLLD is the authority for **what the code can call**: function names and
signatures, config struct fields, enum values, pin-map symbols, register and
bitfield names, module base addresses and instance counts. It is **not** a
source for hardware facts - clock/timing/electrical limits, errata, board
wiring - even when a comment states a number (a TC3xx DTS comment says
"100 uS maximum"; the manual gives up to 2.7 ms). Take those from
`documentation_search`.

## Which iLLD

Use only the iLLD the project compiles: `<project>/Libraries/`. Example-bundled
and IDE iLLD versions differ (e.g. 2.2.0 vs 2.7.0 for TC4D7), and so can their
APIs; the version is in `Libraries/**/IfxLldVersion.h`. Before a project exists,
read the template `~/.aurix-agent/device_projects/<dir>/Libraries/` (`<dir>` as
reported by `ads_create_project`, e.g. `TC4DA`) or use `examples_read_source`.
The iLLD inside ADS/ACS installations is zipped and cannot be searched.

## Where things are

`<dir>` is the device or family folder (`TC4DA`, `TC4xx`, `TC37A`, `TC3xx`, ...);
list `Libraries/iLLD/` once. `<core>` is `Tricore` on TC2xx/TC3xx. On TC4x, drivers
are split: `CpuGeneric` (Asclin, Port, Adc, Dma, Egtm, ...) and `Tricore` (Cpu,
Stm, Can, Qspi, Scu, ...). If unsure, find the file by name.

| Need | Where |
|---|---|
| Driver API, config struct | `iLLD/<dir>/<core>/<Module>/<Sub>/Ifx<Module>_<Sub>.h` (e.g. `Asclin/Asc/IfxAsclin_Asc.h`); low level: `<Module>/Std/Ifx<Module>.h` |
| Config defaults | `Ifx<Module>_<Sub>_initModuleConfig()` in the matching `.c` |
| Pin symbols | `iLLD/<dir>/<core>/_PinMap/Ifx<Module>_PinMap.h`; on TC4x the symbols are in the package file `Ifx<Module>_PinMap_[TC4Dx_]<PACKAGE>.h` |
| Instance counts, module tables | `iLLD/<dir>/<core>/_Impl/Ifx<Module>_cfg.h` (e.g. `IFXDMA_NUM_CHANNELS`) |
| Registers, bitfields | `Infra/Sfr/<dir or device>/[_Reg/]Ifx<Module>_regdef.h` (bitfields), `_reg.h` (`MODULE_<X>` addresses), `_bf.h` (bit positions) |
| Standard interfaces (DPipe, Timer) | `Service/CpuGeneric/StdIf/` |
| Project configuration | `Configurations/Ifx_Cfg.h` (outside `Libraries/`) |

## How to search

1. Find the file by name, e.g. glob `Libraries/**/IfxAsclin_Asc.h`.
2. Search for the symbol inside that file or its module folder; read only the
   matching part (a struct definition, the full enum, the `initModuleConfig`
   defaults).
3. Never search the whole `Libraries/` tree for a pattern: it is 20-45 MB,
   mostly register headers of up to several MB, and such searches have timed
   out after 28 s.

## Pins

1. **Which pin** a board signal uses and its active level come from the board
   documentation (`documentation_search` with `board`), the project BPL
   (`board_pin_label.bpl`) or an official example's `pin.h` for that board -
   never from a pin map, which lists every possible pin of the chip.
2. **The symbol** comes from the pin map of the project's package. On TC4x find
   `IFX_PIN_PACKAGE_*` in the Makefile defines, `Configurations/Ifx_Cfg.h` or
   the board's `pin.h` (`BGA292_COM` for the TC4D7 lite Kit; `Ifx_Cfg.h` may
   spell it `LFBGA292_COM`, file names never use the `LF` prefix), and search
   `Ifx<Module>_PinMap_[TC4Dx_]<PACKAGE>.h`. Without a define, iLLD falls back
   to `BGA436_COM`; 114 of its 417 ASCLIN symbols do not exist on BGA292.