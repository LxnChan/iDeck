# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Check runtime cache invalidation boundaries without a compiler or build assets."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "runtime_input_key", ROOT / "tools/build/runtime-input-key.py")
runtime_key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_key)


class RuntimeInputKeyChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ideck-runtime-keys-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.pins = {"FEX": "1" * 40, "wine": "2" * 40, "dxmt": "3" * 40}
        self.versioned = {
            "build/gnutls-ios/build.sh": b"gnutls recipe",
            "build/gnutls-ios/src/SHA256SUMS": b"pinned dependency hashes",
            "build/ffmpeg/build.sh": b"ffmpeg recipe",
            "build/freetype-ios/build.sh": b"freetype recipe",
            "build/ntdll-unix/virtual_ios.c": b"native Wine bridge",
            "build/wine-pe/build-ntdll.sh": b"Windows Wine recipe",
            "build/fex-ios/fex-cpuid-bmi-fma.patch": b"existing FEX patch",
            "build/dxmt-patches/existing.patch": b"existing DXMT patch",
            "tools/build/build-wine.sh": b"shared header generator",
            "tools/build/sync-gnutls-libs.sh": b"dependency archive staging",
            ".github/workflows/build-ipa.yml": b"build workflow",
            "app/Madeira/aarch64-windows/ideck-control.dll": b"versioned companion PE",
            "app/Madeira/FEXBridge.mm": b"app bridge compiled by Xcode",
            "docs/RUNTIME_SYNC.md": b"documentation",
        }
        for name, content in self.versioned.items():
            self.write(name, content)
        self.tracked = list(self.versioned) + list(self.pins)

    def write(self, name, content):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def git_output(self, arguments, **kwargs):
        self.assertEqual(arguments[:3], ["git", "-C", str(self.work)])
        if arguments[3:] == ["ls-files", "-z"]:
            return ("\0".join(self.tracked) + "\0").encode()
        self.assertEqual(arguments[3], "rev-parse")
        revision = arguments[4]
        self.assertTrue(revision.startswith("HEAD:"))
        return self.pins[revision.split(":", 1)[1]] + "\n"

    def keys(self):
        output = self.work / "github-output"
        output.write_bytes(b"")
        with mock.patch.object(runtime_key, "ROOT", self.work), \
                mock.patch.object(runtime_key.subprocess, "check_output",
                                  side_effect=self.git_output), \
                mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            runtime_key.main()
        values = dict(line.split("=", 1)
                      for line in output.read_text(encoding="utf-8").splitlines())
        self.assertEqual(set(values), {"dependency", "windows", "native"})
        for value in values.values():
            self.assertRegex(value, r"^[0-9a-f]{64}$")
        return values

    def assert_changed_groups(self, before, after, expected):
        changed = {group for group in before if before[group] != after[group]}
        self.assertEqual(changed, set(expected))

    def test_generated_objects_and_copied_ignored_assets_do_not_change_keys(self):
        before = self.keys()
        assets = (
            "build/ntdll-unix/obj/virtual.o",
            "build/wine-pe/obj/arm64ec/ntdll.dll",
            "build/dxmt-ios/obj/shader.o",
            "FEX/build-ios/FEXCore/Source/libFEXCore.a",
            "dxmt/build-arm64ec/src/d3d11/d3d11.dll",
            "app/Madeira/libFEXCore.a",
            "app/Madeira/libntdll_unix.a",
            "app/Madeira/libdxmt_combined.a",
            "app/Madeira/prefix-template.tar.gz",
            "app/Frameworks/StikJIT.xcframework/ios-arm64/StikJIT.framework/StikJIT",
            "toolchains/gnutls-ios/lib/libgnutls.a",
        )
        for name in assets:
            self.write(name, b"first generated or downloaded build output")
        self.assertEqual(self.keys(), before)
        for name in assets:
            self.write(name, b"different output from a rebuild or new release download")
        self.assertEqual(self.keys(), before)

    def test_versioned_native_bridge_invalidates_native_cache(self):
        before = self.keys()
        self.write("build/ntdll-unix/virtual_ios.c", b"updated source bridge protocol")
        self.assert_changed_groups(before, self.keys(), {"native"})

    def test_versioned_cpu_and_graphics_patches_invalidate_both_runtime_caches(self):
        for name in ("build/fex-ios/fex-cpuid-bmi-fma.patch",
                     "build/dxmt-patches/existing.patch"):
            with self.subTest(patch=name):
                before = self.keys()
                self.write(name, b"updated versioned patch")
                self.assert_changed_groups(before, self.keys(), {"windows", "native"})
                self.write(name, self.versioned[name])

    def test_each_source_pin_invalidates_runtime_caches_but_not_dependencies(self):
        for name in self.pins:
            with self.subTest(component=name):
                before = self.keys()
                original = self.pins[name]
                self.pins[name] = "9" * 40
                self.assert_changed_groups(before, self.keys(), {"windows", "native"})
                self.pins[name] = original

    def test_dependency_recipe_invalidates_dependencies_and_native_cache(self):
        before = self.keys()
        self.write("build/gnutls-ios/build.sh", b"updated GnuTLS configuration")
        self.assert_changed_groups(before, self.keys(), {"dependency", "native"})

    def test_shared_build_recipes_and_workflow_invalidate_both_runtime_caches(self):
        for name in ("tools/build/build-wine.sh", ".github/workflows/build-ipa.yml"):
            with self.subTest(recipe=name):
                before = self.keys()
                self.write(name, b"updated common build behavior")
                self.assert_changed_groups(before, self.keys(), {"windows", "native"})
                self.write(name, self.versioned[name])

    def test_dependency_staging_recipe_invalidates_all_three_caches(self):
        before = self.keys()
        self.write("tools/build/sync-gnutls-libs.sh", b"updated library staging")
        self.assert_changed_groups(before, self.keys(), {"dependency", "windows", "native"})

    def test_versioned_companion_pe_bytes_invalidate_windows_cache(self):
        before = self.keys()
        self.write("app/Madeira/aarch64-windows/ideck-control.dll", b"updated companion PE")
        self.assert_changed_groups(before, self.keys(), {"windows"})

    def test_app_only_edits_do_not_rebuild_cached_runtime_libraries(self):
        before = self.keys()
        self.write("app/Madeira/FEXBridge.mm", b"updated app-side bridge")
        self.write("docs/RUNTIME_SYNC.md", b"updated validation notes")
        self.assertEqual(self.keys(), before)

    def test_git_file_listing_order_does_not_change_cache_identity(self):
        before = self.keys()
        self.tracked.reverse()
        self.assertEqual(self.keys(), before)


if __name__ == "__main__":
    unittest.main()
