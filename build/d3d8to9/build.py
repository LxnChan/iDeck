#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Build the shared i386 D3D8 -> D3D9 frontend from verified upstream sources.

Stage after the Wine/DXMT farms, including on cache hits. No Microsoft runtime
binaries are downloaded: D3DX9 is supplied by Wine and D3D9 by DXMT.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = 'd3d8to9-v1.16.0.tar.gz'
URL = 'https://codeload.github.com/crosire/d3d8to9/tar.gz/refs/tags/v1.16.0'
SHA256 = '49b8ff9d13d8e39b81dcd22733b1207cfd81aa69153f8d5346524b6b2079559d'
REVISION = '255338f698c8270b537f0a91a13f795f4f988250'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fetch(directory):
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / SOURCE
    if not archive.is_file() or digest(archive) != SHA256:
        temporary = archive.with_suffix('.part')
        for attempt in range(3):
            try:
                with urllib.request.urlopen(URL, timeout=60) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                break
            except (urllib.error.URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        if digest(temporary) != SHA256:
            temporary.unlink()
            raise ValueError('d3d8to9 source checksum mismatch')
        temporary.replace(archive)
    return archive


def unpack(archive, directory):
    with tarfile.open(archive) as source:
        source.extractall(directory, filter='data')
    return directory / 'd3d8to9-1.16.0'


def check_dll(path, objdump):
    spec = importlib.util.spec_from_file_location('d3d8_pe', ROOT / 'tools/check-synced-runtime.py')
    pe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pe)
    pe.check_pe('i386-windows/d3d8.dll', path.read_bytes())
    description = subprocess.check_output([str(objdump), '-p', str(path)], text=True)
    imports = {line.split(':', 1)[1].strip().lower()
               for line in description.splitlines() if 'DLL Name:' in line}
    if 'd3d9.dll' not in imports or imports & {'wined3d.dll', 'opengl32.dll'}:
        raise ValueError('D3D8 must reach DXMT through D3D9, without WineD3D/OpenGL')
    # The C++ library is static so new DLL dependencies cannot break the farm.
    allowed = {'d3d9.dll', 'kernel32.dll', 'user32.dll', 'shell32.dll', 'gdi32.dll',
               'advapi32.dll', 'msvcrt.dll', 'ucrtbase.dll'}
    unexpected = {name for name in imports if name not in allowed
                  and not name.startswith('api-ms-win-crt-')}
    if unexpected:
        raise ValueError('unexpected D3D8 runtime dependencies: ' + ', '.join(sorted(unexpected)))
    for name in ('Direct3DCreate8', 'DebugSetMute', 'ValidatePixelShader',
                 'ValidateVertexShader', 'D3D8GetSWInfo'):
        if name not in description:
            raise ValueError('missing D3D8 export: ' + name)
    return sorted(imports)


def build(toolchain, work, destination, bundle, jobs):
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = Path(toolchain).resolve() / 'bin'
    compiler = binaries / ('i686-w64-mingw32-clang++' + suffix)
    objdump = binaries / ('llvm-objdump' + suffix)
    windres = binaries / ('i686-w64-mingw32-windres' + suffix)
    if not all(path.is_file() for path in (compiler, objdump, windres)):
        raise ValueError('LLVM-MinGW i386 compiler, windres and objdump are required')
    work, destination, bundle = work.resolve(), destination.resolve(), bundle.resolve()
    work.mkdir(parents=True, exist_ok=True)
    archive = fetch(work / 'sources')
    # Always extract clean bytes; an old edited work tree is not a build input.
    source = unpack(archive, Path(tempfile.mkdtemp(prefix='source-', dir=work)))
    resource = work / 'd3d8-resource.o'
    subprocess.run([str(windres), '-I', str(source / 'res'),
                    str(source / 'res/d3d8to9.rc'), str(resource)], check=True)
    common = [str(compiler), '-std=c++17', '-O2', '-DNDEBUG', '-DD3D8TO9NOLOG',
              '-Wno-delete-non-virtual-dtor', '-Wno-unknown-pragmas']
    sources = sorted((source / 'source').glob('*.cpp')) + [HERE / 'compat.cpp']
    # Compile separately: CI can use all cores without a CMake host-generator
    # dependency, while keeping the upstream translation sources unchanged.
    from concurrent.futures import ThreadPoolExecutor
    objects = [work / (path.stem + '.o') for path in sources]

    def compile_one(pair):
        path, output = pair
        subprocess.run(common + ['-c', str(path), '-o', str(output)], check=True)

    with ThreadPoolExecutor(max_workers=jobs) as workers:
        list(workers.map(compile_one, zip(sources, objects)))
    dll = work / 'd3d8.dll'
    subprocess.run([str(compiler), '-shared', '-static', '-Wl,--kill-at',
                    *map(str, objects), str(resource), str(source / 'res/d3d8.def'),
                    '-ld3d9', '-luser32', '-lshell32', '-lgdi32', '-o', str(dll)], check=True)
    imports = check_dll(dll, objdump)
    probe = work / 'd3d8-probe-x86.exe'
    subprocess.run([str(compiler), '-O2', '-static', str(HERE / 'probe.cpp'),
                    '-ld3d8', '-luser32', '-o', str(probe)], check=True)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(dll, destination / dll.name)
    shutil.copy2(probe, destination / probe.name)
    licenses = bundle / 'licenses/d3d8to9'
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / 'LICENSE.md', licenses / 'LICENSE.md')
    manifest = {'version': '1.16.0', 'revision': REVISION, 'url': URL,
                'source_sha256': SHA256, 'dll_sha256': digest(dll), 'imports': imports,
                'limits': 'Host canary covers translation; DXMT and game rendering require device tests.'}
    (licenses / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print('Installed i386 D3D8 -> D3D9 frontend and device probe', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=os.environ.get('LLVM_MINGW'))
    parser.add_argument('--work', type=Path, default=HERE / 'work')
    parser.add_argument('--bundle', type=Path, default=ROOT / 'app/Madeira')
    parser.add_argument('--dest', type=Path)
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 4, 8))
    args = parser.parse_args()
    if args.toolchain is None:
        parser.error('set LLVM_MINGW or --toolchain')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    build(args.toolchain, args.work, args.dest or args.bundle / 'i386-windows',
          args.bundle, args.jobs)


if __name__ == '__main__':
    main()
