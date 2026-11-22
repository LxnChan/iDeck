#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Execute the production Swift PE scanner on generated, non-proprietary PEs."""
import argparse
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def pe(bits=32, imports=False, delay=False, va=False, exports=False):
    b = bytearray(4096)
    def w(p, x): struct.pack_into('<H', b, p, x)
    def d(p, x): struct.pack_into('<I', b, p, x)
    b[:2] = b'MZ'; d(60, 128); b[128:132] = b'PE\0\0'
    w(132, 0x14c if bits == 32 else 0x8664); w(134, 1)
    opt = 152; length = 224 if bits == 32 else 240
    w(148, length); w(opt, 0x10b if bits == 32 else 0x20b)
    d(opt + 28, 0x400000)
    directories = opt + (96 if bits == 32 else 112)
    d(directories - 4, 16)
    sec = opt + length
    b[sec:sec+8] = b'.rdata\0\0'; d(sec+8, 0xe00); d(sec+12, 0x1000)
    d(sec+16, 0xe00); d(sec+20, 0x200)
    def text(p, s): b[p:p+len(s)+1] = s.encode() + b'\0'
    if imports:
        add = 0x400000 if va else 0
        if delay:
            d(directories + 13*8, 0x1200); d(0x400, 0 if va else 1)
            d(0x404, 0x1080 + add); d(0x410, 0x1100 + add)
        else:
            d(directories + 8, 0x1000); d(0x200, 0x1100)
            d(0x20c, 0x1080); d(0x210, 0x1100)
        text(0x280, 'MFC42.DLL')
        if bits == 32:
            d(0x300, 0x80000007); d(0x304, 0x1190 + add)
        else:
            struct.pack_into('<QQ', b, 0x300, 0x8000000000000007, 0x1190)
        text(0x392, 'HelloMfc')
    if exports:
        d(directories, 0x1000); d(0x20c, 0x10a0); text(0x2a0, 'mfc42.dll')
        d(0x210, 1); d(0x214, 128); d(0x218, 1)
        d(0x21c, 0x1300); d(0x220, 0x1220); d(0x224, 0x1240)
        for i in range(128): d(0x500 + i*4, 0x1600)
        d(0x420, 0x10c0); w(0x440, 6); text(0x2c0, 'HelloMfc')
    return bytes(b)


