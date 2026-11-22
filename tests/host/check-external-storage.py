#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise production path authorization, disk probes, and Steam registration.

Uses temporary directories and real links/permissions; never contacts Steam.
iOS security scopes, hardware hotplug, and Wine execution require device QA.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
parser = argparse.ArgumentParser()
parser.add_argument('--require-swift', action='store_true')
args = parser.parse_args()

DRIVER = r'''
import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

@main struct Checks {
    static func main() throws {
        let fm = FileManager.default
        let temporary = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try fm.createDirectory(at: temporary, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: temporary); DrivePaths.shared.replace([]) }
        let drive = temporary.appendingPathComponent("drive_c").resolvingSymlinksInPath()
        let external = temporary.appendingPathComponent("External games 100% 游戏").resolvingSymlinksInPath()
        let other = temporary.appendingPathComponent("other").resolvingSymlinksInPath()
        for root in [drive, external, other] { try fm.createDirectory(at: root, withIntermediateDirectories: true) }
        try Data("unchanged".utf8).write(to: external.appendingPathComponent("user-file"))
        try ExternalStorageProbe.check(external, write: true)
        let id = try ExternalStorageProbe.identify(external)
        precondition(try ExternalStorageProbe.identify(external) == id)
        try ExternalStorageProbe.check(external, expected: id, write: true)
        precondition(try fm.contentsOfDirectory(atPath: external.path).sorted() == [ExternalStorageProbe.marker, "user-file"].sorted())
        precondition(try Data(contentsOf: external.appendingPathComponent("user-file")) == Data("unchanged".utf8))
        print("PASS: real read/write/rename/delete probe preserves existing files and folder identity")

        let mount = DrivePaths.Mount(id: id, url: external, available: true, problem: "Disconnected")
        let relative = mount.relativeRoot + "/Game.exe"
        let link = drive.appendingPathComponent(mount.relativeRoot)
        try fm.createDirectory(at: link.deletingLastPathComponent(), withIntermediateDirectories: true)
        try fm.createSymbolicLink(atPath: link.path, withDestinationPath: external.path)
        for root in [drive, external, other] { try Data([0x4d, 0x5a]).write(to: root.appendingPathComponent("Game.exe")) }
        DrivePaths.shared.replace([mount])
        precondition(try DrivePaths.shared.resolve(relative, drive: drive).path == link.appendingPathComponent("Game.exe").path)
        precondition(DrivePaths.shared.relative(external.appendingPathComponent("Game.exe"), drive: drive) == relative)
        precondition(try DrivePaths.shared.resolve("Game.exe", drive: drive).path == drive.appendingPathComponent("Game.exe").path)
        for path in ["../other/Game.exe", "/Game.exe", "C:\\Game.exe", "a/../Game.exe", "a\u{0}/Game.exe"] {
            precondition((try? DrivePaths.shared.resolve(path, drive: drive)) == nil)
        }
        try fm.createSymbolicLink(atPath: drive.appendingPathComponent("escape").path, withDestinationPath: other.path)
        try fm.createSymbolicLink(atPath: external.appendingPathComponent("escape").path, withDestinationPath: other.path)
        precondition((try? DrivePaths.shared.resolve("escape/Game.exe", drive: drive)) == nil)
        precondition((try? DrivePaths.shared.resolve(mount.relativeRoot + "/escape/Game.exe", drive: drive)) == nil)
        var offline = mount; offline.available = false
        DrivePaths.shared.replace([offline])
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) == nil)
        precondition(DrivePaths.shared.problem(relative) == "Disconnected")
        precondition(DrivePaths.shared.steamLibraries.isEmpty)
        DrivePaths.shared.replace([mount])
        try fm.removeItem(at: link)
        try fm.createSymbolicLink(atPath: link.path, withDestinationPath: other.path)
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) == nil)
        try fm.removeItem(at: link)
        try fm.createSymbolicLink(atPath: link.path, withDestinationPath: external.path)
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) != nil)
        print("PASS: internal paths and registered mappings work; traversal, unregistered/replaced/nested links and offline mappings fail closed")

        let identityFile = external.appendingPathComponent(ExternalStorageProbe.marker)
        try Data(UUID().uuidString.utf8).write(to: identityFile)
        precondition((try? ExternalStorageProbe.check(external, expected: id, write: false)) == nil)
        try Data(id.uuidString.utf8).write(to: identityFile)
        if getuid() != 0 {
            try fm.setAttributes([.posixPermissions: 0o555], ofItemAtPath: external.path)
            precondition((try? ExternalStorageProbe.check(external, expected: id, write: true)) == nil)
            try fm.setAttributes([.posixPermissions: 0o755], ofItemAtPath: external.path)
            print("PASS: read-only folders are rejected")
        }
        try ExternalStorageProbe.check(external, expected: id, write: true)
        print("PASS: wrong folder identity is rejected; reconnecting the original restores access")

        let original = Data(#"""
        "libraryfolders"
        {
            // preserve this comment and MixedCase key
            "0" { "path" "C:\\Steam" "MixedCase" "brace } in a string" }
            "17" { "path" "C:\\Existing" "apps" { "42" "9000" } }
        } // trailing } comment
        """#.utf8)
        let libraries = [mount.relativeRoot + "/steamapps"]
        let changed = try SteamExternalLibraries.adding(libraries, to: original)
        var reader = try SteamKeyValues(changed)
        let root = try reader.read()["libraryfolders"]!
        precondition(root["17"]?["apps"]?["42"]?.string == "9000")
        precondition(root["18"]?["path"]?.string == "C:\\" + mount.relativeRoot.replacingOccurrences(of: "/", with: "\\"))
        precondition(String(decoding: changed, as: UTF8.self).contains("MixedCase"))
        precondition(try SteamExternalLibraries.adding(libraries, to: changed) == changed)
        precondition((try? SteamExternalLibraries.adding(["../steamapps"], to: original)) == nil)
        precondition((try? SteamExternalLibraries.adding(libraries, to: Data(#""libraryfolders" { "9223372036854775807" {} }"#.utf8))) == nil)
        let client = "Program Files (x86)/Steam"
        let config = drive.appendingPathComponent(client + "/steamapps/libraryfolders.vdf")
        try fm.createDirectory(at: config.deletingLastPathComponent(), withIntermediateDirectories: true)
        try original.write(to: config)
        try SteamExternalLibraries.prepare(drive: drive, clientRelative: client)
        precondition(try Data(contentsOf: config.appendingPathExtension("ideck-before-external")) == original)
        precondition(try Data(contentsOf: config) == changed)
        print("PASS: Steam registration preserves existing records, comments and backup; repeat registration is idempotent and oversized indices are rejected")
    }
}
'''

swift = shutil.which('swiftc')
if not swift:
    if args.require_swift:
        raise SystemExit('swiftc is required for external storage regression checks')
    print('SKIP: production Swift execution requires swiftc (required in CI)')
else:
    # Evaluate throwing expressions before the non-throwing assertion closure.
    driver = DRIVER.replace('precondition(try ', 'check(try ')
    driver = driver.replace('@main struct Checks {',
                            'func check(_ value: Bool) { precondition(value) }\n@main struct Checks {')
    with tempfile.TemporaryDirectory(prefix='ideck-storage-') as folder:
        path = Path(folder)
        source = path / 'Checks.swift'
        source.write_text(driver, encoding='utf-8')
        binary = path / 'checks'
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5',
                        str(APP / 'DrivePaths.swift'), str(APP / 'SteamKeyValues.swift'),
                        str(APP / 'SteamExternalLibraries.swift'), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
