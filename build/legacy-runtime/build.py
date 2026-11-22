#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Build the runtime extraction helper; never fetch Microsoft binaries in CI."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def build(toolchain, bundle):
    suffix = '.exe' if os.name == 'nt' else ''
    for target, farm in [('i686', 'i386-windows'), ('arm64ec', 'arm64ec-windows')]:
        compiler = toolchain / 'bin' / (target + '-w64-mingw32-clang' + suffix)
        destination = bundle / farm / 'madeira-runtime-install.exe'
        destination.parent.mkdir(parents=True, exist_ok=True)
        resource = destination.with_suffix('.res')
        windres = toolchain / 'bin' / (target + '-w64-mingw32-windres' + suffix)
        subprocess.run([str(windres), '-I', str(ROOT / 'build/legacy-runtime'),
                        str(ROOT / 'build/legacy-runtime/install.rc'), '-O', 'res', '-o', str(resource)], check=True)
        subprocess.run([str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-static', '-municode', str(ROOT / 'build/legacy-runtime/install.c'),
                        str(resource), '-lcabinet', '-lbcrypt', '-o', str(destination)], check=True)
        resource.unlink()
        print('Built ' + str(destination))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, default=os.environ.get('LLVM_MINGW'))
    parser.add_argument('--bundle', type=Path, default=ROOT / 'app/Madeira')
    args = parser.parse_args()
    if args.toolchain is None:
        parser.error('set LLVM_MINGW or --toolchain')
    build(Path(args.toolchain), args.bundle)
