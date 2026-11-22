# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Execute the workflow's packaging step with a controlled packager, without signing."""
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SHORT_SHA = "abc1234"
IPA_PATH = f"output/iDeck-fork-{SHORT_SHA}.ipa"
INVENTORY_PATH = f"output/iDeck-fork-{SHORT_SHA}.inventory.json"


def workflow_step(name):
    workflow = (ROOT / ".github/workflows/build-ipa.yml").read_text(encoding="utf-8")
    step = re.search(
        r"^      - name: " + re.escape(name) + r"\n(?P<body>.*?)(?=^      - name:|\Z)",
        workflow, re.MULTILINE | re.DOTALL,
    )
    if step is None:
        raise AssertionError(name + " step is missing")
    return step["body"]


def run_block(name):
    """Read the actual run block so workflow regressions affect these tests."""
    block = re.search(r"^        run: \|\n(?P<script>.*)", workflow_step(name),
                      re.MULTILINE | re.DOTALL)
    if block is None:
        raise AssertionError(name + " run block is missing")
    return textwrap.dedent(block["script"])


def run_group(name, group):
    commands = re.search(r'^echo "::group::' + re.escape(group) + r'"\n(.*?)'
                         r'^echo "::endgroup::"$', run_block(name), re.MULTILINE | re.DOTALL)
    if commands is None:
        raise AssertionError(group + " command group is missing")
    return "set -euo pipefail\n" + commands[1]


def fixture_expressions(script):
    values = {"ipa_path": IPA_PATH, "inventory_path": INVENTORY_PATH,
              "short_sha": SHORT_SHA}
    for name, value in values.items():
        script = re.sub(r"\$\{\{\s*steps\.package\.outputs\." + name + r"\s*\}\}",
                        value, script)
    if "${{" in script:
        raise AssertionError("An unresolved workflow expression needs a test fixture")
    return script


def packaging_step():
    script = run_block("Package IPA")
    script = re.sub(r"\$\{\{\s*inputs\.configuration\s*\|\|\s*'Debug'\s*\}\}",
                    "Debug", script)
    if "${{" in script:
        raise AssertionError("An unresolved workflow expression needs a test fixture")
    return script


def bash_executable():
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git/bin/bash.exe"
        if git_bash.is_file():
            return str(git_bash)
    return shutil.which("bash")


class BuildIPAWorkflowChecks(unittest.TestCase):
    def test_only_normal_build_remains(self):
        workflow = (ROOT / ".github/workflows/build-ipa.yml").read_text(encoding="utf-8")
        jobs = workflow.split("\njobs:\n", 1)[1]
        self.assertEqual(re.findall(r"^  ([\w-]+):\s*$", jobs, re.MULTILINE), ["build"])
        self.assertNotRegex(jobs, r"(?m)^    if:", msg="The normal build must not be profile-gated")
        self.assertIn("  group: build-ipa-${{ github.ref }}\n", workflow)
        for retired in ("runtime_profile", "runtime223", "build223", "build-runtime223.py"):
            self.assertNotIn(retired, workflow)


class BuildIPAPackagingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bash = bash_executable()
        if cls.bash is None:
            raise unittest.SkipTest("Bash is required to execute the GitHub Actions run block")
        cls.script = packaging_step()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="ideck-workflow-")
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)
        (self.work / "build/DerivedData/Build/Products/Debug-iphoneos/Madeira.app").mkdir(parents=True)
        (self.work / "app/Madeira").mkdir(parents=True)
        (self.work / "app/Madeira/Madeira.entitlements").write_text("fixture", encoding="utf-8")
        self.write_script("fake-bin/git", f"""\
            #!/bin/bash
            set -eu
            test "$*" = 'rev-parse --short HEAD'
            printf '%s\\n' '{SHORT_SHA}'
            """)
        self.write_script("fake-bin/python3", """\
            #!/bin/bash
            exec bash "$@"
            """)
        # The fake python3 executes only this fixture script. No real packaging
        # tools or codesign run; the surrounding workflow is unchanged.
        self.write_script("tools/package-ipa.py", """\
            #!/bin/bash
            set -eu
            test "$#" -eq 4
            test "$1" = 'build/DerivedData/Build/Products/Debug-iphoneos/Madeira.app'
            test "$2" = 'output/iDeck-fork-abc1234.ipa'
            test "$3" = '--entitlements'
            test "$4" = 'app/Madeira/Madeira.entitlements'
            test -d "$1"
            test -f "$4"
            inventory="${2%.ipa}.inventory.json"
            case "$PACKAGING_RESULT" in
                failure)
                    printf 'partial IPA' > "$2"
                    printf '{"findings": []}\\n' > "$inventory"
                    exit 23
                    ;;
                missing-inventory) printf 'IPA' > "$2" ;;
                empty-inventory) printf 'IPA' > "$2"; : > "$inventory" ;;
                missing-ipa) printf '{"findings": []}\\n' > "$inventory" ;;
                empty-ipa) : > "$2"; printf '{"findings": []}\\n' > "$inventory" ;;
                success)
                    printf 'IPA' > "$2"
                    printf '{"findings": []}\\n' > "$inventory"
                    ;;
                *) exit 99 ;;
            esac
            """)

    def write_script(self, relative, content):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content), encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def run_step(self, result):
        env = os.environ.copy()
        env.update(PACKAGING_RESULT=result, GITHUB_OUTPUT="github-output.txt")
        completed = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-c",
             'export PATH="$PWD/fake-bin:$PATH"\n' + self.script],
            cwd=self.work, env=env, capture_output=True, text=True, timeout=20,
        )
        output_file = self.work / "github-output.txt"
        outputs = dict(line.split("=", 1) for line in
                       output_file.read_text(encoding="utf-8").splitlines()) if output_file.exists() else {}
        return completed, outputs

    def assert_rejected(self, completed, outputs):
        self.assertNotEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertNotIn("ipa_path", outputs)
        self.assertNotIn("inventory_path", outputs)

    def test_packager_failure_rejects_leftover_artifacts(self):
        completed, outputs = self.run_step("failure")
        self.assertEqual(completed.returncode, 23, completed.stdout + completed.stderr)
        self.assertGreater((self.work / IPA_PATH).stat().st_size, 0)
        self.assertGreater((self.work / INVENTORY_PATH).stat().st_size, 0)
        self.assert_rejected(completed, outputs)

    def test_success_without_inventory_is_rejected(self):
        self.assert_rejected(*self.run_step("missing-inventory"))

    def test_success_with_empty_inventory_is_rejected(self):
        self.assert_rejected(*self.run_step("empty-inventory"))

    def test_success_without_ipa_is_rejected(self):
        self.assert_rejected(*self.run_step("missing-ipa"))

    def test_success_with_empty_ipa_is_rejected(self):
        self.assert_rejected(*self.run_step("empty-ipa"))

    def test_success_publishes_both_exact_paths(self):
        completed, outputs = self.run_step("success")
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(outputs["short_sha"], SHORT_SHA)
        self.assertEqual(outputs["ipa_name"], Path(IPA_PATH).name)
        self.assertEqual(outputs["ipa_path"], IPA_PATH)
        self.assertEqual(outputs["inventory_path"], INVENTORY_PATH)
        self.assertGreater((self.work / outputs["ipa_path"]).stat().st_size, 0)
        self.assertGreater((self.work / outputs["inventory_path"]).stat().st_size, 0)


