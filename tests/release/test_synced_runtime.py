# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise runtime provenance and IPA integrity with synthetic PE headers."""
import contextlib
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "synced_runtime", ROOT / "tools/check-synced-runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
MACHINES = {"arm64ec-windows": 0xa641, "aarch64-windows": 0xaa64,
            "i386-windows": 0x14c}


def pe_bytes(machine):
    """Make enough of a DOS and COFF header for the guard, with no real code."""
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3c, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    data[-8:] = b"fixture!"
    return bytes(data)


class SynchronizedRuntimeChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ideck-runtime-sync-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.bundle = self.work / "Madeira.app"
        self.pins = {"FEX": "1" * 40, "wine": "2" * 40, "dxmt": "3" * 40}
        for arch, names in runtime.REQUIRED.items():
            (self.bundle / arch).mkdir(parents=True)
            for name in names:
                (self.bundle / arch / name).write_bytes(pe_bytes(MACHINES[arch]))
        # A valid ar container with a single synthetic member; no native toolchain.
        member = f'{"fixture.o/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{1:<10}`\n'
        native = b"!<arch>\n" + member.encode("ascii") + b"\0\n"
        for name in runtime.LIBRARIES:
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(native)
        self.patch = self.work / "build/fex-ios/existing.patch"
        self.patch.parent.mkdir(parents=True)
        self.patch.write_bytes(b"existing third-party fixture patch\n")
        self.record()

    def git_pin(self, arguments, **kwargs):
        revision = arguments[-1]
        if revision.startswith("HEAD:"):
            component = revision.split(":", 1)[1]
        else:
            self.assertEqual(revision, "HEAD")
            component = Path(arguments[2]).name
        return self.pins[component] + "\n"

    def record(self, git_output=None):
        with mock.patch.object(runtime, "ROOT", self.work), \
                mock.patch.object(runtime.subprocess, "check_output",
                                  side_effect=git_output or self.git_pin), \
                contextlib.redirect_stdout(io.StringIO()):
            runtime.record(self.bundle)
        self.raw_manifest = (self.bundle / runtime.MANIFEST).read_bytes()
        self.manifest = json.loads(self.raw_manifest)

    def save_manifest(self):
        (self.bundle / runtime.MANIFEST).write_text(
            json.dumps(self.manifest), encoding="utf-8")

    def replace_pe(self, name, data, update_manifest=False):
        (self.bundle / name).write_bytes(data)
        if update_manifest:
            self.manifest["pe_files"][name] = {
                "bytes": len(data), "sha256": runtime.sha(data)}
            self.save_manifest()

    def package(self):
        path = self.work / "test.ipa"
        with zipfile.ZipFile(path, "w") as archive:
            for source in sorted(self.bundle.rglob("*")):
                if source.is_file():
                    archive.write(source, "Payload/Madeira.app/" +
                                  source.relative_to(self.bundle).as_posix())
        return path

    def verify(self, output=None):
        with contextlib.redirect_stdout(io.StringIO()):
            runtime.verify_ipa(self.package(), output)

    def test_complete_package_records_inputs_and_exports_exact_manifest(self):
        self.assertEqual(self.manifest["pins"], self.pins)
        self.assertEqual(set(self.manifest["native_link_inputs"]), set(runtime.LIBRARIES))
        self.assertEqual(len(self.manifest["pe_files"]),
                         sum(len(names) for names in runtime.REQUIRED.values()))
        self.assertEqual(self.manifest["patches"]["build/fex-ios/existing.patch"],
                         runtime.sha(self.patch.read_bytes()))
        output = self.work / "runtime-sync.json"
        self.verify(output)
        self.assertEqual(output.read_bytes(), self.raw_manifest)

    def test_wrong_pe_architecture_rejected_even_with_matching_digest(self):
        wrong = {"arm64ec-windows": 0x14c, "aarch64-windows": 0x8664,
                 "i386-windows": 0xaa64}
        for arch, machine in wrong.items():
            with self.subTest(arch=arch):
                name = arch + "/ntdll.dll"
                self.replace_pe(name, pe_bytes(machine), update_manifest=True)
                with self.assertRaisesRegex(ValueError, "wrong PE machine"):
                    self.verify()
                self.replace_pe(name, pe_bytes(MACHINES[arch]), update_manifest=True)

    def test_amd64_header_is_accepted_for_arm64ec_runtime(self):
        self.replace_pe("arm64ec-windows/ntdll.dll", pe_bytes(0x8664),
                        update_manifest=True)
        self.verify()

    def test_missing_required_runtime_cannot_be_hidden_in_manifest(self):
        name = "arm64ec-windows/xtajit64.dll"
        del self.manifest["pe_files"][name]
        (self.bundle / name).unlink()
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "missing synchronized runtime: " + name):
            self.verify()

    def test_required_file_claimed_by_manifest_must_exist_in_package(self):
        (self.bundle / "aarch64-windows/xtajit.dll").unlink()
        with self.assertRaises((KeyError, ValueError)):
            self.verify()

    def test_same_size_payload_tampering_is_detected(self):
        name = "i386-windows/kernelbase.dll"
        data = bytearray((self.bundle / name).read_bytes())
        data[-1] ^= 1
        self.replace_pe(name, bytes(data))
        with self.assertRaisesRegex(ValueError, "packaged runtime differs from build input"):
            self.verify()

    def test_payload_size_change_is_detected(self):
        name = "aarch64-windows/user32.dll"
        self.replace_pe(name, (self.bundle / name).read_bytes() + b"extra")
        with self.assertRaisesRegex(ValueError, "packaged runtime differs from build input"):
            self.verify()

    def test_manifest_paths_cannot_escape_or_alias_package_entries(self):
        unsafe = ("../escape.dll", "/escape.dll", "arm64ec-windows/../escape.dll",
                  "arm64ec-windows\\escape.dll", "arm64ec-windows//escape.dll",
                  "arm64ec-windows/./escape.dll")
        for name in unsafe:
            with self.subTest(path=name):
                self.manifest["pe_files"][name] = {"bytes": 128, "sha256": "0" * 64}
                self.save_manifest()
                with self.assertRaisesRegex(ValueError, "unsafe runtime path"):
                    self.verify()
                del self.manifest["pe_files"][name]

    def test_record_rejects_checkout_that_differs_from_committed_pin(self):
        def wrong_checkout(arguments, **kwargs):
            if arguments[-1] == "HEAD" and Path(arguments[2]).name == "FEX":
                return "9" * 40 + "\n"
            return self.git_pin(arguments, **kwargs)
        with self.assertRaisesRegex(ValueError, "FEX: checkout differs from committed pin"):
            self.record(wrong_checkout)

    def test_record_rejects_missing_required_native_link_input(self):
        (self.work / "app/Madeira/libntdll_unix.a").unlink()
        with self.assertRaises(FileNotFoundError):
            self.record()


if __name__ == "__main__":
    unittest.main()
