"""MCP tool: ads.create_project

Creates a device project template from the local ADS installation.
Extracts iLLD libraries, configuration files, linker scripts, and source stubs.

Also exports `regenerate_makefile_for_workspace()` used by examples.import.

Mirrors src/tools.adsCreateProject.ts.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from typing import Any, Optional

from ..board_pins import deploy_board_pins, format_board_pins, normalize_board, resolve_board_pins, selected_board
from ..context import load_workspace_context
from ..illd_version import detect_illd_version, format_illd_version
from ..tooldef import TextContent, ToolContext, ToolResult

# ---------------------------------------------------------------------------
# Template version — bump when Makefile/iLLD scan rules change
# ---------------------------------------------------------------------------
TEMPLATE_VERSION = "2026-05-07-v6-pinmap-generic-fix"

# ---------------------------------------------------------------------------
# Device metadata
# ---------------------------------------------------------------------------

@dataclass
class DeviceInfo:
    family: str  # "tc2xx", "tc3xx", "tc4xx"
    illd_dir: str
    cores: int
    mcpu: str
    device_selector: str
    platform: str


DEVICE_MAP: dict[str, DeviceInfo] = {
    "TC4D7": DeviceInfo("tc4xx", "TC4DA", 6, "tc4DAx", "TC4D7XQ_A-Step_MC_COM", "KIT_A2G_TC4D7_5V_TFT"),
    "TC4D9": DeviceInfo("tc4xx", "TC4DA", 6, "tc4DAx", "TC4D9XQ_A-Step_MC_COM", "KIT_A2G_TC4D9_5V_TFT"),
    "TC275": DeviceInfo("tc2xx", "TC27D", 2, "tc27xx", "TC275TP_D-Step", "KIT_AURIX_TC275_LITE"),
    "TC297": DeviceInfo("tc2xx", "TC29B", 2, "tc29xx", "TC297TA_B-Step", "KIT_A2G_TC297_5V_TFT"),
    "TC375": DeviceInfo("tc3xx", "TC37A", 3, "tc38xx", "TC375TP_A-Step", "KIT_A2G_TC375_LITE"),
    "TC377": DeviceInfo("tc3xx", "TC37A", 3, "tc38xx", "TC377TP_A-Step", "KIT_A2G_TC377_5V_TFT"),
    "TC387": DeviceInfo("tc3xx", "TC38A", 4, "tc38xx", "TC387QP_A-Step", "KIT_A2G_TC387_5V_TFT"),
    "TC389": DeviceInfo("tc3xx", "TC38A", 4, "tc38xx", "TC389QP_A-Step", "KIT_A2G_TC389_TFT"),
    "TC397": DeviceInfo("tc3xx", "TC39B", 6, "tc39xx", "TC397XA_B-Step", "KIT_A2G_TC397_5V_TFT"),
}


def _build_alias_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for device, info in DEVICE_MAP.items():
        if info.platform:
            m[info.platform.upper()] = device
        # Accept the full Infineon part number (e.g. TC375TP from
        # "TC375TP_A-Step") so callers don't have to know the short family key.
        if info.device_selector:
            m.setdefault(info.device_selector.split("_")[0].upper(), device)
    m.update({
        "KIT_AURIX_TC297_TFT_BC-STEP": "TC297",
        "KIT_AURIX_TC277_TFT_DC-STEP": "TC275",
        "KIT_AURIX_TC275_ARD_SB": "TC275",
        "KIT_AURIX_TC265_TFT_BC-STEP": "TC275",
        "KIT_AURIX_TC237_TFT_AC-STEP": "TC275",
        "KIT_AURIX_TC234_TFT_AC-STEP": "TC275",
        "KIT_A2G_TC375_ARD_SB": "TC375",
        "KIT_A2G_TC367_5V_TFT": "TC375",
        "KIT_A2G_TC334_LITE": "TC375",
        "KIT_A3G_TC4D7_LITE": "TC4D7",
    })
    return m


DEVICE_ALIAS_MAP = _build_alias_map()


def normalize_device(device: str) -> str:
    upper = device.upper()
    if upper in DEVICE_MAP:
        return upper
    alias = DEVICE_ALIAS_MAP.get(upper)
    if alias:
        return alias
    return upper


DEVICE_PROJECTS_CACHE = os.path.join(os.path.expanduser("~"), ".aurix-agent", "device_projects")

# ---------------------------------------------------------------------------
# ADS studio path resolution
# ---------------------------------------------------------------------------

ADS_STUDIO_EXECUTABLE_NAMES = [
    "AURIX-studioc.exe",
    "AURIX-studio-limitedc.exe",
    "AURIX-configuration-studioc.exe",
    "AURIX-configuration-studio-limitedc.exe",
]


def is_studio_directory(path: str) -> bool:
    if not os.path.isdir(path):
        return False
    try:
        file_names = [entry.name for entry in os.scandir(path) if entry.is_file()]
    except OSError:
        return False
    known_names = {name.lower() for name in ADS_STUDIO_EXECUTABLE_NAMES}
    return any(
        name.lower() in known_names
        or (
            name.lower().startswith("aurix-")
            and "studio" in name.lower()
            and name.lower().endswith("c.exe")
        )
        for name in file_names
    )


def discover_studio_candidates(infineon_dir: str) -> list[str]:
    candidates = [
        os.path.join(infineon_dir, "ide"),
        os.path.join(infineon_dir, "AURIX-Studio"),
    ]
    if not os.path.isdir(infineon_dir):
        return candidates

    for entry in sorted(os.listdir(infineon_dir), reverse=True):
        entry_lower = entry.lower()
        if not entry_lower.startswith(("aurix-studio", "aurix-configuration-studio")):
            continue
        install_root = os.path.join(infineon_dir, entry)
        if not os.path.isdir(install_root):
            continue
        candidates.append(install_root)
        eclipse_dir = os.path.join(install_root, "eclipse")
        if os.path.isdir(eclipse_dir):
            candidates.append(eclipse_dir)
    return candidates


def resolve_studio_dir(project_path: Optional[str] = None) -> str:
    # Try context.json
    ctx = load_workspace_context(project_path)
    configured = ((ctx.data or {}).get("toolchain") or {}).get("adsStudioPath")
    if configured:
        p = os.path.abspath(configured)
        if os.path.isfile(p):
            return os.path.dirname(p)
        if os.path.isdir(p):
            return p

    # Env var fallback
    env_path = os.environ.get("AURIX_ADS_STUDIO_PATH") or os.environ.get("AURIX_IDE_PATH")
    if env_path:
        p = os.path.abspath(env_path)
        if os.path.isfile(p):
            return os.path.dirname(p)
        if os.path.isdir(p):
            return p

    # Scan common locations
    infineon_dir = "C:\\Infineon"
    candidates = discover_studio_candidates(infineon_dir)
    candidates.append(os.path.join(os.path.expanduser("~"), "AURIX-Studio"))
    for c in candidates:
        if is_studio_directory(c):
            return c

    raise FileNotFoundError(
        "Cannot find ADS installation. Set the IDE path via the AURIX AI Agent "
        "status bar (Select IDE Path), or set toolchain.adsStudioPath in "
        ".aurix-ai/context.json, or install AURIX Development Studio to a "
        "standard location (C:\\Infineon\\ide)."
    )


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------

@dataclass
class InitializerPaths:
    root: str
    illd_zip: str
    source_templates: str
    config_templates: str
    linker_tasking: str
    linker_gcc: str


def _find_initializer_root(studio_dir: str, info: DeviceInfo) -> str:
    """Locate the template root directory. Supports full ADS and ACS (libstore) layouts."""
    # Strategy 1: Full ADS layout — build_system/bundled-artefacts-repo/project-initializer/tricore-{family}/{version}/
    pi_base = os.path.join(studio_dir, "build_system", "bundled-artefacts-repo", "project-initializer")
    family_dir = f"tricore-{info.family}"
    family_path = os.path.join(pi_base, family_dir)
    if os.path.exists(family_path):
        versions = sorted(
            [d for d in os.listdir(family_path) if os.path.isdir(os.path.join(family_path, d))],
            reverse=True,
        )
        if versions:
            return os.path.join(family_path, versions[0])

    # Strategy 2: ACS mass-market layout — libstore/DeviceFeatures/pack/{version}/
    # libstore may be sibling of studio_dir (e.g. studio_dir=.../eclipse, libstore=.../libstore)
    for base in (studio_dir, os.path.dirname(studio_dir)):
        libstore_base = os.path.join(base, "libstore", "DeviceFeatures", "pack")
        if os.path.isdir(libstore_base):
            pack_versions = sorted(
                [d for d in os.listdir(libstore_base) if os.path.isdir(os.path.join(libstore_base, d))],
                reverse=True,
            )
            for pv in pack_versions:
                candidate = os.path.join(libstore_base, pv)
                if os.path.isdir(os.path.join(candidate, "iLLDs")):
                    return candidate

    raise FileNotFoundError(
        f"Project initializer not found. Searched:\n"
        f"  - {family_path} (ADS layout)\n"
        f"  - {libstore_base} (ACS layout)\n"
        f"Ensure you have a full AURIX Development Studio or AURIX Configuration Studio installed."
    )


def find_project_initializer(studio_dir: str, info: DeviceInfo) -> InitializerPaths:
    root = _find_initializer_root(studio_dir, info)

    # Find iLLD zip
    illd_dir = os.path.join(root, "iLLDs", "Full_Set")
    illd_zips = [
        f for f in (os.listdir(illd_dir) if os.path.isdir(illd_dir) else [])
        if f.endswith(".zip") and info.illd_dir in f
    ]
    if not illd_zips:
        raise FileNotFoundError(f"No iLLD zip found for {info.illd_dir} in {illd_dir}")

    pt_base = os.path.join(root, "ProjectTemplates", info.illd_dir)
    tricore_dir = os.path.join(pt_base, "TriCore")

    # Source templates: TC4xx → TriCore/TriCore/, TC3xx → TriCore/
    nested_src = os.path.join(tricore_dir, "TriCore")
    source_templates = nested_src if os.path.exists(nested_src) else tricore_dir

    # Config templates
    nested_cfg = os.path.join(pt_base, "Configurations", "TriCore")
    flat_cfg = os.path.join(tricore_dir, "Configurations")
    config_templates = nested_cfg if os.path.exists(nested_cfg) else flat_cfg

    # Linker GCC — try GCC, Gcc, GnuC (different conventions across ADS/ACS versions)
    linker_gcc = ""
    for gcc_dir_name in ("GCC", "Gcc", "GnuC"):
        gnuc_base = os.path.join(root, "Linker_conf", gcc_dir_name, info.illd_dir)
        if os.path.isdir(gnuc_base):
            with_tricore = os.path.join(gnuc_base, "Tricore")
            # Also try "TriCore" (capital C)
            if not os.path.exists(with_tricore):
                with_tricore = os.path.join(gnuc_base, "TriCore")
            linker_gcc = with_tricore if os.path.exists(with_tricore) else gnuc_base
            break
    if not linker_gcc:
        # Fallback: use root Linker_conf even if specific folder not found
        linker_gcc = os.path.join(root, "Linker_conf")

    return InitializerPaths(
        root=root,
        illd_zip=os.path.join(illd_dir, illd_zips[0]),
        source_templates=source_templates,
        config_templates=config_templates,
        linker_tasking=os.path.join(root, "Linker_conf", "Tasking", info.illd_dir, "TriCore"),
        linker_gcc=linker_gcc,
    )


# ---------------------------------------------------------------------------
# Zip extraction
# ---------------------------------------------------------------------------

def extract_zip(zip_path: str, dest_dir: str) -> None:
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


# ---------------------------------------------------------------------------
# FreeMarker template processing
# ---------------------------------------------------------------------------

def process_ftlh(content: str, vars_dict: dict[str, str], architectures: Optional[list[str]] = None) -> str:
    if architectures is None:
        architectures = ["tricore"]
    result = content

    # 1. Process <#assign VAR = architectures?contains("x")>
    bool_vars: dict[str, bool] = {}

    def _assign_arch(m: re.Match) -> str:
        var_name = m.group(1)
        value = m.group(2)
        bool_vars[var_name] = value in architectures
        return ""

    result = re.sub(
        r'<#assign\s+(\w+)\s*=\s*architectures\?contains\("([^"]+)"\)\s*>',
        _assign_arch, result
    )
    # Remove remaining <#assign>
    result = re.sub(r"<#assign\s+[^>]*>", "", result)

    # 2. Process <#if boolVar>...</#if>
    def _bool_if(m: re.Match) -> str:
        var_name = m.group(1)
        body = m.group(2)
        if var_name in bool_vars:
            return body if bool_vars[var_name] else ""
        return m.group(0)  # leave for next pass

    result = re.sub(r"<#if\s+(\w+)\s*>([\s\S]*?)</#if>", _bool_if, result)

    # 3. Process <#if VAR == "x">...<#elseif>...<#else>...</#if>
    def _string_if(m: re.Match) -> str:
        var_name = m.group(1)
        cond_value = m.group(2)
        body = m.group(3)
        actual_value = vars_dict.get(var_name, "")

        # Split body by <#elseif ...> and <#else>
        parts: list[tuple[Optional[str], str]] = []
        splits = re.split(r"(<#elseif\s+\w+\s*==\s*\"[^\"]+\"\s*>|<#else>)", body)
        parts.append((cond_value, splits[0]))
        i = 1
        while i < len(splits):
            directive = splits[i]
            part_content = splits[i + 1] if i + 1 < len(splits) else ""
            elseif_m = re.match(r'<#elseif\s+\w+\s*==\s*"([^"]+)"\s*>', directive)
            if elseif_m:
                parts.append((elseif_m.group(1), part_content))
            else:
                parts.append((None, part_content))
            i += 2

        for cond, text in parts:
            if cond is None:
                return text
            if cond == actual_value:
                return text
        return ""

    result = re.sub(r'<#if\s+(\w+)\s*==\s*"([^"]+)"\s*>([\s\S]*?)</#if>', _string_if, result)

    # 4. Remove remaining FreeMarker directives
    result = re.sub(r"</?#[^>]*>", "", result)
    return result


# ---------------------------------------------------------------------------
# EJS-style template processing (for ACS .template files)
# ---------------------------------------------------------------------------

def process_ejs_template(content: str) -> str:
    """Process EJS-style .template files for SimpleMain (all feature flags false).

    Removes <% if (VAR) { %> ... <% } %> blocks and <%= expr %> expressions,
    since for a SimpleMain project SCR/PPU/CDSP are all undefined/false.
    """
    # Remove multi-line conditional blocks: <% if (...) { %> ... <% } %>
    # Handle nested and sequential blocks via repeated passes
    prev = None
    result = content
    while prev != result:
        prev = result
        result = re.sub(
            r'<%\s*(?:if|for)\s*\([^)]*\)\s*\{\s*%>[\s\S]*?<%\s*\}\s*%>',
            '', result
        )
    # Remove remaining EJS expression tags: <%= ... %>
    result = re.sub(r'<%=\s*[^%]*%>', '', result)
    # Remove any remaining EJS tags: <% ... %>
    result = re.sub(r'<%[^%]*%>', '', result)
    # Clean up excessive blank lines (more than 2 consecutive)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result


def _copy_template_file(src_path: str, dest_path: str) -> None:
    """Copy a file, processing .template (EJS) or .ftlc/.ftlh (FreeMarker) files."""
    name = os.path.basename(src_path)
    if name.endswith(".template"):
        raw = open(src_path, "r", encoding="utf-8", errors="replace").read()
        processed = process_ejs_template(raw)
        # Strip .template suffix for output
        out_path = dest_path[:-9] if dest_path.endswith(".template") else dest_path
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(processed)
    else:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copy2(src_path, dest_path)


# ---------------------------------------------------------------------------
# Copy helpers
# ---------------------------------------------------------------------------

def copy_dir_recursive(src: str, dest: str) -> int:
    count = 0
    os.makedirs(dest, exist_ok=True)
    for entry in os.scandir(src):
        src_path = entry.path
        dest_path = os.path.join(dest, entry.name)
        if entry.is_dir():
            count += copy_dir_recursive(src_path, dest_path)
        elif entry.is_file():
            shutil.copy2(src_path, dest_path)
            count += 1
    return count


def deploy_template_dependencies(cache_path: str, workspace_path: str) -> list[str]:
    existing_illd = os.path.join(workspace_path, "Libraries", "iLLD")
    existing_config = os.path.join(workspace_path, "Configurations", "Ifx_Cfg.h")
    existing_lcf = os.path.join(workspace_path, "Lcf")

    if os.path.isdir(existing_illd):
        if not os.path.isfile(existing_config):
            raise ValueError(
                "Workspace contains Libraries/iLLD but is missing Configurations/Ifx_Cfg.h. "
                "Refusing to mix the existing iLLD with configuration files from another "
                "ADS/ACS version."
            )
        details = ["Preserved existing Libraries/ and Configurations/ dependency bundle"]
        if os.path.isdir(existing_lcf):
            details.append("Preserved existing Lcf/")
        else:
            lcf_src = os.path.join(cache_path, "Lcf")
            if os.path.isdir(lcf_src):
                copy_dir_recursive(lcf_src, existing_lcf)
                details.append("Deployed Lcf/")
        return details

    details: list[str] = []
    for dir_name in ["Libraries", "Lcf", "Configurations"]:
        src = os.path.join(cache_path, dir_name)
        if os.path.isdir(src):
            copy_dir_recursive(src, os.path.join(workspace_path, dir_name))
            details.append(f"Deployed {dir_name}/")
    return details


# ---------------------------------------------------------------------------
# Makefile generation
# ---------------------------------------------------------------------------

ILLD_EXCLUDE_DIRS = {"ArcEV", "Scr"}


def parse_ifx_cfg_defines(cfg_path: str) -> dict[str, str]:
    content = open(cfg_path, "r", encoding="utf-8", errors="replace").read()
    device_m = re.search(r"#define\s+(DEVICE_\w+)\s+1", content)
    pin_m = re.search(r"^\s*#define\s+(IFX_PIN_PACKAGE_\w+)\s+1", content, re.MULTILINE)
    pin_name = pin_m.group(1) if pin_m else ""
    return {
        "deviceDefine": device_m.group(1) if device_m else "",
        "pinPackageDefine": pin_name,
        "pinPackageSuffix": pin_name.replace("IFX_PIN_PACKAGE_", "") if pin_name else "",
    }


def find_gcc_cross_compile_prefix(studio_dir: str) -> str:
    """Find the tricore-gcc prefix in ADS and ACS installation layouts."""
    search_dirs = [
        os.path.join(studio_dir, "tools", "Compilers"),
        os.path.join(studio_dir, "eclipse"),
        studio_dir,
    ]
    for comp_dir in search_dirs:
        if not os.path.isdir(comp_dir):
            continue
        dirs = sorted(
            [d for d in os.listdir(comp_dir) if os.path.isdir(os.path.join(comp_dir, d)) and d.startswith("tricore-gcc")],
            reverse=True,
        )
        if dirs:
            return os.path.join(comp_dir, dirs[0], "bin", "tricore-elf-").replace("\\", "/")
    return ""


def scan_c_sources(directory: str, root_dir: str, pin_package_suffix: str) -> list[str]:
    results: list[str] = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return results
    for e in entries:
        if e.is_dir() and not e.name.startswith("."):
            if e.name in ILLD_EXCLUDE_DIRS:
                continue
            results.extend(scan_c_sources(e.path, root_dir, pin_package_suffix))
        elif e.is_file() and e.name.endswith(".c"):
            rel_path = os.path.relpath(e.path, root_dir).replace("\\", "/")
            if "/_PinMap/" in rel_path:
                is_package_specific = bool(re.search(r"_PinMap_\w+\.c$", e.name))
                if not is_package_specific or not pin_package_suffix or e.name.endswith(f"_{pin_package_suffix}.c"):
                    results.append(rel_path)
            else:
                results.append(rel_path)
    return results


def scan_include_paths(root_dir: str) -> list[str]:
    result: list[str] = []
    stack = [{"dir": root_dir, "rel": ""}]
    while stack:
        item = stack.pop()
        d, rel = item["dir"], item["rel"]
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        has_headers = False
        for e in entries:
            if e.is_file() and e.name.lower().endswith(".h"):
                has_headers = True
            if e.is_dir() and not e.name.startswith("."):
                if e.name in ILLD_EXCLUDE_DIRS:
                    continue
                new_rel = f"{rel}/{e.name}" if rel else e.name
                stack.append({"dir": e.path, "rel": new_rel})
        if has_headers and rel:
            result.append(rel)

    # Add known iLLD parent include roots
    illd_roots = [
        "Libraries/Infra/Platform",
        "Libraries/Infra/Ipc",
        "Libraries/Service/CpuGeneric",
    ]
    try:
        illd_base = os.path.join(root_dir, "Libraries", "iLLD")
        for d in os.listdir(illd_base):
            if os.path.isdir(os.path.join(illd_base, d)):
                illd_roots.append(f"Libraries/iLLD/{d}/Tricore")
                illd_roots.append(f"Libraries/iLLD/{d}/CpuGeneric")
    except OSError:
        pass

    existing = set(result)
    for root in illd_roots:
        if root not in existing and os.path.exists(os.path.join(root_dir, root)):
            result.append(root)

    return sorted(result)


def scan_include_paths_for_dir(root_dir: str, top_dir: str) -> list[str]:
    result: list[str] = []
    abs_top = os.path.join(root_dir, top_dir)
    stack = [{"dir": abs_top, "rel": top_dir}]
    while stack:
        item = stack.pop()
        d, rel = item["dir"], item["rel"]
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        has_headers = False
        for e in entries:
            if e.is_file() and e.name.lower().endswith(".h"):
                has_headers = True
            if e.is_dir() and not e.name.startswith("."):
                stack.append({"dir": e.path, "rel": f"{rel}/{e.name}"})
        if has_headers:
            result.append(rel)
    return result


def _fmt_make_list(items: list[str], indent: str = "  ") -> str:
    lines = []
    for i, s in enumerate(items):
        suffix = " \\" if i < len(items) - 1 else ""
        lines.append(f"{indent}{s}{suffix}")
    return "\n".join(lines)


def find_linker_script(cache_path: str) -> str:
    gcc_dir = os.path.join(cache_path, "Lcf", "Gcc")
    if os.path.isdir(gcc_dir):
        lsl_files = [f for f in os.listdir(gcc_dir) if f.endswith(".lsl")]
        if lsl_files:
            return f"Lcf/Gcc/{lsl_files[0]}"
    return "Lcf/Gcc/Lcf_Gnuc_Tricore_Tc.lsl"


def generate_makefile(cache_path: str, info: DeviceInfo, studio_dir: str, device: str) -> list[str]:
    details: list[str] = []

    ifx_cfg_path = os.path.join(cache_path, "Configurations", "Ifx_Cfg.h")
    if not os.path.isfile(ifx_cfg_path):
        details.append("WARNING: Ifx_Cfg.h not found, skipping Makefile generation")
        return details

    cfg = parse_ifx_cfg_defines(ifx_cfg_path)
    gcc_prefix = find_gcc_cross_compile_prefix(studio_dir)

    # Scan library sources
    lib_srcs = sorted(scan_c_sources(os.path.join(cache_path, "Libraries"), cache_path, cfg["pinPackageSuffix"]))
    include_paths = scan_include_paths(cache_path)

    # Discover extra source directories
    SKIP_DIRS = {"Libraries", "Lcf", "Configurations", "build", ".git", "node_modules"}
    extra_srcs: list[str] = []
    extra_includes: list[str] = []
    try:
        for e in os.scandir(cache_path):
            if not e.is_dir() or e.name.startswith(".") or e.name in SKIP_DIRS:
                continue
            extra_srcs.extend(scan_c_sources(e.path, cache_path, cfg["pinPackageSuffix"]))
            extra_includes.extend(scan_include_paths_for_dir(cache_path, e.name))
    except OSError:
        pass

    # User source stubs
    user_srcs: list[str] = []
    for i in range(info.cores):
        f = f"Cpu{i}_Main.c"
        if os.path.isfile(os.path.join(cache_path, f)):
            user_srcs.append(f)

    # Configuration source files
    cfg_srcs = [
        f for f in [
            "Configurations/Ifx_Cfg_Ssw.c",
            "Configurations/Ifx_Cfg_SswBmhd.c",
            "Configurations/Debug/sync_on_halt.c",
        ] if os.path.isfile(os.path.join(cache_path, f))
    ]

    # Define flags
    define_flags = ["-DCOMPILER_GNU", "-D__HIGHTEC__"]
    if cfg["deviceDefine"]:
        define_flags.append(f"-D{cfg['deviceDefine']}")
    if cfg["pinPackageDefine"]:
        define_flags.append(f"-D{cfg['pinPackageDefine']}")

    all_includes = sorted(set([".", *include_paths, *extra_includes]))
    include_flags = [f"-I{p}" for p in all_includes]

    extra_srcs_block = ""
    if extra_srcs:
        extra_srcs_block = f"""
