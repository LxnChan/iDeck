#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Record source pins/link inputs and verify that packaged PE files match them."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'legal/runtime-sync.json'
CORE = ('ntdll.dll', 'kernel32.dll', 'kernelbase.dll', 'user32.dll',
        'gdi32.dll', 'win32u.dll')
GRAPHICS = ('d3d11.dll', 'dxgi.dll', 'winemetal.dll')
REQUIRED = {
    'arm64ec-windows': CORE + GRAPHICS + ('xtajit64.dll', 'd3d9.dll', 'd3d10core.dll'),
    'aarch64-windows': CORE + GRAPHICS + ('xtajit.dll', 'wow64.dll', 'wow64win.dll'),
    'i386-windows': CORE + GRAPHICS + ('d3d9.dll', 'd3d10core.dll'),
}
LIBRARIES = (
    'FEX/build-ios/FEXCore/Source/libFEXCore.a',
    'FEX/build-ios/FEXCore/Source/libFEXCore_Base.a',
    'FEX/build-ios/FEXCore/Source/libJemallocLibs.a',
    'FEX/build-ios/External/fmt/libfmt.a',
    'FEX/build-ios/External/cephes/libcephes_128bit.a',
    'FEX/build-ios/External/xxhash/cmake_unofficial/libxxhash.a',
    'FEX/build-ios/External/SoftFloat-3e/libsoftfloat_3e.a',
    'app/Madeira/libntdll_unix.a', 'app/Madeira/libwin32u_unix.a',
    'app/Madeira/libwineserver.a', 'app/Madeira/libdxmt_combined.a',
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or str(path) != name:
        raise ValueError('unsafe runtime path: ' + name)
    return name


def check_pe(name, data):
    if len(data) < 64 or data[:2] != b'MZ':
        raise ValueError('not a PE file: ' + name)
    offset = struct.unpack_from('<I', data, 0x3c)[0]
    if offset + 24 > len(data) or data[offset:offset + 4] != b'PE\0\0':
        raise ValueError('invalid PE header: ' + name)
    machine = struct.unpack_from('<H', data, offset + 4)[0]
    arch = name.split('/')[0]
    allowed = {'arm64ec-windows': {0xa641, 0x8664},
               'aarch64-windows': {0xaa64}, 'i386-windows': {0x14c}}
    if arch not in allowed or machine not in allowed[arch]:
        raise ValueError(f'wrong PE machine {machine:#x}: {name}')


def require_files(files):
    for arch, names in REQUIRED.items():
        for name in names:
            if f'{arch}/{name}' not in files:
                raise ValueError(f'missing synchronized runtime: {arch}/{name}')


def record(bundle):
    pins = {}
    for component in ('FEX', 'wine', 'dxmt'):
        expected = subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', f'HEAD:{component}'], text=True).strip()
        actual = subprocess.check_output(
            ['git', '-C', str(ROOT / component), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != expected:
            raise ValueError(f'{component}: checkout differs from committed pin')
        pins[component] = actual
    files = {}
    for arch in REQUIRED:
        for path in sorted((bundle / arch).iterdir()):
            if path.suffix.lower() not in {'.dll', '.exe', '.drv', '.cpl', '.acm', '.ax', '.ocx'}:
                continue
            name = path.relative_to(bundle).as_posix()
            data = path.read_bytes()
            check_pe(name, data)
            files[name] = {'bytes': len(data), 'sha256': sha(data)}
    require_files(files)
    libraries = {}
    for name in LIBRARIES:
        data = (ROOT / name).read_bytes()
        if len(data) <= 8 or not data.startswith(b'!<arch>\n'):
            raise ValueError('missing or invalid native archive: ' + name)
        libraries[name] = {'bytes': len(data), 'sha256': sha(data)}
    patches = {path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
               for directory in ('build/fex-ios', 'build/fex-patches',
                                 'build/dxmt-ios', 'build/dxmt-patches')
               for path in sorted((ROOT / directory).glob('*.patch'))}
    result = {'schema': 1, 'pins': pins, 'patches': patches,
              'native_link_inputs': libraries, 'pe_files': files,
              'limits': 'Records build inputs and package integrity, not device execution. '
                        'Companion D3D12 and other unchanged runtimes retain their own provenance.'}
    output = bundle / MANIFEST
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Recorded {len(files)} PE files and {len(libraries)} native link inputs')


def verify_ipa(path, output=None):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate IPA paths')
        manifests = [name for name in names if name.startswith('Payload/')
                     and name.count('/') == 3 and name.endswith('.app/' + MANIFEST)]
        if len(manifests) != 1:
            raise ValueError('expected one runtime synchronization manifest in IPA')
        raw = archive.read(manifests[0])
        manifest = json.loads(raw)
        if manifest.get('schema') != 1:
            raise ValueError('unsupported runtime manifest schema')
        for name in manifest['pe_files']:
            safe_path(name)
        require_files(manifest['pe_files'])
        prefix = manifests[0][:-len(MANIFEST)]
        packaged = {name[len(prefix):] for name in names if name.startswith(prefix)
                    and name[len(prefix):].split('/')[0] in REQUIRED
                    and PurePosixPath(name).suffix.lower() in
                    {'.dll', '.exe', '.drv', '.cpl', '.acm', '.ax', '.ocx'}}
        if packaged != set(manifest['pe_files']):
            raise ValueError('packaged runtime file set differs from manifest')
        for name, item in manifest['pe_files'].items():
            data = archive.read(prefix + safe_path(name))
            check_pe(name, data)
            if len(data) != item['bytes'] or sha(data) != item['sha256']:
                raise ValueError('packaged runtime differs from build input: ' + name)
        if output:
            output.write_bytes(raw)
        print(f'IPA contains {len(manifest["pe_files"])} matching runtime files')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--record', type=Path)
    group.add_argument('--ipa', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.record:
        record(args.record)
    else:
        verify_ipa(args.ipa, args.output)


if __name__ == '__main__':
    main()
