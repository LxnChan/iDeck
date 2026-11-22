#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Prepare a private, unmodified x86 MFC42 copy from a user-supplied runtime.

This does not download or redistribute Microsoft binaries. --requires can
verify an application's imported MFC42 ordinals/names before copying anything.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct


class PE32:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.data[:2] != b'MZ':
            raise ValueError('not a PE image: ' + str(path))
        pe = self.u32(0x3c)
        if (self.data[pe:pe + 4] != b'PE\0\0' or self.u16(pe + 4) != 0x14c
                or self.u16(pe + 24) != 0x10b):
            raise ValueError('32-bit x86 PE required: ' + str(path))
        self.optional = pe + 24
        sections = self.optional + self.u16(pe + 20)
        self.sections = [struct.unpack_from('<IIII', self.data, sections + 40 * i + 8)
                         for i in range(self.u16(pe + 6))]

    def u16(self, offset):
        return struct.unpack_from('<H', self.data, offset)[0]

    def u32(self, offset):
        return struct.unpack_from('<I', self.data, offset)[0]

    def offset(self, rva):
        for virtual_size, virtual, raw_size, raw in self.sections:
            if virtual <= rva < virtual + min(virtual_size or raw_size, raw_size):
                return raw + rva - virtual
        raise ValueError('PE RVA has no file data: ' + hex(rva))

    def string(self, rva):
        offset = self.offset(rva)
        return self.data[offset:self.data.index(0, offset)].decode('ascii')

    def imports(self, library):
        rva = self.u32(self.optional + 104)
        if not rva:
            return set()
        offset, result = self.offset(rva), set()
        while self.u32(offset + 12):
            if self.string(self.u32(offset + 12)).lower() == library.lower():
                thunk = self.offset(self.u32(offset) or self.u32(offset + 16))
                while self.u32(thunk):
                    value = self.u32(thunk)
                    result.add(value & 0xffff if value & 0x80000000 else self.string(value + 2))
                    thunk += 4
            offset += 20
        return result

    def exports(self):
        offset = self.offset(self.u32(self.optional + 96))
        base, count = self.u32(offset + 16), self.u32(offset + 20)
        functions = self.offset(self.u32(offset + 28))
        result = {base + i for i in range(count) if self.u32(functions + 4 * i)}
        names = self.offset(self.u32(offset + 32))
        result.update(self.string(self.u32(names + 4 * i)) for i in range(self.u32(offset + 24)))
        return result

    def export_module(self):
        offset = self.offset(self.u32(self.optional + 96))
        return self.string(self.u32(offset + 12)).lower()


def prepare(source, destination, requirements=()):
    runtime = PE32(source)
    exports = runtime.exports()
    # Most MFC42 functions are exported by ordinal only; checking undecorated
    # Afx names would reject Microsoft's actual runtime.
    if runtime.export_module() != 'mfc42.dll':
        raise ValueError('source is not an MFC42 runtime')
    for path in requirements:
        imports = PE32(path).imports('mfc42.dll')
        missing = imports - exports
        if missing:
            raise ValueError(str(path) + ': missing MFC42 exports ' + ', '.join(map(str, sorted(missing, key=str))))
        print(f'{path.name}: verified {len(imports)} MFC42 imports')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / 'mfc42.dll'
    if target.exists() and target.read_bytes() != runtime.data:
        raise ValueError('refusing to replace a different runtime: ' + str(target))
    if not target.exists():
        shutil.copy2(source, target)
    print('Prepared unmodified x86 MFC42:', target)
    print('SHA256:', hashlib.sha256(runtime.data).hexdigest())
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='User-supplied x86 mfc42.dll, e.g. Windows/SysWOW64/mfc42.dll')
    parser.add_argument('--dest', type=Path, required=True,
                        help='Private staging directory, game directory, or prefix windows/syswow64')
    parser.add_argument('--requires', type=Path, nargs='*', default=[])
    args = parser.parse_args()
    prepare(args.source, args.dest, args.requires)
