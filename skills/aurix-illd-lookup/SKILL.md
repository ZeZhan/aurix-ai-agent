---
name: aurix-illd-lookup
description: Look up iLLD API signatures, structs, register definitions, or peripheral driver details by searching iLLD header files directly. Use when examples.read_source does not cover the needed API, or when you need to verify function signatures, config structs, or module availability for a specific AURIX device family.
---

# iLLD lookup (direct header search)

When you need to look up iLLD API signatures, structs, or registers that are
not covered by `examples.read_source`, search the iLLD headers **directly**
using terminal commands or `grep_search` on the paths below.

## iLLD locations (in priority order)

1. Current workspace: `Libraries/iLLD/` (if project already has iLLD)
2. ADS bundled iLLD: `C:\\Infineon\\<ADS-version>\\build_system\\bundled-artefacts-repo\\project-initializer\\tricore-tc<N>xx\\<ver>\\iLLDs\\Full_Set\\`
3. GitHub cache: `~/.aurix-agent/illd_cache/illd_release_tc<N>x/src/`

## iLLD directory structure

```
BaseSw/iLLD/TC<X>xx/Tricore/<Module>/<SubModule>/
```

Example: `BaseSw/iLLD/TC3xx/Tricore/Evadc/Adc/IfxEvadc_Adc.h`

## Search strategy

1. First try `grep_search` in the workspace `Libraries/iLLD/` path.
2. If not found, check the ADS bundled path or GitHub cache.
3. Search for the module name (e.g. `IfxGtm_Tom`) to find the relevant header.
4. Once found, read the header to extract function signatures and config structs.
5. Pay attention to the device family suffix (`TC2xx`, `TC3xx`, `TC4xx`) —
   APIs differ across families.