DRIVER = r'''
import Foundation
let args = CommandLine.arguments
do {
    switch args[1] {
    case "inspect":
        let pe = try LegacyRuntimePE(url: URL(fileURLWithPath: args[2]))
        let symbols = try pe.mfc42Imports().sorted()
        print("\(pe.bits):" + symbols.joined(separator: ","))
    case "scan":
        let need = try LegacyRuntimeDependency.scan(executable: URL(fileURLWithPath: args[2]), drive: URL(fileURLWithPath: args[3]), prefix: URL(fileURLWithPath: args[4]))
        print(need.map { $0.symbols.sorted().joined(separator: ",") } ?? "satisfied")
    case "fuzz":
        let bytes = try Data(contentsOf: URL(fileURLWithPath: args[2]))
        for length in 0...bytes.count {
            if let pe = try? LegacyRuntimePE(Data(bytes.prefix(length))) {
                _ = try? pe.mfc42Imports(); _ = try? pe.mfc42Exports()
            }
        }
        print("bounded")
    case "policy":
        for value in ["http://download.microsoft.com/a", "https://evil.example/a", "https://download.microsoft.com.evil.example/a", "https://user@download.microsoft.com/a", "https://download.microsoft.com:8443/a"] {
            precondition(!LegacyRuntimePin.allowed(URL(string: value)))
        }
        precondition(LegacyRuntimePin.allowed(LegacyRuntimePin.url))
        let wrapped = LegacyRuntimePin.wrapped(executable: "C:\\Game\\Player.exe", arguments: "\"a b\" 100% ^&", bits: 32)
        precondition(wrapped.exe.contains("syswow64"))
        precondition(wrapped.args.hasSuffix("--launch \"C:\\Game\\Player.exe\" \"a b\" 100% ^&"))
        precondition(!wrapped.args.contains("cmd /c"))
        precondition(LegacyRuntimePin.workingDirectory(executable: "C:\\Game\\Bin\\Player.exe", chosen: nil) == "C:\\Game\\Bin")
        precondition(LegacyRuntimePin.workingDirectory(executable: "C:\\Player.exe", chosen: nil) == "C:\\")
        precondition(LegacyRuntimePin.workingDirectory(executable: "C:\\Game\\Player.exe", chosen: "C:\\Custom") == "C:\\Custom")
        precondition(LegacyRuntimePin.workingDirectory(executable: "explorer.exe", chosen: nil) == nil)
        print("policy")
    default: fatalError("unexpected mode")
    }
} catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(2)
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-swift', action='store_true')
    args = parser.parse_args()
    swift = shutil.which('swiftc')
    if not swift:
        if args.require_swift: raise SystemExit('swiftc is required')
        print('SKIP: production Swift scanner execution requires swiftc')
        return
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); main_file = root / 'main.swift'; main_file.write_text(DRIVER)
        probe = root / 'runtime-probe'
        subprocess.run([swift, str(ROOT / 'app/Madeira/LegacyRuntimeCore.swift'), str(main_file), '-o', str(probe)], check=True)
        def run(*args, expected=None, failure=False):
            result = subprocess.run([str(probe), *map(str, args)], capture_output=True, text=True)
            if failure: assert result.returncode == 2, result
            else:
                assert result.returncode == 0, result.stderr
                if expected is not None: assert result.stdout.strip() == expected, result.stdout
        for bits, delay, va in [(32, False, False), (32, True, False), (32, True, True), (64, False, False)]:
            file = root / f'{bits}-{delay}-{va}.dll'; file.write_bytes(pe(bits, True, delay, va))
            run('inspect', file, expected=f'{bits}:#7,HelloMfc')
        prefix = root / 'wine'; drive = prefix / 'drive_c'
        binary = drive / 'Game/Bin/Player.exe'; plugin = drive / 'Game/Managers/UI.dll'
        binary.parent.mkdir(parents=True); plugin.parent.mkdir(parents=True)
        binary.write_bytes(pe()); plugin.write_bytes(pe(imports=True))
        run('scan', binary, drive, prefix, expected='#7,HelloMfc')
        # A second, unrelated program takes exactly the same path.
        other = drive / 'Other/Start.exe'; other.parent.mkdir(); other.write_bytes(pe(imports=True, delay=True))
        run('scan', other, drive, prefix, expected='#7,HelloMfc')
        # x64 importers must not trigger an x86 MFC installation.
        plugin.write_bytes(pe(64, imports=True))
        run('scan', binary, drive, prefix, expected='satisfied')
        plugin.write_bytes(pe(imports=True))
        runtime = drive / 'windows/syswow64/MFC42.DLL'; runtime.parent.mkdir(parents=True)
        runtime.write_bytes(pe(exports=True))
        run('scan', binary, drive, prefix, expected='satisfied')
        run('scan', other, drive, prefix, expected='satisfied')
        runtime.write_bytes(pe(64, exports=True))
        run('scan', binary, drive, prefix, failure=True)
        runtime.unlink()
        # A different/broken application-local DLL must remain a visible conflict.
        (binary.parent / 'mfc42.dll').write_bytes(b'broken existing runtime')
        run('scan', binary, drive, prefix, failure=True)
        run('scan', root / 'outside.exe', drive, prefix, expected='satisfied')
        malformed = root / 'truncated.dll'; malformed.write_bytes(pe(imports=True))
        run('fuzz', malformed, expected='bounded')
        run('policy', expected='policy')
    print('PASS: normal/delay/VA/ordinal imports, plugin discovery, two applications, x86/x64 separation, existing runtime/conflicts, truncation and download/launch policy')


if __name__ == '__main__': main()
