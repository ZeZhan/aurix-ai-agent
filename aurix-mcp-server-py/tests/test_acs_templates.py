from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurix_mcp_server.tools import ads_create_project as acp


class AcsTemplateProcessingTests(unittest.TestCase):
    def test_freemarker_blocks_in_acs_templates_are_removed(self) -> None:
        # Excerpt of ACS 1.0.24 TC37A/TC4DA Cpu0_Main.c.template and Ifx_Cfg.h.template.
        template = (
            '#include "Ifx_Cfg_Ssw.h"\n'
            "<#if SCR?has_content>\n"
            '#include "${SCR}.h"\n'
            "</#if>\n"
            "void core0_main(void)\n{\n"
            "    <#if CDSP>\n"
            "    <#list 0..(CdspCount-1) as i>\n"
            "    start(${i});\n"
            "    </#list>\n"
            "    </#if>\n"
            "    while(1) { }\n}\n"
            "<% if (PPU) { %>\nppu();\n<% } %>\n"
        )
        result = acp.process_ejs_template(template)
        self.assertEqual(result.rstrip("\n"), '#include "Ifx_Cfg_Ssw.h"\nvoid core0_main(void)\n{\n    while(1) { }\n}')

    def test_c_code_with_angle_brackets_is_untouched(self) -> None:
        code = '#include <stdint.h>\nint a = b < c ? 1 : 2;\n'
        self.assertEqual(acp.process_ejs_template(code), code)


class PinPackageAliasTests(unittest.TestCase):
    def libraries(self, header: str) -> str:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        pinmap = Path(temporary.name) / "iLLD" / "TC4xx" / "CpuGeneric" / "_PinMap"
        pinmap.mkdir(parents=True)
        (pinmap / "IfxAsclin_PinMap.h").write_text(header, encoding="utf-8")
        return temporary.name

    def test_acs_tc4d7_package_name_maps_to_the_illd_name(self) -> None:
        libraries = self.libraries(
            "#if defined(IFX_PIN_PACKAGE_BGA436_COM)\n#include \"a.h\"\n"
            "#elif defined(IFX_PIN_PACKAGE_BGA292_COM)\n#include \"b.h\"\n#endif\n"
        )
        self.assertEqual(acp.resolve_pin_package_alias(libraries, "LFBGA292_COM"), "BGA292_COM")

    def test_matching_or_unknown_names_are_left_alone(self) -> None:
        libraries = self.libraries(
            "#if defined(IFX_PIN_PACKAGE_LQFP176)\n#elif defined(IFX_PIN_PACKAGE_LFBGA292)\n"
            "#elif defined(IFX_PIN_PACKAGE_BGA292)\n#endif\n"
        )
        self.assertIsNone(acp.resolve_pin_package_alias(libraries, "LQFP176"))
        self.assertIsNone(acp.resolve_pin_package_alias(libraries, "LFBGA292"))
        self.assertIsNone(acp.resolve_pin_package_alias(libraries, "XYZ"))
        self.assertIsNone(acp.resolve_pin_package_alias(libraries, ""))


if __name__ == "__main__":
    unittest.main()
