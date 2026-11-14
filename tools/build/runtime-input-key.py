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
    'headers': ('tools/build/build-wine.sh', 'tools/build/setup-llvm-mingw.sh'),
    'windows': ('build/windows-runtime/', 'build/wine-pe/', 'build/wine-i386/',
                'build/faultrep/', 'build/wintypes-compat/',
                'build/fex-arm64ec/', 'build/fex-wow64/', 'build/fex-patches/',
                'build/fex-ios/apply-cpuid.sh', 'build/fex-ios/fex-cpuid-bmi-fma.patch',
                'build/dxmt-ios/build-pe.sh', 'build/dxmt-ios/xcode27-metal-atomic.patch',
                'build/dxmt-patches/', 'tools/build/build-windows-runtime.sh',
                'app/Madeira/arm64ec-windows/', 'app/Madeira/aarch64-windows/',
                'app/Madeira/i386-windows/'),
    'native': ('build/fex-ios/', 'build/fex-patches/', 'build/ntdll-unix/',
               'build/win32u-unix/', 'build/wineserver/', 'build/madsync/',
               'build/crypto-unix/', 'build/dxmt-ios/', 'build/dxmt-patches/',
               'build/madeira-d3d12/deps.sh', 'madeira-d3d12/src/',
               'madeira-d3d12/tests/native/msc_canary.mm',
               'madeira-d3d12/third_party/metal-shader-converter/',
               'tools/build/build-native-runtime.sh', 'tools/build/build-llvm-ios.sh',
               'tools/build/stage-metal-converter.sh'),
}
PINS = {'dependency': (), 'headers': ('wine',),
        'windows': ('FEX', 'wine', 'dxmt'), 'native': ('FEX', 'wine', 'dxmt')}
SHARED = ('tools/build/build-wine.sh', 'tools/build/setup-llvm-mingw.sh')
SHADERS = ('tools/build/build-shader-headers.sh',)


def main():
    paths = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    pins = {name: subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', f'HEAD:{name}'], text=True).strip()
            for name in ('FEX', 'wine', 'dxmt')}
    results = {}
    for group, prefixes in GROUPS.items():
        inputs = {}
        for name in paths:
            shared = ((group in {'windows', 'native'} and name.startswith(SHARED + SHADERS))
                      or (group in {'dependency', 'native'} and
                          (name.startswith(GROUPS['dependency']) or
                           name == 'tools/build/sync-gnutls-libs.sh')))
            # Build commands live in the versioned recipes above. Workflow
            # scheduling, reporting and artifact edits do not change binaries.
            if (name.startswith(prefixes) or shared) and not name.endswith('.md') and (ROOT / name).is_file():
                inputs[name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        payload = {'schema': 2, 'inputs': inputs,
                   'pins': {name: pins[name] for name in PINS[group]}}
        results[group] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(''.join(f'{name}={value}\n' for name, value in results.items()))


if __name__ == '__main__':
    main()
