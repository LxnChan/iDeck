"""Check the production Wine farm selection across PE architectures."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wine_runtime_targets", ROOT / "build/windows-runtime/targets.py"
)
runtime_targets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_targets)


def make_rules(arch, files):
    return "\n".join(f"dlls/{name.rsplit('.', 1)[0]}/{arch}-windows/{name}: objects" for name in files)


class WineRuntimeTargets(unittest.TestCase):
    def test_each_farm_contains_core_and_excludes_other_architectures(self):
        text = "\n".join(make_rules(arch, ["ntdll.dll", "kernel32.dll", "wow64.dll"])
                         for arch in ["arm64ec", "aarch64", "i386"])
        for arch in ["arm64ec", "aarch64", "i386"]:
            with self.subTest(arch=arch):
                result = runtime_targets.targets(text, arch)
                self.assertEqual(len(result), 3)
                self.assertTrue(all(f"/{arch}-windows/" in item for item in result))

    def test_fex_dxmt_d3d12_and_ios_owned_files_are_not_replaced(self):
        external = ["d3d11.dll", "dxgi.dll", "winemetal.dll", "d3d12.dll", "d3d12core.dll",
                    "xtajit.dll", "xtajit64.dll", "wow64cpu.dll", "wineios.drv",
                    "faultrep.dll", "wintypes.dll"]
        for arch in ["arm64ec", "aarch64", "i386"]:
            with self.subTest(arch=arch):
                text = make_rules(arch, external + ["ntdll.dll"])
                self.assertEqual(runtime_targets.targets(text, arch),
                                 [f"dlls/ntdll/{arch}-windows/ntdll.dll"])

    def test_native_d3d9_and_d3d10core_belong_to_wine(self):
        files = ["ntdll.dll", "d3d9.dll", "d3d10core.dll"]
        for arch in ["arm64ec", "i386"]:
            self.assertEqual(len(runtime_targets.targets(make_rules(arch, files), arch)), 1)
        self.assertEqual(len(runtime_targets.targets(make_rules("aarch64", files), "aarch64")), 3)

    def test_only_installable_targets_are_selected_once(self):
        text = make_rules("arm64ec", ["ntdll.dll", "ntdll.dll", "libntdll.a", "module.o",
                                         "cng.sys", "winevdm.exe", "winevulkan.dll"])
        text += "\nprograms/cmd/arm64ec-windows/cmd.exe: objects\n"
        result = runtime_targets.targets(text, "arm64ec")
        self.assertEqual(result, ["dlls/ntdll/arm64ec-windows/ntdll.dll",
                                  "programs/cmd/arm64ec-windows/cmd.exe"])

    def test_companion_ntoskrnl_is_rebuilt_from_selected_wine_source(self):
        # The base IPA already ships this Wine module. Refresh it alongside
        # the other PE files instead of retaining its previous source version.
        for arch in ["arm64ec", "aarch64"]:
            with self.subTest(arch=arch):
                rule = f"dlls/ntoskrnl.exe/{arch}-windows/ntoskrnl.exe: objects"
                self.assertEqual(runtime_targets.targets(rule, arch),
                                 [f"dlls/ntoskrnl.exe/{arch}-windows/ntoskrnl.exe"])


if __name__ == "__main__":
    unittest.main()
