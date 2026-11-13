#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Hash versioned runtime inputs, excluding generated build trees and assets."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GROUPS = {
    'dependency': ('build/gnutls-ios/', 'build/ffmpeg/', 'build/freetype-ios/'),
    'windows': ('build/windows-runtime/', 'build/wine-pe/', 'build/wine-i386/',
                'build/faultrep/', 'build/fex-', 'build/dxmt-',
                'app/Madeira/arm64ec-windows/', 'app/Madeira/aarch64-windows/'),
    'native': ('build/',),
}


def main():
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    pins = {name: subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', f'HEAD:{name}'], text=True).strip()
            for name in ('FEX', 'wine', 'dxmt')}
    results = {}
    for group, prefixes in GROUPS.items():
        inputs = {}
        for name in paths:
            shared = (((name.startswith('tools/build/') and name not in
                        {'tools/build/package-runtime-source.py', 'tools/build/prepare-runtime-sources.sh'})
                       or name == '.github/workflows/build-ipa.yml')
                      if group != 'dependency' else name == 'tools/build/sync-gnutls-libs.sh')
            if (name.startswith(prefixes) or shared) and (ROOT / name).is_file():
                inputs[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        payload = {'schema': 1, 'inputs': inputs, 'pins': pins if group != 'dependency' else {}}
        results[group] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(''.join(f'{name}={value}\n' for name, value in results.items()))


if __name__ == '__main__':
    main()
