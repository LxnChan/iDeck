# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Historical diagnostic must stay explicit, isolated, and provenance checked."""
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('runtime223', ROOT / 'tools/build/build-runtime223.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class Runtime223Checks(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='ideck-runtime223-')
        self.addCleanup(temp.cleanup)
        self.work = Path(temp.name)

    def test_workflow_default_and_cache_isolation(self):
        text = (ROOT / '.github/workflows/build-ipa.yml').read_text(encoding='utf-8')
        self.assertIn('default: synced', text)
        self.assertIn("if: inputs.runtime_profile != 'build223'", text)
        self.assertIn("group: build-ipa-${{ github.ref }}-${{ inputs.runtime_profile || 'synced' }}", text)
        diagnostic = text.split('\n  runtime223:\n')[1]
        self.assertIn('ref: ' + runtime.BASELINE, diagnostic)
        self.assertNotIn('actions/cache', diagnostic)
        self.assertNotIn('check-synced-runtime', diagnostic)
        self.assertIn('inherited-source.tar.gz', diagnostic)
        self.assertIn('persist-credentials: false', diagnostic)

    def test_overlay_updates_swift_but_retains_native_bridge(self):
        current, legacy = self.work / 'current', self.work / 'legacy'
        names = ['app/Madeira/Library.swift', 'app/Madeira/Winios/Winios.m', 'app/project']
        for root in (current, legacy):
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'old')
        (current / names[0]).write_bytes(b'current Swift')
        (current / names[1]).write_bytes(b'new native bridge')
        with mock.patch.object(runtime, 'git', return_value=('\0'.join(names) + '\0').encode()):
            overlay = runtime.overlay_frontend(current, legacy)
            self.assertEqual([item['path'] for item in overlay], names[:1])
            self.assertEqual((legacy / names[0]).read_bytes(), b'current Swift')
            self.assertEqual((legacy / names[1]).read_bytes(), b'old')
            (current / names[2]).write_bytes(b'unreviewed project change')
            with self.assertRaisesRegex(ValueError, 'non-Swift'):
                runtime.overlay_frontend(current, legacy)

    def test_wrong_baseline_and_parameterized_historical_steps_fail(self):
        with mock.patch.object(runtime, 'git', return_value=b'wrong-sha\n'):
            with self.assertRaisesRegex(ValueError, 'not Build 223'):
                runtime.checked_baseline(self.work)
        workflow = b'      - name: Select\n        run: |\n          echo ${{ inputs.untrusted }}\n'
        with mock.patch.object(runtime, 'git', return_value=workflow):
            with self.assertRaisesRegex(ValueError, 'parameterized'):
                runtime.historical_script(self.work, 'Select')

    def test_runtime_package_rejects_changed_missing_extra_resources_and_wrong_marker(self):
        original = {'arm64ec-windows/xtajit64.dll': b'old xta',
                    'arm64ec-windows/dockhost.exe': b'old dock',
                    'prefix-template.tar.gz': b'old prefix'}
        plan = {'resource_sha256': {name: hashlib.sha256(data).hexdigest()
                                    for name, data in original.items()}}

        def write(files, marker='iDeck RT223'):
            ipa = self.work / 'fixture.ipa'
            with zipfile.ZipFile(ipa, 'w') as archive:
                archive.writestr('Payload/Madeira.app/Info.plist', plistlib.dumps(
                    {'CFBundleDisplayName': marker, 'MadeiraBuild': '235 runtime223'}))
                for name, data in files.items():
                    archive.writestr('Payload/Madeira.app/' + name, data)
            return ipa

        runtime.verify_packaged(write(original), plan)
        for files in (dict(original, **{'arm64ec-windows/xtajit64.dll': b'new xta'}),
                      {name: data for name, data in original.items() if not name.endswith('dockhost.exe')},
                      dict(original, **{'arm64ec-windows/extra.dll': b'unexpected'})):
            with self.assertRaisesRegex(ValueError, 'differs from Build 223'):
                runtime.verify_packaged(write(files), plan)
        with self.assertRaisesRegex(ValueError, 'marker missing'):
            runtime.verify_packaged(write(original, 'iDeck'), plan)

    def test_reference_inventory_rejects_wrong_build_and_hash(self):
        ipa = self.work / 'reference.ipa'
        ipa.write_bytes(b'reference')
        with self.assertRaisesRegex(ValueError, 'not the clean Build 223'):
            runtime.reference_files(ipa, {'build': '234'})
        with self.assertRaisesRegex(ValueError, 'differs from its original inventory'):
            runtime.reference_files(ipa, {'build': '223', 'findings': [], 'ipa_sha256': 'bad'})

    def test_reference_paths_cannot_escape(self):
        for name in ('../prefix-template.tar.gz', '/arm64ec-windows/ntdll.dll',
                     'arm64ec-windows/../../secret'):
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                runtime.runtime_resource(name)


if __name__ == '__main__':
    unittest.main()