# ── Extra source files (from imported examples — auto-discovered) ──
EXTRA_SRCS = \\
{_fmt_make_list(sorted(extra_srcs))}
"""
    else:
        extra_srcs_block = """
# ── Extra source files (none discovered) ──
EXTRA_SRCS =
"""

    makefile = f"""# ============================================================================
# AURIX Project Makefile (auto-generated by AURIX AI Agent)
# Device: {device} | Family: {info.family} | Package: {cfg['pinPackageSuffix']}
# ============================================================================
#
# Pre-configured with correct device defines, pin package, include paths,
# and iLLD source files. To add application code:
#   Just drop your .c files in the project root — they are auto-discovered.
#
# Usage:
#   make            — build the project
#   make clean      — remove build artefacts
#

# ── Toolchain ──
CROSS_COMPILE = {gcc_prefix}
CC      = $(CROSS_COMPILE)gcc
AS      = $(CROSS_COMPILE)gcc
LD      = $(CROSS_COMPILE)gcc
OBJCOPY = $(CROSS_COMPILE)objcopy
SIZE    = $(CROSS_COMPILE)size

# ── Project ──
TARGET    = {device}
BUILD_DIR = build

# ── CPU & Defines ──
CPU = -mcpu={info.mcpu}
DEFINES = {' '.join(define_flags)}

