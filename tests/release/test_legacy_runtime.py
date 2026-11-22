# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Guard cross-language pins and required on-device installer delivery."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LegacyRuntimeDeliveryChecks(unittest.TestCase):
    def test_downloader_and_installer_agree_on_both_hashes(self):
        core = (ROOT / 'app/Madeira/LegacyRuntimeCore.swift').read_text(encoding='utf-8')
        helper = (ROOT / 'build/legacy-runtime/install.c').read_text(encoding='utf-8')
        for swift, c in [('sha256', 'package_hash'), ('dllSHA256', 'runtime_hash')]:
            a = re.search(r'static let ' + swift + r' = "([a-f0-9]{64})"', core)[1]
            b = re.search(c + r'\[\] = "([a-f0-9]{64})"', helper)[1]
            self.assertEqual(a, b)

    def test_installer_is_built_before_runtime_record_and_has_sources_in_xcode(self):
        workflow = (ROOT / '.github/workflows/build-ipa.yml').read_text(encoding='utf-8')
        self.assertLess(workflow.index('run: python3 -B build/legacy-runtime/build.py'),
                        workflow.index('name: Verify and record synchronized runtime inputs'))
        self.assertIn('check-legacy-runtime.py --require-swift', workflow)
        project = (ROOT / 'app/Madeira.xcodeproj/project.pbxproj').read_text(encoding='utf-8')
        for name in ['LegacyRuntime.swift', 'LegacyRuntimeCore.swift']:
            self.assertIn(name + ' in Sources', project)
        definitions = re.findall(r'^\s*([A-F0-9]{24}|A[0-9]{7}) /\*.*?\*/ = \{', project, re.MULTILINE)
        self.assertEqual(len(definitions), len(set(definitions)), 'Duplicate Xcode object IDs')


if __name__ == '__main__': unittest.main()
