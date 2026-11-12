# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
import gzip
import importlib.util
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("check_prefix_template", ROOT / "tools/check-prefix-template.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
REGISTRY_DATA = b"WINE REGISTRY Version 2\n\n[Software] 1\n"


class PrefixTemplateChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "prefix-template.tar.gz"

    def tar_bytes(self, omitted=(), empty=(), layout="prefix/", extras=()):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name in ("system.reg", "user.reg", "userdef.reg"):
                if name in omitted:
                    continue
                data = b"" if name in empty else REGISTRY_DATA
                member = tarfile.TarInfo(layout + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            for member, data in extras:
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def write_archive(self, data):
        self.path.write_bytes(gzip.compress(data))
        return self.path

    def test_generated_prefix_layout(self):
        self.assertEqual(checker.validate(self.write_archive(self.tar_bytes())), 3)

    def test_root_layout_with_dot_prefix(self):
        checker.validate(self.write_archive(self.tar_bytes(layout="./")))

    def test_missing_file(self):
        with self.assertRaisesRegex(ValueError, "no such archive"):
            checker.validate(self.path)

    def test_empty_file_is_rejected(self):
        self.path.touch()
        with self.assertRaises(ValueError):
            checker.validate(self.path)

    def test_empty_tar_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "empty tar"):
            checker.validate(self.write_archive(self.tar_bytes(omitted=checker.REGISTRY_FILES)))

    def test_directory_only_tar_is_rejected(self):
        directory = tarfile.TarInfo("prefix/drive_c")
        directory.type = tarfile.DIRTYPE
        self.write_archive(self.tar_bytes(omitted=checker.REGISTRY_FILES, extras=[(directory, b"")]))
        with self.assertRaisesRegex(ValueError, "registry file"):
            checker.validate(self.path)

    def test_each_registry_file_is_required(self):
        for name in checker.REGISTRY_FILES:
            with self.subTest(name=name):
                self.write_archive(self.tar_bytes(omitted=[name]))
                with self.assertRaisesRegex(ValueError, name):
                    checker.validate(self.path)

    def test_empty_registry_is_rejected(self):
        self.write_archive(self.tar_bytes(empty=["system.reg"]))
        with self.assertRaisesRegex(ValueError, "system.reg"):
            checker.validate(self.path)

    def test_later_empty_registry_overwrite_is_rejected(self):
        member = tarfile.TarInfo("prefix/system.reg")
        self.write_archive(self.tar_bytes(extras=[(member, b"")]))
        with self.assertRaisesRegex(ValueError, "system.reg"):
            checker.validate(self.path)

    def test_symlink_does_not_substitute_for_registry(self):
        link = tarfile.TarInfo("prefix/system.reg")
        link.type, link.linkname = tarfile.SYMTYPE, "user.reg"
        self.write_archive(self.tar_bytes(omitted=["system.reg"], extras=[(link, b"")]))
        with self.assertRaisesRegex(ValueError, "system.reg"):
            checker.validate(self.path)

    def test_absolute_build_host_symlink_is_rejected(self):
        link = tarfile.TarInfo("prefix/drive_c/users/madeira/Documents")
        link.type, link.linkname = tarfile.SYMTYPE, "/Users/builder/Documents"
        self.write_archive(self.tar_bytes(extras=[(link, b"")]))
        with self.assertRaisesRegex(ValueError, "absolute host symlink"):
            checker.validate(self.path)

    def test_existing_temporary_symlink_exceptions(self):
        for target in ("../Documents", "/tmp/socket", "/var/socket", "/private/tmp/socket"):
            with self.subTest(target=target):
                link = tarfile.TarInfo("prefix/link")
                link.type, link.linkname = tarfile.SYMTYPE, target
                checker.validate(self.write_archive(self.tar_bytes(extras=[(link, b"")])))

    def test_gzip_checksum_is_verified_after_tar_end(self):
        data = bytearray(gzip.compress(self.tar_bytes()))
        data[-8] ^= 1  # CRC32 trailer, beyond the tar reader's terminator.
        self.path.write_bytes(data)
        with self.assertRaises(ValueError):
            checker.validate(self.path)

    def test_truncated_gzip_trailer_is_rejected(self):
        self.path.write_bytes(gzip.compress(self.tar_bytes())[:-8])
        with self.assertRaises(ValueError):
            checker.validate(self.path)

    def test_invalid_first_tar_header_is_rejected(self):
        with self.assertRaises(ValueError):
            checker.validate(self.write_archive(b"not a tar archive"))

    def test_invalid_header_after_registry_is_rejected(self):
        payload = tarfile.TarInfo("prefix/extra")
        payload.size = 1
        data = bytearray(self.tar_bytes(extras=[(payload, b"x")]))
        data[3 * 1024] ^= 1  # Change the fourth header without updating its checksum.
        with self.assertRaisesRegex(ValueError, "tar header"):
            checker.validate(self.write_archive(data))

    def test_truncated_member_is_rejected_even_with_valid_gzip(self):
        payload = tarfile.TarInfo("prefix/extra")
        payload.size = 2048
        data = self.tar_bytes(extras=[(payload, b"x" * payload.size)])
        with self.assertRaisesRegex(ValueError, "truncated tar member"):
            checker.validate(self.write_archive(data[:3 * 1024 + 512 + 100]))

    def test_missing_member_padding_is_rejected(self):
        payload = tarfile.TarInfo("prefix/extra")
        payload.size = 1
        data = self.tar_bytes(extras=[(payload, b"x")])
        with self.assertRaisesRegex(ValueError, "truncated tar member"):
            checker.validate(self.write_archive(data[:3 * 1024 + 512 + 1]))

    def test_cli_failure_is_actionable(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/check-prefix-template.py"), str(self.path)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("no such archive", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