# ── Include paths ──
INCLUDES = \\
{_fmt_make_list(include_flags)}

# ── Linker script ──
LDSCRIPT = {find_linker_script(cache_path)}

# ── Compiler flags (match ADS: -std=c99, -fstrict-volatile-bitfields for HW regs) ──
CFLAGS  = $(CPU) -std=c99 -O0 -g3 -Wall -ffunction-sections -fdata-sections -fno-common -fstrict-volatile-bitfields
CFLAGS += $(DEFINES) $(INCLUDES)

ASFLAGS = $(CPU) -x assembler-with-cpp $(DEFINES) $(INCLUDES)

LDFLAGS = $(CPU) -T $(LDSCRIPT) -Wl,--gc-sections -nocrt0
LDFLAGS += -Wl,-Map=$(BUILD_DIR)/$(TARGET).map

# ── User source files (auto-discovered: any .c in the project root) ──
USER_SRCS = $(wildcard *.c)

# ── Configuration source files ──
CFG_SRCS = \\
{_fmt_make_list(cfg_srcs)}

# ── Library source files (auto-generated — do not edit) ──
LIB_SRCS = \\
{_fmt_make_list(lib_srcs)}
{extra_srcs_block}
# ── All sources ──
C_SRCS = $(USER_SRCS) $(CFG_SRCS) $(LIB_SRCS) $(EXTRA_SRCS)

