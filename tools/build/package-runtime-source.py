#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Export committed runtime sources and tracked text build patches, never build trees."""
import argparse
import copy
import hashlib
import io
import json
import os
import posixpath
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
PREFIX = 'source/iDeck'
DISABLED = (
    'FEX/External/fex-gcc-target-tests-bins',
    'FEX/External/fex-gvisor-tests-bins',
    'FEX/External/fex-posixtest-bins',
    'FEX/Source/Tests/TestBins',
)
BINARY_SUFFIXES = {'.a', '.o', '.dll', '.exe', '.dylib', '.metallib', '.ipa'}
PRIVATE_SUFFIXES = {'.p12', '.p8', '.key', '.mobileprovision'}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def excluded(name):
    path = PurePosixPath(name)
    return ('.git' in path.parts or path.suffix.lower() in PRIVATE_SUFFIXES or
            path.name.lower() in {'loginusers.vdf', 'localconfig.vdf', 'steam.exe',
                                 'steamwebhelper.exe', 'libcef.dll'} or
            path.name.lower().startswith('ssfn') or
            any(name == base or name.startswith(base + '/') for base in DISABLED))


def origin(repo):
    result = subprocess.run(['git', '-C', str(repo), 'remote', 'get-url', 'origin'],
                            capture_output=True, text=True)
    if result.returncode:
        return None
    url = result.stdout.strip()
    if '://' in url:
        parsed = urlsplit(url)
        if parsed.scheme not in {'https', 'http', 'ssh', 'git'}:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc.rsplit('@', 1)[-1],
                           parsed.path, '', ''))
    return url if url.startswith('git@') else None


def discover(repo, label, manifest, expected=None):
    if not (repo / '.git').exists():
        raise ValueError('required source Git checkout is missing: ' + label)
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    if expected and head != expected:
        raise ValueError('source checkout differs from committed pin: ' + label)
    result = [(repo, label, head)]
    for entry in git(repo, 'ls-tree', '-rz', '--full-tree', 'HEAD').split(b'\0'):
        if not entry:
            continue
        info, raw_name = entry.split(b'\t', 1)
        if not info.startswith(b'160000 '):
            continue
        child = raw_name.decode('utf-8')
        child_label = (label + '/' + child).lstrip('/')
        pin = info.split()[2].decode()
        manifest['pins'][child_label] = pin
        if excluded(child_label) or not (repo / child / '.git').exists():
            manifest['excluded'].append({'path': child_label, 'revision': pin,
                                         'reason': 'disabled test input' if excluded(child_label)
                                         else 'uninitialized optional submodule'})
            if not label and child in {'FEX', 'wine', 'dxmt'}:
                raise ValueError('required runtime submodule is uninitialized: ' + child)
            continue
        result.extend(discover(repo / child, child_label, manifest, pin))
    return result


def tracked_patch(repo, label, manifest):
    names = []
    for entry in git(repo, 'diff', '--no-ext-diff', '--no-renames', '--numstat',
                     '-z', 'HEAD').split(b'\0'):
        if not entry:
            continue
        added, removed, raw_name = entry.split(b'\t', 2)
        name = raw_name.decode('utf-8')
        full_name = (label + '/' + name).lstrip('/')
        if added == b'-' or removed == b'-' or PurePosixPath(name).suffix.lower() in BINARY_SUFFIXES:
            manifest['excluded'].append({'path': full_name, 'reason': 'binary working-tree change'})
        elif not excluded(full_name) and not (repo / name / '.git').exists():
            names.append(name)
    if not names:
        return b''
    return git(repo, 'diff', '--no-ext-diff', '--no-renames', 'HEAD', '--', *names)


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(data))


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def package(output, root=ROOT, *, inherited_dependencies=None):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('refusing to overwrite source package: ' + str(output))
    manifest = {'schema': 1, 'source_root': PREFIX, 'pins': {}, 'sources': [],
                'patches': [], 'excluded': [],
                'limits': 'Committed Git sources plus tracked text build changes. '
                          'System SDKs, binary build outputs and unchanged companion '
                          'runtime source obligations are supplied separately.'}
    repos = discover(root, '', manifest)
    # Historical diagnostic builds use verified companion archives for unchanged
    # precompiled dependencies, rather than claiming today's dependency pins.
    if inherited_dependencies is not None:
        if not inherited_dependencies:
            raise ValueError('verified inherited dependency archives are required')
        manifest['inherited_dependencies'] = []
        for path, expected in inherited_dependencies:
            path = Path(path)
            if file_sha(path) != expected:
                raise ValueError('inherited dependency archive hash mismatch: ' + path.name)
            manifest['inherited_dependencies'].append({'path': path.name, 'sha256': expected})
    for label, variable in (() if inherited_dependencies is not None else
                           (('toolchains/llvm-project', 'RUNTIME_LLVM_SOURCE'),
                            ('research/freetype', 'RUNTIME_FREETYPE_SOURCE'))):
        repos.extend(discover(Path(os.environ.get(variable, str(root / label))).resolve(),
                              label, manifest))
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(output, 'w:gz', format=tarfile.PAX_FORMAT) as destination:
            for repo, label, head in repos:
                with tempfile.TemporaryDirectory(prefix='ideck-source-archive-') as temp:
                    exported = Path(temp) / 'source.tar'
                    subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar',
                                    '--output', str(exported), 'HEAD'], check=True)
                    archive_sha = file_sha(exported)
                    count = 0
                    with tarfile.open(exported, 'r:') as source:
                        for member in source:
                            name = (label + '/' + member.name).lstrip('/')
                            if excluded(name):
                                manifest['excluded'].append({'path': name, 'reason': 'excluded archive input'})
                                continue
                            path = PurePosixPath(name)
                            if path.is_absolute() or '..' in path.parts:
                                raise ValueError('unsafe Git archive path: ' + name)
                            staged = copy.copy(member)
                            staged.name = PREFIX + '/' + name
                            staged.pax_headers = {}
                            if staged.issym():
                                target = posixpath.normpath(posixpath.join(
                                    str(PurePosixPath(staged.name).parent), staged.linkname))
                                if (PurePosixPath(staged.linkname).is_absolute() or
                                        not target.startswith(PREFIX + '/') or '.git' in PurePosixPath(target).parts):
                                    raise ValueError('unsafe Git archive symlink: ' + name)
                            if staged.islnk():
                                staged.linkname = PREFIX + '/' + (label + '/' + staged.linkname).lstrip('/')
                            destination.addfile(staged, source.extractfile(member) if member.isfile() else None)
                            count += 1
                    manifest['sources'].append({'path': label or '.', 'revision': head,
                                                'origin': origin(repo), 'git_archive_sha256': archive_sha,
                                                'members': count})
                patch = tracked_patch(repo, label, manifest)
                if patch:
                    name = 'build-changes/' + (label.replace('/', '__') or 'iDeck') + '.patch'
                    add_bytes(destination, name, patch)
                    manifest['patches'].append({'path': name, 'repository': label or '.',
                                               'sha256': hashlib.sha256(patch).hexdigest()})
            add_bytes(destination, 'SOURCE_MANIFEST.json',
                      (json.dumps(manifest, indent=2) + '\n').encode())
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    print(f'Exported {len(repos)} Git source trees to {output}')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package(args.output)
