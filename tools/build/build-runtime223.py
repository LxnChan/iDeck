#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Reproduce Build 223's runtime build chain with the current Swift frontend.

This is an opt-in diagnostic, NOT a byte-identical reproduction of the native
executable: Xcode and the SDK can differ. PE runtime files ARE checked byte for
byte against the original successful Actions artifact. No device data is read.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BASELINE = '47dfc1f2d9c4acb40c8602751be90e1757f62a17'
RUN = '43383581817'
REPOSITORY = 'LxnChan/iDeck'
ASSETS = {
    'iDeck-0.1.3-alpha.5-relink.tar.gz': 'eab1e9eb92c6f4c7328a3b27a80eebb1268bc8a4f0fcaeb96ed6095d6dedbf64',
    'iDeck-0.1.3-alpha.5-source.tar.gz': '01495925a27af91afb4f7f612c4ad1f8dd4276fa6a74ec50c86d50b32169cbb6',
    'iDeck-0.1.3-alpha.5-licenses-audit.tar.gz': '01726e89e00d9fe4ee80eb60466b5c27aaf9e59780fb95cb34ef64c9f39de81f',
}
FEX_LIBS = {
    'libFEXCore.a': 'FEXCore/Source', 'libFEXCore_Base.a': 'FEXCore/Source',
    'libJemallocLibs.a': 'FEXCore/Source', 'libfmt.a': 'External/fmt',
    'libcephes_128bit.a': 'External/cephes',
    'libxxhash.a': 'External/xxhash/cmake_unofficial',
    'libsoftfloat_3e.a': 'External/SoftFloat-3e',
}
RESOURCE_DIRS = {'aarch64-windows', 'arm64ec-windows', 'i386-windows',
                 'x86_64-vcruntime', 'd3d12', 'nls', 'fonts'}
RESOURCE_FILES = {'prefix-template.tar.gz', 'ideck-control.exe'}
STEPS = {
    'select': ['Select Xcode (prefer iOS 27 / 26 SDK)'],
    'tools': ['Install build tools (LLVM & Bison)'],
    'headers': ['Setup FEXCore generated headers', 'Setup Wine host headers'],
    'native': ['Rebuild modified Wine runtime libraries'],
    'licenses': ['Refresh bundled licenses'],
}