ASM_SRCS =

# ── Object files ──
C_OBJS   = $(patsubst %.c,$(BUILD_DIR)/%.o,$(C_SRCS))
ASM_OBJS = $(patsubst %.S,$(BUILD_DIR)/%.o,$(patsubst %.s,$(BUILD_DIR)/%.o,$(ASM_SRCS)))
OBJS     = $(C_OBJS) $(ASM_OBJS)
DEPS     = $(C_OBJS:.o=.d)

# ── Rules ──
.PHONY: all clean

all: $(BUILD_DIR)/$(TARGET).elf $(BUILD_DIR)/$(TARGET).hex
\t@echo "Build complete: $(BUILD_DIR)/$(TARGET).elf"
\t@$(SIZE) $(BUILD_DIR)/$(TARGET).elf

$(BUILD_DIR)/$(TARGET).elf: $(OBJS)
\t@echo "Linking: $@"
\t@mkdir -p $(dir $@)
\t$(LD) $(LDFLAGS) $^ -o $@

$(BUILD_DIR)/$(TARGET).hex: $(BUILD_DIR)/$(TARGET).elf
\t$(OBJCOPY) -O ihex $< $@

$(BUILD_DIR)/%.o: %.c
\t@echo "Compiling: $<"
\t@mkdir -p $(dir $@)
\t$(CC) $(CFLAGS) -MMD -MP -c $< -o $@

