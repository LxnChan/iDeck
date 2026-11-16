#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
"""Build an opt-in x64 Mesa WGL/D3D12 driver using the pinned LLVM-MinGW.

No Microsoft binary redistributables are fetched or bundled. Mesa emits DXIL;
Madeira's Metal converter consumes it without the Windows DXIL signing service.
The canary must still be run on a device to establish Metal compatibility.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCES = {
    'mesa-25.0.7.tar.xz': (
        'https://archive.mesa3d.org/mesa-25.0.7.tar.xz',
        '592272df3cf01e85e7db300c449df5061092574d099da275d19e97ef0510f8a6',
        'mesa-25.0.7'),
    'DirectX-Headers-v1.614.1.tar.gz': (
        'https://codeload.github.com/microsoft/DirectX-Headers/tar.gz/refs/tags/v1.614.1',
        '344eb454c979ea68d8255d82c818bf7daf01f5109d26ac104f9911d18fae3b21',
        'DirectX-Headers-1.614.1'),
}
DLLS = ('opengl32-mesa.dll', 'madeira-mesa-gl.dll')
PROBE = 'opengl-probe-x64.exe'
MANIFEST = 'mesa-d3d12.json'
PATCHES = (
    (
        '0001-allow-private-submission-fences.patch',
        'src/gallium/drivers/d3d12/d3d12_screen.cpp',
        '38a80a573863b0ec914d371243249168850bfeb46064cb3f5c89e19f6669bcb6',
        '5adf786a31dd8080311e4b95c297f821772283024c8d21c8afa17da035e30926',
    ),
    (
        '0002-accept-identical-window-pixel-format.patch',
        'src/gallium/frontends/wgl/stw_framebuffer.c',
        '14473de16fba8f0ef2f1f5d0a20899d870850605f3c7738d5467cceccbc84165',
        '65fc465bcca16c44027c0a2f05e5bef9919d9bc807b0bf491a93447370e3c608',
    ),
    (
        '0003-log-wgl-context-initialization.patch',
        'src/gallium/frontends/wgl/stw_context.c',
        '40130452ac8b0b908b4921d18b3e6ba2cf29acc595994bd0b24d1853f5b67312',
        'f83b63d0b287720449c2ff1a0efad3b2286b7b3450c68800bb55b345c073f98c',
    ),
    # Point feedback patches (Mesa MIT license, original notices retained).
    (
        '0004-point-xfb-d3d12_compiler.patch',
        'src/gallium/drivers/d3d12/d3d12_compiler.h',
        '2287466997584154f49f849098abde0cf5607f8fbda200aff93d1ecbb2b9a5af',
        'a3e72155f48ddfa8098917a7cdb1c45fc35f07aa1ee074ba8ec146a14fa46a5b',
    ),
    (
        '0005-point-xfb-d3d12_context.patch',
        'src/gallium/drivers/d3d12/d3d12_context.h',
        'f17e92c2007b0705b69e71e1ba36db4991ed8a05083d02be6c67c92b5469504a',
        'afd36976610b824c14921b7bbf3e6b1e08b7678c3b02efe70372ff9f2a53ff1a',
    ),
    (
        '0006-point-xfb-d3d12_context_graphics.patch',
        'src/gallium/drivers/d3d12/d3d12_context_graphics.cpp',
        '6e763c8116c1cd240c7741410defba0b0250effb1e7f61ca1d2aaa3146cbc0ac',
        '1c4ed6bbfd4594243d6adb9ee8231c881d3114a5416177cea6dc7587cf60e914',
    ),
    (
        '0007-point-xfb-d3d12_compiler.patch',
        'src/gallium/drivers/d3d12/d3d12_compiler.cpp',
        '64fbb20e2048fb933882db171ba353dc4d46f7b29d4fcf3d97087f33bf88d590',
        '96990764b826fe2c5f87505098582c46ecd8591bf45d22b2c7546bf5978bdca7',
    ),
    (
        '0008-point-xfb-d3d12_draw.patch',
        'src/gallium/drivers/d3d12/d3d12_draw.cpp',
        '160644dda40619237a89bdf80221714c18ede9b0ed3156bcb30a4d8cdf9fe3a5',
        '8dd0b7ca2130ddb460242baf34ea766338b6d130e8ae952ca00b73112a6fa126',
    ),
    (
        '0009-point-xfb-d3d12_pipeline_state.patch',
        'src/gallium/drivers/d3d12/d3d12_pipeline_state.cpp',
        'b6085bbee257d59e48c3a68be8c2fea56341792cfeab9e2b09afb04e4dcbb7d6',
        '5e6bee63ff735e82fd9bb2229d7383419d53b1a14b26f4ebd92ec65e379db515',
    ),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recipe_key():
    inputs = {p.name: sha(p) for p in (HERE / 'build.py', HERE / 'probe.c', HERE / 'requirements.txt')}
    inputs.update(patch_manifest())
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def patch_manifest():
    return {'patches/' + name: sha(HERE / 'patches' / name) for name, *_ in PATCHES}


def apply_patches(source):
    for name, relative, before, after in PATCHES:
        target = source / relative
        actual = sha(target)
        if actual == after:
            continue
        if actual != before:
            raise ValueError('unexpected Mesa patch input: ' + relative)
        patch = (HERE / 'patches' / name).resolve()
        command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.eol=lf',
                   'apply', '--no-index', '--whitespace=error']
        subprocess.run(command + ['--check', str(patch)], cwd=source, check=True)
        subprocess.run(command + [str(patch)], cwd=source, check=True)
        if sha(target) != after:
            raise ValueError('Mesa patch output checksum mismatch: ' + relative)


def download(path, url, expected):
    if not path.exists() or sha(path) != expected:
        part = path.with_suffix(path.suffix + '.part')
        print('Downloading', path.name, flush=True)
        with urllib.request.urlopen(url, timeout=60) as response, part.open('wb') as output:
            shutil.copyfileobj(response, output)
        if sha(part) != expected:
            part.unlink()
            raise ValueError('source checksum mismatch: ' + path.name)
        part.replace(path)


def extract(archive, destination):
    # Accept only regular files/directories inside the archive's own root.
    # Mesa's disabled CI fixtures include symlinks; they are not build inputs.
    destination = destination.resolve()
    with tarfile.open(archive) as source:
        for member in source:
            target = (destination / member.name).resolve()
            if not target.is_relative_to(destination):
                raise ValueError('unsafe source archive member')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.extractfile(member) as stream, target.open('wb') as output:
                    shutil.copyfileobj(stream, output)
                target.chmod(member.mode & 0o777)


def verify(dist):
    manifest = json.loads((dist / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('recipe') != recipe_key() or manifest.get('sources') != {
            name: values[1] for name, values in SOURCES.items()} or manifest.get('patches') != patch_manifest():
        raise ValueError('cached Mesa recipe, patches or source pins do not match')
    required = {*DLLS, PROBE, *('sources/' + name for name in SOURCES)}
    if not required.issubset(manifest['files']):
        raise ValueError('incomplete Mesa distribution')
    for name, expected in manifest['files'].items():
        path = (dist / name).resolve()
        if not path.is_relative_to(dist.resolve()) or sha(path) != expected:
            raise ValueError('Mesa distribution checksum mismatch: ' + name)
    for name, (_, expected, _) in SOURCES.items():
        if sha(dist / 'sources' / name) != expected:
            raise ValueError('Mesa source archive does not match pinned checksum: ' + name)
    spec = importlib.util.spec_from_file_location('mesa_pe', ROOT / 'tools/check-wine-media-dlls.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    allowed = {'madeira-mesa-gl.dll', 'advapi32.dll', 'bcrypt.dll', 'comdlg32.dll',
               'gdi32.dll', 'kernel32.dll', 'ole32.dll', 'oleaut32.dll', 'shell32.dll',
               'user32.dll', 'version.dll', 'winspool.drv', 'ws2_32.dll', 'ucrtbase.dll',
               'api-ms-win-core-synch-l1-2-0.dll'}
    for name in DLLS:
        pe = module.PE(dist / name)
        offset = pe.unpack('<I', 0x3c)[0]
        if pe.unpack('<H', offset + 4)[0] != 0x8664:
            raise ValueError('Mesa driver must be x86-64')
        imports = pe.imports() | pe.imports(delayed=True)
        unexpected = {n for n in imports if n not in allowed and not n.startswith('api-ms-win-crt-')}
        if unexpected:
            raise ValueError(f'{name}: unexpected runtime dependencies: {sorted(unexpected)}')
    exports = module.PE(dist / DLLS[0]).exports()
    for name in ('wglChoosePixelFormat', 'wglSetPixelFormat', 'wglCreateContext',
                 'wglMakeCurrent', 'wglGetProcAddress', 'wglSwapBuffers', 'glGetString', 'glReadPixels'):
        if not exports.get(name):
            raise ValueError('missing Mesa export: ' + name)
    return manifest


def build(args):
    work, dist = args.work.resolve(), args.dist.resolve()
    work.mkdir(parents=True, exist_ok=True)
    dist.mkdir(parents=True, exist_ok=True)
    sources = dist / 'sources'
    sources.mkdir(exist_ok=True)
    for name, (url, expected, directory) in SOURCES.items():
        download(sources / name, url, expected)
        if not (work / directory / 'meson.build').is_file():
            extract(sources / name, work)
    source = work / 'mesa-25.0.7'
    apply_patches(source)
    headers = source / 'subprojects/DirectX-Headers-1.0'
    if not headers.exists():
        shutil.copytree(work / 'DirectX-Headers-1.614.1', headers)
    toolchain = args.toolchain.resolve() / 'bin'
    suffix = '.exe' if os.name == 'nt' else ''
    def tool(name):
        path = toolchain / (name + suffix)
        if not path.is_file():
            raise ValueError('missing LLVM-MinGW tool: ' + str(path))
        return path.as_posix()
    tools = {key: tool(value) for key, value in {
        'c': 'x86_64-w64-mingw32-clang', 'cpp': 'x86_64-w64-mingw32-clang++',
        'ar': 'llvm-ar', 'strip': 'llvm-strip', 'windres': 'x86_64-w64-mingw32-windres'}.items()}
    cross = work / 'x64.ini'
    cross.write_text('[binaries]\n' + ''.join(f"{key} = '{value}'\n" for key, value in tools.items()) +
                     "pkg-config = 'pkg-config'\n[host_machine]\nsystem = 'windows'\n"
                     "cpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n"
                     "[built-in options]\nc_link_args = ['-static']\ncpp_link_args = ['-static']\n",
                     encoding='utf-8')
    env = os.environ.copy()
    env['PATH'] = str(toolchain) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env['PATH']
    env['PYTHONUTF8'] = '1'
    output = work / 'build-x64'
    options = ['--buildtype=release', '--wrap-mode=nodownload', '-Dgallium-drivers=d3d12',
               '-Dvulkan-drivers=', '-Dplatforms=windows', '-Dllvm=disabled',
               '-Dgles1=disabled', '-Dgles2=disabled', '-Degl=disabled', '-Dglx=disabled',
               '-Dshared-glapi=disabled', '-Dgallium-d3d12-video=disabled',
               '-Dgallium-wgl-dll-name=madeira-mesa-gl', '-Dbuild-tests=false',
               '-Dzlib=disabled', '-Dzstd=disabled', '-Dexpat=disabled']
    command = [sys.executable, '-m', 'mesonbuild.mesonmain', 'setup']
    if (output / 'build.ninja').exists():
        command += ['--reconfigure']
    subprocess.run(command + [str(output), str(source), '--cross-file', str(cross)] + options,
                   check=True, env=env)
    ninja = shutil.which('ninja', path=env['PATH'])
    if not ninja:
        raise ValueError('ninja is required')
    if os.name == 'nt':
        # win_flex shares temporary filenames; do not run its generators together.
        for target in ('src/compiler/glsl/glcpp/glcpp-lex.c', 'src/compiler/glsl/glsl_lexer.cpp',
                       'src/mesa/program/lex.yy.c'):
            subprocess.run([ninja, '-C', str(output), target, '-j', '1'], check=True, env=env)
    subprocess.run([ninja, '-C', str(output), '-j', str(args.jobs)], check=True, env=env)
    for original, installed in [('libgl-gdi/opengl32.dll', DLLS[0]),
                                 ('wgl/madeira-mesa-gl.dll', DLLS[1])]:
        shutil.copy2(output / 'src/gallium/targets' / original, dist / installed)
        subprocess.run([tools['strip'], '--strip-debug', str(dist / installed)], check=True)
    subprocess.run([tools['c'], '-O2', '-static', str(HERE / 'probe.c'), '-o', str(dist / PROBE),
                    '-lopengl32', '-lgdi32', '-luser32'], check=True)
    license_dir = dist / 'licenses'
    shutil.copytree(source / 'licenses', license_dir / 'Mesa', dirs_exist_ok=True)
    shutil.copyfile(source / 'docs/license.rst', license_dir / 'Mesa-LICENSE.rst')
    shutil.copyfile(headers / 'LICENSE', license_dir / 'DirectX-Headers-LICENSE.txt')
    # The DLLs include compiler-rt/libc++ and MinGW runtime objects even though
    # no toolchain DLL is shipped. Keep their original redistribution notices.
    shutil.copyfile(args.toolchain / 'LICENSE.TXT', license_dir / 'LLVM-LICENSE.txt')
    mingw_notices = args.toolchain / 'x86_64-w64-mingw32/share/mingw32'
    for notice in mingw_notices.glob('COPYING*'):
        shutil.copyfile(notice, license_dir / notice.name)
    if not (license_dir / 'COPYING.MinGW-w64-runtime.txt').is_file():
        raise ValueError('toolchain is missing its MinGW runtime notices')
    manifest = {'schema': 1, 'recipe': recipe_key(), 'mesa': '25.0.7', 'architecture': 'x86_64',
                'sources': {name: values[1] for name, values in SOURCES.items()},
                'patches': patch_manifest(),
                'options': options, 'files': {p.relative_to(dist).as_posix(): sha(p)
                    for p in sorted(dist.rglob('*')) if p.is_file() and p.name != MANIFEST},
                'limits': 'Experimental WGL/D3D12 build. Device rendering and game compatibility require testing.'}
    (dist / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    return verify(dist)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=os.environ.get('LLVM_MINGW'))
    parser.add_argument('--work', type=Path, default=HERE / 'work')
    parser.add_argument('--dist', type=Path, default=HERE / 'dist')
    parser.add_argument('--dest', type=Path, default=ROOT / 'app/Madeira/arm64ec-windows')
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 4, 8))
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if args.stage_only:
        verify(args.dist)
    else:
        if args.toolchain is None:
            parser.error('set LLVM_MINGW or --toolchain')
        build(args)
    args.dest.mkdir(parents=True, exist_ok=True)
    for name in (*DLLS, PROBE):
        shutil.copy2(args.dist / name, args.dest / name)
    licenses = ROOT / 'app/Madeira/licenses/mesa-d3d12'
    shutil.copytree(args.dist / 'licenses', licenses, dirs_exist_ok=True)
    shutil.copy2(args.dist / MANIFEST, licenses / MANIFEST)
    print('Staged experimental x64 OpenGL/D3D12 driver and device canary', flush=True)


if __name__ == '__main__':
    main()