def run(*args, cwd=ROOT):
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def sha(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def load_tool(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked_baseline(root):
    if git(root, 'rev-parse', 'HEAD').decode().strip() != BASELINE:
        raise ValueError('diagnostic runtime checkout is not Build 223')


def historical_script(root, name):
    # Read committed historical scripts, never a modified workflow from disk.
    workflow = git(root, 'show', BASELINE + ':.github/workflows/build-ipa.yml').decode()
    match = re.search(r'^      - name: ' + re.escape(name) +
                      r'\n.*?^        run: \|\n(.*?)(?=^      - name:|\Z)',
                      workflow, re.M | re.S)
    if not match or '${{' in match[1]:
        raise ValueError('missing or parameterized historical step: ' + name)
    return textwrap.dedent(match[1])


def overlay_frontend(current, legacy):
    # Fail closed if later frontend/native changes need a new compatibility review.
    def tracked(root):
        return set(git(root, 'ls-files', '-z', '--', 'app').decode().strip('\0').split('\0'))
    old, new = tracked(legacy), tracked(current)
    if old != new:
        raise ValueError('frontend file set changed; review the diagnostic overlay')
    overlay = []
    for name in sorted(new):
        source, target = current / name, legacy / name
        if not source.is_file() or not target.is_file():
            raise ValueError('frontend contains a missing/non-regular file: ' + name)
        if source.read_bytes() == target.read_bytes():
            continue
        if name == 'app/Madeira/Winios/Winios.m':
            continue  # Deliberately retain the native bridge from Build 223.
        if not name.endswith('.swift'):
            raise ValueError('unreviewed non-Swift frontend change: ' + name)
        shutil.copyfile(source, target)
        overlay.append({'path': name, 'sha256': sha(target)})
    return overlay


def runtime_resource(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('unsafe reference resource path: ' + name)
    return bool(path.parts) and (path.parts[0] in RESOURCE_DIRS or name in RESOURCE_FILES)


def reference_files(ipa, inventory):
    if inventory.get('build') != '223' or inventory.get('findings'):
        raise ValueError('reference inventory is not the clean Build 223 artifact')
    if inventory.get('ipa_sha256') != sha(ipa):
        raise ValueError('reference IPA differs from its original inventory')
    prefix = 'Payload/Madeira.app/'
    expected = {item['path'][len(prefix):]: item['sha256']
                for item in inventory['files'] if item['path'].startswith(prefix)
                and runtime_resource(item['path'][len(prefix):])}
    for required in ('arm64ec-windows/xtajit64.dll', 'arm64ec-windows/dockhost.exe',
                     'aarch64-windows/ntdll.dll', 'i386-windows/ntdll.dll',
                     'prefix-template.tar.gz'):
        if required not in expected:
            raise ValueError('reference runtime incomplete: ' + required)
    return expected


def prepare(legacy):
    checked_baseline(legacy)
    plan = {'schema': 1, 'profile': 'build223', 'runtime_source_sha': BASELINE,
            'frontend_sha': git(ROOT, 'rev-parse', 'HEAD').decode().strip(),
            'reference_run': RUN, 'reference_repository': REPOSITORY,
            'swift_overlay': overlay_frontend(ROOT, legacy),
            'limits': 'Build 223 runtime build-chain reproduction, not a byte-identical '
                      'native rebuild. Current Xcode/SDK; inherited FEX/DXMT and dependency '
                      'libraries from the hash-pinned alpha.5 companion; old native Wine '
                      'patch scripts. Steam recovery requires an on-device test.'}
    cache = legacy / 'download_cache'
    cache.mkdir(exist_ok=True)
    for name, expected in ASSETS.items():
        path = cache / name
        if not path.exists():
            run('gh', 'release', 'download', 'v0.1.3-alpha.5', '--repo', 'kuscholar/iDeck',
                '--pattern', name, '--dir', cache)
        if sha(path) != expected:
            raise ValueError('historical companion checksum mismatch: ' + name)
    plan['companions'] = ASSETS
    reference = cache / 'reference223'
    run('gh', 'run', 'download', RUN, '--repo', REPOSITORY, '--name',
        'iDeck-fork-47dfc1f', '--dir', reference)
    ipa = reference / 'iDeck-fork-47dfc1f.ipa'
    inventory = json.loads((reference / 'iDeck-fork-47dfc1f.inventory.json').read_text())
    expected = reference_files(ipa, inventory)
    plan['reference_ipa_sha256'] = sha(ipa)
    plan['resource_sha256'] = expected
    app = legacy / 'app/Madeira'
    # Only generated library payloads from the pinned companion are extracted.
    with tarfile.open(cache / 'iDeck-0.1.3-alpha.5-relink.tar.gz', 'r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.parent == PurePosixPath('libraries') and path.suffix == '.a':
                if not member.isfile():
                    raise ValueError('non-regular companion library')
                (app / path.name).write_bytes(archive.extractfile(member).read())
    for name, directory in FEX_LIBS.items():
        target = legacy / 'FEX/build-ios' / directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(app / name, target)
    for name in RESOURCE_DIRS:
        target = app / name
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
    with zipfile.ZipFile(ipa) as archive:
        for name, expected_sha in expected.items():
            data = archive.read('Payload/Madeira.app/' + name)
            if hashlib.sha256(data).hexdigest() != expected_sha:
                raise ValueError('reference resource hash mismatch: ' + name)
            target = app / name
            if name == 'ideck-control.exe':
                target = legacy / 'build/ideck-control/ideck-control.exe'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        framework = legacy / 'app/Frameworks/StikJIT.xcframework/ios-arm64/StikJIT.framework'
        framework.mkdir(parents=True, exist_ok=True)
        for name in ('StikJIT', 'Info.plist'):
            (framework / name).write_bytes(archive.read(
                'Payload/Madeira.app/Frameworks/StikJIT.framework/' + name))
        (framework / 'StikJIT').chmod(0o755)
    run(sys.executable, ROOT / 'tools/check-prefix-template.py', app / 'prefix-template.tar.gz')
    write_json(legacy / 'build/runtime223.json', plan)


def build(legacy):
    config = os.environ.get('DIAGNOSTIC_CONFIGURATION', 'Debug')
    if config not in {'Debug', 'Release'}:
        raise ValueError('invalid build configuration')
    number = os.environ.get('DIAGNOSTIC_BUILD_NUMBER') or str(150 + int(os.environ['GITHUB_RUN_NUMBER']))
    bundle_id = os.environ.get('DIAGNOSTIC_BUNDLE_ID') or 'com.kuschqin.madeira.steamui'
    log = legacy / 'build/xcode-runtime223.log'
    command = ['xcodebuild', '-project', 'app/Madeira.xcodeproj', '-scheme', 'Madeira',
               '-configuration', config, '-destination', 'generic/platform=iOS',
               '-derivedDataPath', 'build/DerivedData', 'CODE_SIGNING_ALLOWED=NO',
               'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY=',
               'MADEIRA_BUNDLE_IDENTIFIER=' + bundle_id, 'CURRENT_PROJECT_VERSION=' + number,
               'IPHONEOS_DEPLOYMENT_TARGET=17.0', 'build']
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen(command, cwd=legacy, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            stream.write(line)
            print(line, end='', flush=True)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, command)
    app = legacy / f'build/DerivedData/Build/Products/{config}-iphoneos/Madeira.app'
    frontend = git(ROOT, 'rev-parse', '--short', 'HEAD').decode().strip()
    for path in (app / 'Info.plist', app / 'PlugIns/MadeiraJITHelper.appex/Info.plist'):
        info = plistlib.loads(path.read_bytes())
        info['CFBundleVersion'] = number
        if path == app / 'Info.plist':
            info['CFBundleDisplayName'] = 'iDeck RT223'
            info['MadeiraBuild'] = f'{number} runtime223 frontend={frontend} baseline=47dfc1f'
        else:
            info['CFBundleIdentifier'] = bundle_id + '.JITHelper'
        path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))


def verify_packaged(ipa, plan):
    with zipfile.ZipFile(ipa) as archive:
        prefix = 'Payload/Madeira.app/'
        info = plistlib.loads(archive.read(prefix + 'Info.plist'))
        if info.get('CFBundleDisplayName') != 'iDeck RT223' or 'runtime223' not in info.get('MadeiraBuild', ''):
            raise ValueError('diagnostic package marker missing')
        actual = {name[len(prefix):]: hashlib.sha256(archive.read(name)).hexdigest()
                  for name in archive.namelist() if name.startswith(prefix)
                  and not name.endswith('/') and runtime_resource(name[len(prefix):])}
        # Ad-hoc codesigning changes the converter Mach-O, but not the PE farms,
        # shaders, prefix or other runtime resources.
        expected = dict(plan['resource_sha256'])
        for name in list(expected):
            if name.endswith('.dylib'):
                if name not in actual:
                    raise ValueError('packaged native converter is missing')
                expected.pop(name)
                actual.pop(name)
        if actual != expected:
            changed = sorted(set(actual) ^ set(expected) |
                             {name for name in actual.keys() & expected.keys()
                              if actual[name] != expected[name]})
            raise ValueError('packaged runtime differs from Build 223: ' + ', '.join(changed[:20]))


def package(legacy):
    output = ROOT / 'output'
    output.mkdir(exist_ok=True)
    short = git(ROOT, 'rev-parse', '--short', 'HEAD').decode().strip()
    stem = 'iDeck-fork-' + short
    config = os.environ.get('DIAGNOSTIC_CONFIGURATION', 'Debug')
    app = legacy / f'build/DerivedData/Build/Products/{config}-iphoneos/Madeira.app'
    ipa = output / (stem + '.ipa')
    run(sys.executable, ROOT / 'tools/package-ipa.py', app, ipa, '--entitlements',
        legacy / 'app/Madeira/Madeira.entitlements')
    plan = json.loads((legacy / 'build/runtime223.json').read_text())
    verify_packaged(ipa, plan)
    plan['native_library_sha256'] = {p.name: sha(p) for p in sorted((legacy / 'app/Madeira').glob('*.a'))}
    plan['xcode'] = subprocess.check_output(['xcodebuild', '-version'], text=True).strip()
    plan['sdk'] = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-version'], text=True).strip()
    plan['ipa_sha256'] = sha(ipa)
    write_json(output / (stem + '.runtime.json'), plan)
    run(sys.executable, ROOT / 'tools/prepare-relink.py', legacy / 'build/xcode-runtime223.log',
        legacy / 'build/runtime-relink')
    run(sys.executable, legacy / 'build/runtime-relink/relink.py', '--verify-inputs',
        '--framework-path', legacy / 'app/Frameworks/StikJIT.xcframework/ios-arm64')
    with tarfile.open(output / (stem + '.relink.tar.gz'), 'w:gz') as archive:
        archive.add(legacy / 'build/runtime-relink', arcname='.')
    inherited = []
    for name in ASSETS:
        if 'relink' not in name:
            target = output / (stem + ('.inherited-source.tar.gz' if '-source.' in name
                                      else '.inherited-licenses.tar.gz'))
            shutil.copyfile(legacy / 'download_cache' / name, target)
            inherited.append((target, ASSETS[name]))
    source = load_tool('source_bundle', ROOT / 'tools/build/package-runtime-source.py')
    source.package(output / (stem + '.source.tar.gz'), legacy, inherited_dependencies=inherited)
    run('git', 'archive', '--format=tar.gz', '--output', output / (stem + '.diagnostic-tools.tar.gz'),
        'HEAD', 'tools', '.github/workflows/build-ipa.yml', 'docs/RUNTIME223_DIAGNOSTIC.md')
    groups = {'': ['.ipa', '.inventory.json', '.runtime.json'],
              '.source': ['.source.tar.gz', '.inherited-source.tar.gz',
                          '.inherited-licenses.tar.gz', '.diagnostic-tools.tar.gz'],
              '.relink': ['.relink.tar.gz']}
    for group, suffixes in groups.items():
        (output / (stem + group + '.SHA256SUMS')).write_text(''.join(
            sha(output / (stem + suffix)) + '  ' + stem + suffix + '\n' for suffix in suffixes))
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
        stream.write('short_sha=' + short + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'build', 'package', *STEPS])
    parser.add_argument('--legacy-root', type=Path, default=ROOT / 'build/runtime223')
    options = parser.parse_args()
    legacy = options.legacy_root.resolve()
    checked_baseline(legacy)
    if options.phase in STEPS:
        for name in STEPS[options.phase]:
            run('bash', '-e', '-o', 'pipefail', '-c', historical_script(legacy, name), cwd=legacy)
    else:
        {'prepare': prepare, 'build': build, 'package': package}[options.phase](legacy)


if __name__ == '__main__':
    main()