$(BUILD_DIR)/%.o: %.S
\t@echo "Assembling: $<"
\t@mkdir -p $(dir $@)
\t$(AS) $(ASFLAGS) -c $< -o $@

$(BUILD_DIR)/%.o: %.s
\t@echo "Assembling: $<"
\t@mkdir -p $(dir $@)
\t$(AS) $(ASFLAGS) -c $< -o $@

clean:
\trm -rf $(BUILD_DIR)

-include $(DEPS)
"""

    with open(os.path.join(cache_path, "Makefile"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(makefile)

    details.append(f"Generated Makefile: {len(lib_srcs)} library sources, {len(include_paths)} include paths")
    details.append(f"Defines: {' '.join(define_flags)}")
    details.append(f"PinMap variant: {cfg['pinPackageSuffix'] or '(all)'}")
    return details


# ---------------------------------------------------------------------------
# Main: create project in cache
# ---------------------------------------------------------------------------

def create_project_in_cache(device: str, studio_dir: str) -> dict[str, Any]:
    upper_device = normalize_device(device)
    info = DEVICE_MAP.get(upper_device)
    if not info:
        supported = ", ".join(DEVICE_MAP.keys())
        raise ValueError(f'Unknown device "{device}". Supported: {supported}')

    cache_path = os.path.join(DEVICE_PROJECTS_CACHE, info.illd_dir)
    marker_file = os.path.join(cache_path, ".device_project_ready")
    details: list[str] = []

    # Check cache
    if os.path.isfile(marker_file):
        cached_version = None
        try:
            marker = json.loads(open(marker_file, "r").read())
            cached_version = marker.get("templateVersion")
        except Exception:
            pass
        if cached_version == TEMPLATE_VERSION:
            details.append(f"Using cached project template at {cache_path} (v{TEMPLATE_VERSION})")
            return {"cachePath": cache_path, "info": info, "details": details}
        details.append(
            f"Cache at {cache_path} is stale (have={cached_version or 'unknown'}, need={TEMPLATE_VERSION}); regenerating."
        )

    # Clean and create
    if os.path.exists(cache_path):
        shutil.rmtree(cache_path, ignore_errors=True)
    os.makedirs(cache_path, exist_ok=True)

    pi = find_project_initializer(studio_dir, info)

    # 1. Extract iLLD zip
    details.append(f"Extracting iLLD from {os.path.basename(pi.illd_zip)}...")
    libraries_dir = os.path.join(cache_path, "Libraries")
    extract_zip(pi.illd_zip, libraries_dir)

    # 2. Copy source templates
    if os.path.isdir(pi.source_templates):
        src_count = 0
        # Collect source files from the template dir and SimpleMain subdir
        src_dirs = [pi.source_templates]
        simple_main = os.path.join(pi.source_templates, "SimpleMain")
        if os.path.isdir(simple_main):
            src_dirs.append(simple_main)

        for src_dir in src_dirs:
            for entry in os.scandir(src_dir):
                if entry.is_dir():
                    continue
                if entry.name.endswith(".ftlc"):
                    raw = open(entry.path, "r", encoding="utf-8", errors="replace").read()
                    processed = process_ftlh(raw, {"device": info.device_selector, "platform": info.platform})
                    out_name = entry.name[:-5] + ".c"
                    with open(os.path.join(cache_path, out_name), "w", encoding="utf-8") as fh:
                        fh.write(processed)
                elif entry.name.endswith(".template"):
                    raw = open(entry.path, "r", encoding="utf-8", errors="replace").read()
                    processed = process_ejs_template(raw)
                    out_name = entry.name[:-9]  # strip .template
                    with open(os.path.join(cache_path, out_name), "w", encoding="utf-8") as fh:
                        fh.write(processed)
                else:
                    if entry.name.lower() in ("readme.txt",):
                        continue
                    shutil.copy2(entry.path, os.path.join(cache_path, entry.name))
                src_count += 1
        details.append(f"Copied {src_count} source template files")

    # 3. Copy Configurations
    config_dest = os.path.join(cache_path, "Configurations")
    if os.path.isdir(pi.config_templates):
        os.makedirs(config_dest, exist_ok=True)

        # Determine actual config source dirs.
        # ACS layout: config_templates contains device subdirs like TC4D7Xx/SimpleMain/, TC4D7Xx/Commons/
        # ADS layout: config_templates directly contains Ifx_Cfg.ftlh etc.
        config_source_dirs: list[str] = []
        # Derive device prefix for ACS subdir matching (e.g. "TC4D7" → "TC4D7Xx")
        device_prefix = upper_device  # e.g. "TC4D7"
        acs_device_dir = None
        for entry in os.scandir(pi.config_templates):
            if entry.is_dir() and entry.name.upper().startswith(device_prefix.upper()):
                acs_device_dir = entry.path
                break
        if acs_device_dir:
            # ACS layout: collect from Commons/ and SimpleMain/ subdirs
            commons = os.path.join(acs_device_dir, "Commons")
            simple_main_cfg = os.path.join(acs_device_dir, "SimpleMain")
            if os.path.isdir(commons):
                config_source_dirs.append(commons)
            if os.path.isdir(simple_main_cfg):
                config_source_dirs.append(simple_main_cfg)
        else:
            # ADS layout: files directly in config_templates
            config_source_dirs.append(pi.config_templates)

        for cfg_dir in config_source_dirs:
            for entry in os.scandir(cfg_dir):
                if entry.is_dir():
                    copy_dir_recursive(entry.path, os.path.join(config_dest, entry.name))
                elif entry.name.endswith(".ftlh"):
                    raw = open(entry.path, "r", encoding="utf-8", errors="replace").read()
                    processed = process_ftlh(raw, {"device": info.device_selector, "platform": info.platform})
                    out_name = entry.name[:-5] + ".h"
                    with open(os.path.join(config_dest, out_name), "w", encoding="utf-8") as fh:
                        fh.write(processed)
                    details.append(f"Processed {entry.name} → {out_name}")
                elif entry.name.endswith(".template"):
                    raw = open(entry.path, "r", encoding="utf-8", errors="replace").read()
                    processed = process_ejs_template(raw)
                    out_name = entry.name[:-9]  # strip .template
                    with open(os.path.join(config_dest, out_name), "w", encoding="utf-8") as fh:
                        fh.write(processed)
                    details.append(f"Processed {entry.name} → {out_name}")
                else:
                    shutil.copy2(entry.path, os.path.join(config_dest, entry.name))

    # 4. Copy linker scripts
    lcf_dest = os.path.join(cache_path, "Lcf")
    if os.path.isdir(pi.linker_tasking):
        copy_dir_recursive(pi.linker_tasking, os.path.join(lcf_dest, "Tasking"))
        details.append("Copied TASKING linker scripts")
    if os.path.isdir(pi.linker_gcc):
        copy_dir_recursive(pi.linker_gcc, os.path.join(lcf_dest, "Gcc"))
        details.append("Copied GCC linker scripts")

    # 5. Generate Makefile
    make_details = generate_makefile(cache_path, info, studio_dir, upper_device)
    details.extend(make_details)

    # Mark as ready
    with open(marker_file, "w", encoding="utf-8") as fh:
        json.dump({
            "templateVersion": TEMPLATE_VERSION,
            "device": upper_device,
            "illdDir": info.illd_dir,
            "family": info.family,
            "cores": info.cores,
            "createdAt": __import__("datetime").datetime.now().isoformat(),
        }, fh)

    return {"cachePath": cache_path, "info": info, "details": details}


# ---------------------------------------------------------------------------
# MCP tool handler
# ---------------------------------------------------------------------------

async def _run(args: dict[str, Any], _ctx: ToolContext) -> ToolResult:
    device = (args.get("device") or "").strip()
    workspace = (args.get("workspace") or "").strip() or None

    if not device:
        raise ValueError("ads.create_project requires device")

    upper_device = normalize_device(device)
    info = DEVICE_MAP.get(upper_device)
    if not info:
        supported = ", ".join(DEVICE_MAP.keys())
        return ToolResult(
            content=[TextContent(text=f'Unknown device "{device}". Supported devices: {supported}')],
            is_error=True,
        )

    try:
        board = selected_board(args.get("board"), workspace, device)
        if device.upper().startswith("KIT_") and board and normalize_board(device) != board:
            return ToolResult.text("ads.create_project failed: device and board specify different boards", is_error=True)
        requested_device = re.search(r"TC(?:\d{3}|4[A-Z]\d)", device.upper())
        board_device = re.search(r"TC(?:\d{3}|4[A-Z]\d)", board or "")
        if board_device and requested_device and board_device[0] != requested_device[0]:
            return ToolResult.text("ads.create_project failed: board and device refer to different devices", is_error=True)
        studio_dir = resolve_studio_dir(workspace)
    except ValueError as error:
        return ToolResult.text(f"ads.create_project failed: {error}", is_error=True)
    except FileNotFoundError as e:
        return ToolResult(
            content=[TextContent(text=f"Cannot resolve ADS installation: {e}")],
            is_error=True,
        )

    try:
        result = create_project_in_cache(upper_device, studio_dir)
        cache_path = result["cachePath"]
        details = result["details"]
        info = result["info"]

        deployed_to: Optional[str] = None
        deploy_details: list[str] = []

        if workspace:
            deployed_to = os.path.abspath(workspace)
            os.makedirs(deployed_to, exist_ok=True)
            deploy_details.extend(deploy_template_dependencies(cache_path, deployed_to))

            # Makefile: regenerate against actual workspace layout
            ws_details = generate_makefile(deployed_to, info, studio_dir, upper_device)
            deploy_details.append("Generated Makefile (scanned workspace layout)")
            deploy_details.extend(ws_details)

            # CpuN_Main.c stubs: only if not present
            for f in os.listdir(cache_path):
                if re.match(r"^Cpu\d+_Main\.c$", f):
                    dest_stub = os.path.join(deployed_to, f)
                    if not os.path.exists(dest_stub):
                        shutil.copy2(os.path.join(cache_path, f), dest_stub)
                        deploy_details.append(f"Created {f}")
                    else:
                        deploy_details.append(f"Preserved existing {f}")

        target_path = deployed_to or cache_path
        illd_version = detect_illd_version(target_path)
        if deployed_to:
            board_pins = deploy_board_pins(deployed_to, board, studio_dir)
        else:
            board_pins = resolve_board_pins(None, board, studio_dir)
            board_pins["deployment"] = "not_copied"
        lines = [
            f"ads.create_project succeeded for {upper_device}:",
            f"  {'Deployed to' if deployed_to else 'Cache path'}: {target_path}",
            f"  iLLD directory: {info.illd_dir}",
            f"  {format_illd_version(illd_version)}",
            f"  {format_board_pins(board_pins)}",
            f"  Family: {info.family}",
            f"  Cores: {info.cores}",
            *[f"  {d}" for d in details],
            *[f"  {d}" for d in deploy_details],
        ]
        if deployed_to:
            lines.append("  Makefile is ready — call build.run next.")

        return ToolResult(
            content=[TextContent(text="\n".join(lines))],
            structured_content={
                "ok": True,
                "device": upper_device,
                "deployedTo": deployed_to,
                "cachePath": cache_path,
                "illdDir": info.illd_dir,
                "illdVersion": illd_version,
                "boardPins": board_pins,
                "family": info.family,
                "cores": info.cores,
            },
        )
    except Exception as e:
        return ToolResult(
            content=[TextContent(text=f"ads.create_project failed: {e}")],
            is_error=True,
        )


# ---------------------------------------------------------------------------
# Exported helper: regenerate Makefile for an existing workspace
# ---------------------------------------------------------------------------

def regenerate_makefile_for_workspace(workspace_dir: str) -> Optional[str]:
    """Regenerate the Makefile in-place for a workspace that already has
    Libraries + Configurations deployed. Called by examples.import after
    importing files that add source directories.

    Returns None if the workspace is not a valid ads.create_project workspace,
    or a status string on success.
    """
    ifx_cfg_path = os.path.join(workspace_dir, "Configurations", "Ifx_Cfg.h")
    if not os.path.isfile(ifx_cfg_path):
        return None
    if not os.path.isdir(os.path.join(workspace_dir, "Libraries")):
        return None

    cfg = parse_ifx_cfg_defines(ifx_cfg_path)
    device_from_define = cfg["deviceDefine"].replace("DEVICE_", "")

    device: Optional[str] = None
    info: Optional[DeviceInfo] = None

    if device_from_define in DEVICE_MAP:
        device = device_from_define
        info = DEVICE_MAP[device]
    else:
        # Prefix match
        candidates = sorted(
            [k for k in DEVICE_MAP if device_from_define.startswith(k)],
            key=len, reverse=True,
        )
        if candidates:
            device = candidates[0]
            info = DEVICE_MAP[device]

    if not device or not info:
        return None

    try:
        studio_dir = resolve_studio_dir()
    except FileNotFoundError:
        return None

    generate_makefile(workspace_dir, info, studio_dir, device)
    return f"Regenerated Makefile for {device} (scanned workspace layout)"


# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------


