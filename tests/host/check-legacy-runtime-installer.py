#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Run the production x86 helper using an explicitly supplied official package.

No Microsoft runtime is downloaded, committed or uploaded by this test.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, required=True)
    args = parser.parse_args()
    if os.name != 'nt': raise SystemExit('This execution test requires Windows')
    root = Path(__file__).resolve().parents[2]
    pins = (root / 'app/Madeira/LegacyRuntimeCore.swift').read_text(encoding='utf-8')
    expected = re.search(r'dllSHA256 = "([a-f0-9]+)"', pins)[1]
    with tempfile.TemporaryDirectory(prefix='ideck-runtime-') as scratch:
        work = Path(scratch); dll = work / 'mfc42.dll'; report = work / 'result.txt'
        def run(*values, code=0):
            result = subprocess.run([str(args.helper), *map(str, values)], capture_output=True)
            assert result.returncode == code, (result.returncode, result.stderr)
        run(args.package, dll, report)
        assert hashlib.sha256(dll.read_bytes()).hexdigest() == expected
        run(args.package, dll, report)
        dll.write_bytes(b'preserve existing runtime')
        run(args.package, dll, report, code=2)
        assert dll.read_bytes() == b'preserve existing runtime'
        dll.unlink()
        bad = work / 'changed-package.exe'
        changed = bytearray(args.package.read_bytes()); changed[-10] ^= 1; bad.write_bytes(changed)
        run(bad, dll, report, code=1)
        assert not dll.exists()
        source = work / 'argprobe.c'
        source.write_text('#include <stdio.h>\n#include <wchar.h>\nint wmain(int argc,wchar_t **argv){FILE *f=_wfopen(argv[1],L"wb");if(!f)return 90;for(int i=2;i<argc;++i)fwrite(argv[i],sizeof(wchar_t),wcslen(argv[i])+1,f);fclose(f);return 17;}')
        child = work / 'argprobe.exe'
        subprocess.run([str(args.compiler), '-static', '-municode', str(source), '-o', str(child)], check=True)
        output = work / 'arguments.bin'
        values = ['', 'a b', 'q"r', 'tail\\', '100%^&', '\u4e2d\u6587']
        run(args.package, dll, report, '--launch', child, output, *values, code=17)
        assert output.read_bytes().decode('utf-16le').split('\0')[:-1] == values
        output.unlink(); dll.unlink()
        run(bad, dll, report, '--launch', child, output, *values, code=1)
        assert not output.exists() and not dll.exists()
    print('PASS: official nested cabinets, pinned DLL hash, idempotence, conflict retention, tampering, child argv/exit status and failure blocks launch')


if __name__ == '__main__': main()
