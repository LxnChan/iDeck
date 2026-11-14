# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Verify source export boundaries using disposable Git repositories."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "runtime_source_bundle", ROOT / "tools/build/package-runtime-source.py")
source_bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(source_bundle)


class RuntimeSourceBundleChecks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ideck-source-bundle-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        self.root = self.work / "checkout"
        self.make_repo(self.root, {"README.md": b"committed application source\n",
                                  ".gitignore": b"ignored/\nobj/\ntoolchains/\nresearch/\n"})
        for name in ("FEX", "wine", "dxmt"):
            child = self.root / name
            self.make_repo(child, {"component.txt": (name + " source\n").encode(),
                                   "LICENSE": b"retained component license\n"})
            self.set_pin(self.root, name, child)
        nested = self.root / "FEX/External/rpmalloc"
        self.make_repo(nested, {"allocator.txt": b"nested allocator source\n"})
        self.set_pin(self.root / "FEX", "External/rpmalloc", nested)
        self.set_pin(self.root, "FEX", self.root / "FEX")
        self.make_repo(self.root / "toolchains/llvm-project",
                       {"llvm/CMakeLists.txt": b"committed LLVM configuration\n"})
        self.make_repo(self.root / "research/freetype",
                       {"src/freetype.txt": b"committed FreeType source\n"})
        self.env = {"RUNTIME_LLVM_SOURCE": str(self.root / "toolchains/llvm-project"),
                    "RUNTIME_FREETYPE_SOURCE": str(self.root / "research/freetype")}
        self.output = self.work / "runtime-source.tar.gz"

    def git(self, repo, *arguments):
        return subprocess.check_output(
            ["git", "-C", str(repo), *arguments], stderr=subprocess.PIPE)

    def commit(self, repo):
        self.git(repo, "-c", "user.name=Source Fixture", "-c",
                 "user.email=fixture@example.invalid", "commit", "-m", "Source fixture")

    def make_repo(self, path, files):
        path.mkdir(parents=True)
        self.git(path, "init", "--initial-branch=main")
        for name, content in files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.git(path, "add", "--", *files)
        self.commit(path)

    def set_pin(self, parent, name, child):
        revision = self.git(child, "rev-parse", "HEAD").decode().strip()
        self.git(parent, "update-index", "--add", "--cacheinfo", "160000", revision, name)
        self.commit(parent)

    def package(self):
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            manifest = source_bundle.package(self.output, self.root)
        with tarfile.open(self.output, "r:gz") as archive:
            files = {member.name: archive.extractfile(member).read()
                     for member in archive if member.isfile()}
        self.assertEqual(json.loads(files["SOURCE_MANIFEST.json"]), manifest)
        return manifest, files

    def test_exports_exact_commits_nested_dependencies_licenses_and_source_archives(self):
        source = self.root / "dependency-source.tar.gz"
        source.write_bytes(b"tracked upstream source archive")
        self.git(self.root, "add", source.name)
        self.commit(self.root)
        manifest, files = self.package()
        prefix = source_bundle.PREFIX + "/"
        self.assertEqual(files[prefix + "README.md"], b"committed application source\n")
        self.assertEqual(files[prefix + "FEX/External/rpmalloc/allocator.txt"],
                         b"nested allocator source\n")
        self.assertEqual(files[prefix + "wine/LICENSE"], b"retained component license\n")
        self.assertEqual(files[prefix + "dependency-source.tar.gz"], source.read_bytes())
        self.assertIn(prefix + "toolchains/llvm-project/llvm/CMakeLists.txt", files)
        self.assertIn(prefix + "research/freetype/src/freetype.txt", files)
        for item in manifest["sources"]:
            repo = self.root if item["path"] == "." else self.root / item["path"]
            expected = self.git(repo, "rev-parse", "HEAD").decode().strip()
            self.assertEqual(item["revision"], expected)
            exported = self.git(repo, "archive", "--format=tar", "HEAD")
            self.assertEqual(item["git_archive_sha256"], hashlib.sha256(exported).hexdigest())

    def test_inherited_dependencies_require_verified_archives_and_are_recorded(self):
        companion = self.work / 'historical-source.tar.gz'
        companion.write_bytes(b'original companion sources')
        expected = hashlib.sha256(companion.read_bytes()).hexdigest()
        for supplied in ([], [(companion, 'wrong')]):
            with self.assertRaisesRegex(ValueError, 'required|hash mismatch'):
                source_bundle.package(self.output, self.root, inherited_dependencies=supplied)
        manifest = source_bundle.package(self.output, self.root,
                                         inherited_dependencies=[(companion, expected)])
        self.assertEqual(manifest['inherited_dependencies'],
                         [{'path': companion.name, 'sha256': expected}])
        self.assertNotIn('toolchains/llvm-project', [item['path'] for item in manifest['sources']])
        self.assertIn('FEX', manifest['pins'])

    def test_untracked_ignored_private_files_and_git_metadata_never_enter_archive(self):
        for name in ("untracked.txt", "ignored/credentials.txt", "obj/generated.o"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"PRIVATE WORKSPACE CONTENT")
        private = self.root / "device.mobileprovision"
        private.write_bytes(b"PRIVATE SIGNING PROFILE")
        self.git(self.root, "add", private.name)
        self.commit(self.root)
        manifest, files = self.package()
        self.assertFalse(any(".git" in Path(name).parts for name in files))
        self.assertFalse(any(b"PRIVATE" in data for data in files.values()))
        self.assertTrue(any(item["path"] == "device.mobileprovision"
                            for item in manifest["excluded"]))

    def test_committed_source_and_current_text_patch_are_kept_separate(self):
        repo = self.root / "wine"
        (repo / "component.txt").write_bytes(b"text change used during compilation\n")
        (repo / "binary.dll").write_bytes(b"MZ\0COMMITTED BINARY")
        self.git(repo, "add", "binary.dll")
        self.commit(repo)
        self.set_pin(self.root, "wine", repo)
        (repo / "binary.dll").write_bytes(b"MZ\0PRIVATE MODIFIED BINARY")
        (self.root / "toolchains/llvm-project/llvm/CMakeLists.txt").write_bytes(
            b"text iOS configuration applied by build script\n")
        manifest, files = self.package()
        prefix = source_bundle.PREFIX + "/"
        self.assertEqual(files[prefix + "wine/component.txt"], b"wine source\n")
        self.assertEqual(files[prefix + "wine/binary.dll"], b"MZ\0COMMITTED BINARY")
        wine_patch = files["build-changes/wine.patch"]
        self.assertIn(b"text change used during compilation", wine_patch)
        self.assertNotIn(b"binary.dll", wine_patch)
        self.assertIn(b"text iOS configuration", files["build-changes/toolchains__llvm-project.patch"])
        self.assertTrue(any(item["path"] == "wine/binary.dll"
                            and item["reason"] == "binary working-tree change"
                            for item in manifest["excluded"]))

    def test_disabled_binary_test_inputs_are_omitted_even_when_initialized(self):
        repo = self.root / "FEX"
        test_bins = repo / "External/fex-gcc-target-tests-bins"
        self.make_repo(test_bins, {"corpus.bin": b"DISABLED COMPILED TEST CACHE"})
        self.set_pin(repo, "External/fex-gcc-target-tests-bins", test_bins)
        cache = repo / "Source/Tests/TestBins/cache.bin"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"DISABLED COMPILED TEST CACHE")
        self.git(repo, "add", "Source/Tests/TestBins/cache.bin")
        self.commit(repo)
        self.set_pin(self.root, "FEX", repo)
        manifest, files = self.package()
        self.assertFalse(any("fex-gcc-target-tests-bins" in name or "/TestBins/" in name
                             for name in files))
        self.assertFalse(any(b"DISABLED COMPILED" in data for data in files.values()))
        self.assertIn("FEX/External/fex-gcc-target-tests-bins", manifest["pins"])

    def test_optional_uninitialized_pin_is_recorded_without_workspace_content(self):
        pin = self.git(self.root / "wine", "rev-parse", "HEAD").decode().strip()
        self.git(self.root, "update-index", "--add", "--cacheinfo", "160000", pin, "optional")
        self.commit(self.root)
        (self.root / "optional").mkdir()
        (self.root / "optional/private.txt").write_bytes(b"PRIVATE NON-GIT DIRECTORY")
        manifest, files = self.package()
        self.assertEqual(manifest["pins"]["optional"], pin)
        self.assertTrue(any(item["path"] == "optional" for item in manifest["excluded"]))
        self.assertNotIn(source_bundle.PREFIX + "/optional/private.txt", files)

    def test_environment_source_overrides_keep_canonical_archive_paths(self):
        llvm = self.work / "alternate/llvm"
        freetype = self.work / "alternate/freetype"
        self.make_repo(llvm, {"llvm/CMakeLists.txt": b"actual alternate LLVM Git source\n"})
        self.make_repo(freetype, {"src/freetype.txt": b"actual alternate FreeType Git source\n"})
        self.env.update(RUNTIME_LLVM_SOURCE=str(llvm), RUNTIME_FREETYPE_SOURCE=str(freetype))
        manifest, files = self.package()
        self.assertEqual(files[source_bundle.PREFIX + "/toolchains/llvm-project/llvm/CMakeLists.txt"],
                         b"actual alternate LLVM Git source\n")
        self.assertEqual(next(item["revision"] for item in manifest["sources"]
                              if item["path"] == "toolchains/llvm-project"),
                         self.git(llvm, "rev-parse", "HEAD").decode().strip())

    def test_missing_actual_llvm_git_source_fails_instead_of_packaging_headers(self):
        headers = self.work / "header-only-cache"
        headers.mkdir()
        (headers / "Module.h").write_bytes(b"cached LLVM header")
        self.env["RUNTIME_LLVM_SOURCE"] = str(headers)
        with self.assertRaisesRegex(ValueError, "required source Git checkout is missing"):
            self.package()
        self.assertFalse(self.output.exists())

    def test_checkout_different_from_committed_pin_is_rejected(self):
        repo = self.root / "FEX"
        (repo / "component.txt").write_bytes(b"different unpinned source\n")
        self.git(repo, "add", "component.txt")
        self.commit(repo)
        with self.assertRaisesRegex(ValueError, "source checkout differs from committed pin"):
            self.package()
        self.assertFalse(self.output.exists())

    def test_origin_credentials_are_not_published(self):
        self.git(self.root, "remote", "add", "origin",
                 "https://user:PRIVATE_TOKEN@github.com/example/source.git")
        manifest, files = self.package()
        self.assertEqual(manifest["sources"][0]["origin"],
                         "https://github.com/example/source.git")
        self.assertNotIn(b"PRIVATE_TOKEN", files["SOURCE_MANIFEST.json"])


if __name__ == "__main__":
    unittest.main()
