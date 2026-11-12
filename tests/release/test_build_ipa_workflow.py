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


def packaging_step():
    """Read the actual run block so regressions in the workflow affect these tests."""
    workflow = (ROOT / ".github/workflows/build-ipa.yml").read_text(encoding="utf-8")
    step = re.search(
        r"^      - name: Package IPA\n(?P<body>.*?)(?=^      - name:|\Z)",
        workflow, re.MULTILINE | re.DOTALL,
    )
    if step is None:
        raise AssertionError("Package IPA step is missing")
    block = re.search(r"^        run: \|\n(?P<script>.*)", step["body"],
                      re.MULTILINE | re.DOTALL)
    if block is None:
        raise AssertionError("Package IPA run block is missing")
    script = textwrap.dedent(block["script"])
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


if __name__ == "__main__":
    unittest.main()
