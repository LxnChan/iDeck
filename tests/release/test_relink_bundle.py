"""Exercise exact Xcode input capture and a relocated relink recipe."""
from pathlib import Path, PurePosixPath, PureWindowsPath
import hashlib
import importlib.util
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prepare_relink", ROOT / "tools/prepare-relink.py")
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class PolicyPosixPath(PurePosixPath):
    """Exercise POSIX path policy on hosts without macOS's temporary folders."""
    def resolve(self):
        return self


class PolicyWindowsPath(PureWindowsPath):
    def resolve(self):
        return self


class RelinkBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "original build"
        self.source.mkdir()
        self.sdk = self.root / "Xcode SDK" / "iPhoneOS27.0.sdk"
        self.toolchain = self.root / "XcodeDefault.xctoolchain"
        self.driver = self.toolchain / "usr/bin/clang++"
        self.sdk.mkdir(parents=True)
        self.library = self.write("libraries/libdxmt_combined.a", b"actual DXMT archive")
        self.object = self.write("Objects/App main.o", b"application object")
        self.swift = self.write("Objects/Madeira-Swift-generated.o", b"swift object")
        self.extra = self.write("Other/App main.o", b"other object with same basename")
        self.framework_dir = self.source / "Frameworks/ios-arm64"
        self.framework = self.write("Frameworks/ios-arm64/StikJIT.framework/StikJIT", b"externally supplied framework")
        self.write("Frameworks/ios-arm64/StikJIT.framework/embedded.mobileprovision", b"never ship profile")
        self.write("Frameworks/ios-arm64/StikJIT.framework/Headers/StikJIT.h", b"external headers")

    def write(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def log(self, args, driver=None, other=""):
        log = self.source / "xcode.log"
        log.write_text("cd " + shlex.quote(self.source.as_posix()) + "\n" + other +
                       shlex.join([str(driver or self.driver), *map(str, args)]) + "\n", encoding="utf-8")
        return log

    def base(self, name="Madeira.debug.dylib"):
        return ["-target", "arm64-apple-ios17.0", "-isysroot", self.sdk.as_posix(),
                "-L" + self.library.parent.as_posix(), "-F", self.framework_dir.as_posix(),
                "-framework", "StikJIT", "-framework", "Foundation", "-lc++", "-lz",
                "-o", (self.source / "DerivedData/Madeira.app" / name).as_posix()]

    def recipe(self, bundle, *args):
        return subprocess.run([sys.executable, str(bundle / "relink.py"), "--sdk", str(self.sdk),
                               "--compiler", sys.executable, "--toolchain-root", str(self.toolchain),
                               "--framework-path", str(self.framework_dir), *args], text=True, capture_output=True)

    def test_debug_capture_exact_objects_archives_and_external_framework(self):
        filelist = self.write("Objects/link inputs.list", (self.object.as_posix() + "\n" +
                              shlex.quote(self.swift.as_posix()) + "\n" + self.extra.as_posix()).encode())
        response = self.write("nested.rsp", shlex.join(["-l", "dxmt_combined", self.library.as_posix()]).encode())
        response2 = self.write("driver.rsp", shlex.join(["@" + response.as_posix()]).encode())
        args = self.base() + ["-dylib", "-filelist", filelist.as_posix(), "@" + response2.as_posix(),
                             "-Xlinker", "-add_ast_path", "-Xlinker", "missing.swiftmodule",
                             "-Wl,-object_path_lto,/unavailable/lto.o,-dependency_info,/unavailable/deps.dat",
                             "-Xlinker", "-rpath", "-Xlinker", "@executable_path/Frameworks"]
        launcher = shlex.join([str(self.driver), *map(str, self.base("Madeira")), str(self.object)]) + "\n"
        compile_line = shlex.join([str(self.driver), "@missing-response-file", "-c", "example.c"]) + "\n"
        log = self.log(args, other=compile_line + launcher)
        bundle = self.root / "bundle"
        self.assertEqual(TOOL.collect(log, bundle), 4)
        metadata = json.loads((bundle / "BUILD.json").read_text())
        self.assertEqual(metadata["driver"], "clang++")
        self.assertEqual(metadata["output"], "Madeira.debug.dylib")
        self.assertEqual(metadata["build_log_sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertEqual(metadata["external_frameworks"][0]["name"], "StikJIT")
        self.assertFalse((bundle / "Frameworks").exists())
        inputs = json.loads((bundle / "INPUTS.json").read_text())
        self.assertEqual(len({x["path"] for x in inputs}), 4)
        self.assertTrue(any(x["path"].endswith("Madeira-Swift-generated.o") for x in inputs))
        for entry in inputs:
            self.assertEqual(hashlib.sha256((bundle / entry["path"]).read_bytes()).hexdigest(), entry["sha256"])
        portable = (bundle / "link-args.json").read_text()
        self.assertNotIn(self.source.as_posix(), portable)
        self.assertNotIn("missing.swiftmodule", portable)
        self.assertNotIn("/unavailable", portable)
        self.assertIn("@executable_path/Frameworks", portable)
        moved = self.root / "relocated kit"
        shutil.move(str(bundle), str(moved))
        result = self.recipe(moved, "--verify-inputs", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("relocated kit", result.stdout)
        self.assertNotIn("DerivedData", result.stdout)
        self.assertNotIn("codesign", (moved / "link-args.json").read_text())

    def test_release_clang_linker_response_and_library_replacement(self):
        filelist = self.write("relative.list", b'"Objects/App main.o"\n')
        ld_response = self.write("ld.rsp", shlex.join(["-filelist", filelist.name, "-force_load", str(self.library)]).encode())
        swiftlib = self.toolchain / "usr/lib/swift/iphoneos/libswiftCompatibility.a"
        swiftlib.parent.mkdir(parents=True)
        swiftlib.write_bytes(b"toolchain library supplied by Xcode")
        args = self.base("Madeira") + ["-Xlinker", "@" + str(ld_response),
                                      "-L" + str(swiftlib.parent), "-lswiftCompatibility"]
        bundle = self.root / "release"
        TOOL.collect(self.log(args, driver=self.driver.with_name("clang")), bundle)
        self.assertEqual(json.loads((bundle / "BUILD.json").read_text())["output"], "Madeira")
        self.assertEqual(len(json.loads((bundle / "INPUTS.json").read_text())), 2)
        portable = json.loads((bundle / "link-args.json").read_text())
        self.assertIn("-L@TOOLCHAIN@/usr/lib/swift/iphoneos", portable)
        self.assertIn("-lswiftCompatibility", portable)
        (bundle / "libraries/libdxmt_combined.a").write_bytes(b"modified LGPL library")
        self.assertEqual(self.recipe(bundle, "--dry-run").returncode, 0)
        rejected = self.recipe(bundle, "--verify-inputs", "--dry-run")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("hash mismatch", rejected.stderr)

    def test_required_external_framework_must_be_supplied(self):
        bundle = self.root / "bundle"
        TOOL.collect(self.log(self.base() + [str(self.object)]), bundle)
        command = [sys.executable, str(bundle / "relink.py"), "--sdk", str(self.sdk),
                   "--compiler", sys.executable, "--dry-run"]
        missing = subprocess.run(command, text=True, capture_output=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("StikJIT.framework", missing.stderr)
        self.framework.write_bytes(b"rebuilt external framework")
        self.assertEqual(self.recipe(bundle, "--dry-run").returncode, 0)
        changed = self.recipe(bundle, "--verify-inputs", "--dry-run")
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("framework hash mismatch", changed.stderr)

    def test_recursive_or_missing_response_fails(self):
        loop = self.write("loop.rsp", b"@loop.rsp")
        for response, message in [(str(loop), "Recursive"), ("missing.rsp", "Missing")]:
            with self.subTest(response=response):
                with self.assertRaisesRegex(TOOL.RelinkError, message):
                    TOOL.collect(self.log(self.base() + ["@" + response]), self.root / ("bundle-" + message))

    def test_does_not_copy_credentials_logs_or_valve_payloads(self):
        for name in ["profile.mobileprovision", "key.p12", "private.log", "private/runtime.a", "valve/runtime.a", "steamclient.o"]:
            with self.subTest(name=name):
                unsafe = self.write(name, b"must not ship")
                with self.assertRaises(TOOL.RelinkError):
                    TOOL.collect(self.log(self.base() + ["-force_load", str(unsafe)]), self.root / ("kit-" + name.replace("/", "-")))

    def test_macos_system_temporary_prefixes_are_allowed(self):
        for name in ["/private/var/folders/runner/Build/main.o", "/private/tmp/runtime/native.a"]:
            with self.subTest(path=name):
                TOOL.ensure_public_input(PolicyPosixPath(name))

    def test_macos_temporary_prefixes_keep_private_payload_checks(self):
        for name in ["/private/var/private/runtime.a", "/private/tmp/private/runtime.o",
                     "/private/var/folders/runner/key.p12", "/private/tmp/private.log",
                     "/private/var/credentials/runtime.a", "/private/tmp/valve/runtime.o",
                     "/private/tmp/steamclient.o", "/private/other/runtime.a",
                     "/private/varevil/runtime.a", "/tmp/private/var/runtime.a", "private/var/runtime.a"]:
            with self.subTest(path=name):
                with self.assertRaises(TOOL.RelinkError):
                    TOOL.ensure_public_input(PolicyPosixPath(name))
        with self.assertRaises(TOOL.RelinkError):
            TOOL.ensure_public_input(PolicyWindowsPath("C:/private/var/runtime.a"))

    def test_simulator_and_ambiguous_main_links_are_rejected(self):
        args = self.base() + [str(self.object)]
        args[1] = "arm64-apple-ios17.0-simulator"
        with self.assertRaisesRegex(TOOL.RelinkError, "found 0"):
            TOOL.collect(self.log(args), self.root / "simulator")
        args[1] = "arm64-apple-ios17.0"
        duplicate = shlex.join([str(self.driver), *args]) + "\n"
        with self.assertRaisesRegex(TOOL.RelinkError, "found 2"):
            TOOL.collect(self.log(args, other=duplicate), self.root / "duplicate")


if __name__ == "__main__":
    unittest.main()