class BuildIPAArtifactChecks(unittest.TestCase):
    def test_grouped_source_packaging_uses_fallback_checkouts_in_current_shell(self):
        bash = bash_executable()
        if bash is None:
            self.skipTest("Bash is required to execute grouped source packaging")
        with tempfile.TemporaryDirectory(prefix="ideck-source-env-") as directory:
            work = Path(directory)
            prepare = ROOT / "tools/build/prepare-runtime-sources.sh"
            source = prepare.read_text(encoding="utf-8")
            target = work / "tools/build/prepare-runtime-sources.sh"
            target.parent.mkdir(parents=True)
            target.write_text(source, encoding="utf-8", newline="\n")
            fake = work / "fake-bin"
            fake.mkdir()
            cases = []
            for name, variable in (("llvm-project", "RUNTIME_LLVM_SOURCE"),
                                   ("freetype", "RUNTIME_FREETYPE_SOURCE")):
                pin = re.search(r'([0-9a-f]{40}) ' + variable, source)[1]
                (work / "toolchains/runtime-sources" / name / ".git").mkdir(parents=True)
                cases.append(f'*/{name}) printf "%s\\n" "{pin}" ;;')
            # Cached headers lack Git metadata, so source preparation must use
            # its separate fallback checkouts without cloning anything.
            (work / "toolchains/llvm-project/llvm/include").mkdir(parents=True)
            (work / "research/freetype/include").mkdir(parents=True)
            (fake / "git").write_text(
                '#!/bin/bash\nset -eu\ntest "$1" = -C\n'
                'test "$3 $4" = "rev-parse HEAD"\ncase "$2" in\n' +
                '\n'.join(cases) + '\n*) exit 99 ;;\nesac\n',
                encoding="utf-8", newline="\n")
            (fake / "python3").write_text(textwrap.dedent('''\
                #!/bin/bash
                set -eu
                test "$1" = tools/build/package-runtime-source.py
                test -d "$RUNTIME_LLVM_SOURCE/.git"
                test -d "$RUNTIME_FREETYPE_SOURCE/.git"
                case "$RUNTIME_LLVM_SOURCE" in */toolchains/runtime-sources/llvm-project) ;; *) exit 98 ;; esac
                case "$RUNTIME_FREETYPE_SOURCE" in */toolchains/runtime-sources/freetype) ;; *) exit 97 ;; esac
                test "$3" = --mesa-sources
                test "$5" = --d3d8to9-sources
                test "$6" = build/d3d8to9/work/sources
                printf source > "$2"
                '''), encoding="utf-8", newline="\n")
            for script in fake.iterdir():
                script.chmod(0o755)
            (work / "output").mkdir()
            (work / "build/runtime-relink").mkdir(parents=True)
            env = os.environ.copy()
            for variable in ("RUNTIME_LLVM_SOURCE", "RUNTIME_FREETYPE_SOURCE"):
                env.pop(variable, None)
            env["GITHUB_ENV"] = "github-env.txt"
            script = fixture_expressions(run_group("Verify and package runtime artifacts",
                                                   "Package source and relink companions"))
            result = subprocess.run([bash, "--noprofile", "--norc", "-c",
                                     'export PATH="$PWD/fake-bin:$PATH"\n' + script],
                                    cwd=work, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((work / "output" / f"iDeck-fork-{SHORT_SHA}.source.tar.gz").is_file())
            self.assertTrue((work / "output" / f"iDeck-fork-{SHORT_SHA}.relink.tar.gz").is_file())
            exported = (work / "github-env.txt").read_text(encoding="utf-8")
            self.assertIn("RUNTIME_LLVM_SOURCE=", exported)
            self.assertIn("RUNTIME_FREETYPE_SOURCE=", exported)

    def upload(self, name):
        body = workflow_step(name)
        self.assertIn("uses: actions/upload-artifact@v4", body)
        self.assertIn("if-no-files-found: error", body)
        self.assertIn("retention-days: 14", body)
        self.assertIn("compression-level: 0", body)
        artifact = re.search(r"^          name: (.+)$", body, re.MULTILINE)
        paths = re.search(r"^          path: \|\n((?:^            .+\n)+)",
                          body, re.MULTILINE)
        self.assertIsNotNone(artifact)
        self.assertIsNotNone(paths)
        return (fixture_expressions(artifact[1]),
                set(fixture_expressions(paths[1]).split()))

    def test_ipa_download_does_not_include_source_or_relink_archives(self):
        name, paths = self.upload("Upload IPA Artifact")
        self.assertEqual(name, f"iDeck-fork-{SHORT_SHA}")
        self.assertEqual(paths, {IPA_PATH, INVENTORY_PATH,
                               f"output/iDeck-fork-{SHORT_SHA}.runtime.json",
                               f"output/iDeck-fork-{SHORT_SHA}.SHA256SUMS"})

    def test_source_download_is_separate_and_complete(self):
        name, paths = self.upload("Upload matching source artifact")
        self.assertEqual(name, f"iDeck-fork-{SHORT_SHA}-source")
        self.assertEqual(paths, {f"output/iDeck-fork-{SHORT_SHA}.source.tar.gz",
                               f"output/iDeck-fork-{SHORT_SHA}.source.SHA256SUMS"})

    def test_relink_download_is_separate_and_complete(self):
        name, paths = self.upload("Upload portable relink artifact")
        self.assertEqual(name, f"iDeck-fork-{SHORT_SHA}-relink")
        self.assertEqual(paths, {f"output/iDeck-fork-{SHORT_SHA}.relink.tar.gz",
                               f"output/iDeck-fork-{SHORT_SHA}.relink.SHA256SUMS"})

    def checksums(self, *, missing=None):
        bash = bash_executable()
        if bash is None:
            self.skipTest("Bash is required to execute the checksum run block")
        temp = tempfile.TemporaryDirectory(prefix="ideck-downloads-")
        self.addCleanup(temp.cleanup)
        work = Path(temp.name)
        (work / "output").mkdir()
        files = {".ipa", ".inventory.json", ".runtime.json", ".source.tar.gz", ".relink.tar.gz"}
        for suffix in files:
            if suffix != missing:
                (work / "output" / f"iDeck-fork-{SHORT_SHA}{suffix}").write_bytes(b"fixture")
        # Inspect input selection without requiring macOS's shasum on Windows.
        fake = work / "fake-bin/shasum"
        fake.parent.mkdir()
        fake.write_text("#!/bin/bash\nset -eu\ntest \"$1\" = -a\ntest \"$2\" = 256\n"
                        "shift 2\nfor path; do\n  test -s \"$path\"\n"
                        "  printf '%064d  %s\\n' 0 \"$path\"\ndone\n",
                        encoding="utf-8", newline="\n")
        fake.chmod(0o755)
        script = fixture_expressions(run_group("Verify and package runtime artifacts",
                                               "Generate artifact checksums"))
        result = subprocess.run([bash, "--noprofile", "--norc", "-c",
                                 'export PATH="$PWD/fake-bin:$PATH"\n' + script],
                                cwd=work, capture_output=True, text=True, timeout=20)
        return result, work / "output"

    def test_each_checksum_file_references_only_its_download(self):
        result, output = self.checksums()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        expected = {".SHA256SUMS": {".ipa", ".inventory.json", ".runtime.json"},
                    ".source.SHA256SUMS": {".source.tar.gz"},
                    ".relink.SHA256SUMS": {".relink.tar.gz"}}
        for manifest, suffixes in expected.items():
            lines = (output / f"iDeck-fork-{SHORT_SHA}{manifest}").read_text().splitlines()
            self.assertEqual({line.split("  ", 1)[1] for line in lines},
                             {f"iDeck-fork-{SHORT_SHA}{suffix}" for suffix in suffixes})

    def test_missing_companion_rejects_checksum_generation(self):
        result, _ = self.checksums(missing=".source.tar.gz")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
