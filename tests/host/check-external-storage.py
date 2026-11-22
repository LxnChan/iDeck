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


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


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
        typealias Capacity = StorageCapacity.Reading
        precondition(Capacity(filesystem: 4096, volume: 1024, important: 0).available == 4096)
        precondition(Capacity(filesystem: 4096, volume: 1024, important: 0, internalVolume: true).available == 4096)
        precondition(Capacity(filesystem: nil, volume: 4096, important: 0).available == 4096)
        precondition(Capacity(filesystem: -1, volume: 4096, important: 0).available == 4096)
        precondition(Capacity(filesystem: 0, volume: 4096, important: 8192).available == 0)
        precondition(Capacity(filesystem: 0, volume: 0, important: 0, internalVolume: true).available == 0)
        precondition(Capacity(filesystem: nil, volume: nil, important: nil).available == nil)
        precondition(Capacity(filesystem: -1, volume: -1, important: -1, internalVolume: true).available == nil)
        precondition(Capacity(filesystem: 4096, volume: 4096, important: 8192).available == 4096)
        precondition(Capacity(filesystem: 4096, volume: 4096, important: 8192, internalVolume: true).available == 8192)
        print("PASS: shared capacity ignores zero external estimates, preserves actual full/unknown volumes, and includes internal purgeable space")
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
        let linkedCapacity = StorageCapacity.read(at: link)
        precondition(linkedCapacity.filesystem != nil && linkedCapacity.filesystem! > 0)
        precondition(linkedCapacity.available != nil && linkedCapacity.available! > 0)
        precondition(StorageCapacity.read(at: other.appendingPathComponent("missing")).available == nil)
        print("PASS: capacity reads the real filesystem through a mapped folder; a missing location stays unknown")
        DrivePaths.shared.replace([mount])
        let freshLibrary = mount.relativeRoot + "/steamapps"
        let freshLogical = drive.appendingPathComponent(freshLibrary)
        let fullResolution = freshLogical.resolvingSymlinksInPath().standardizedFileURL
        print("INFO: Foundation full-path resolution follows mapping with missing leaf=\(DrivePaths.within(fullResolution, external))")
        precondition(!fm.fileExists(atPath: external.appendingPathComponent("steamapps").path))
        precondition(try DrivePaths.shared.resolve(freshLibrary, drive: drive, mustExist: false).path == freshLogical.path)
        let freshFile = freshLibrary + "/common/New game/data/first.bin"
        precondition(try DrivePaths.shared.resolve(freshFile, drive: drive, mustExist: false).path == drive.appendingPathComponent(freshFile).path)
        precondition((try? DrivePaths.shared.resolve(freshLibrary, drive: drive)) == nil)
        precondition(!fm.fileExists(atPath: external.appendingPathComponent("steamapps").path))
        precondition(try DrivePaths.shared.resolve("new/internal/file", drive: drive, mustExist: false).path == drive.appendingPathComponent("new/internal/file").path)
        print("PASS: first external download resolves missing steamapps and nested files without creating them; existing-only checks still reject them")
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
        precondition((try? DrivePaths.shared.resolve("escape/not-created/file", drive: drive, mustExist: false)) == nil)
        precondition((try? DrivePaths.shared.resolve(mount.relativeRoot + "/escape/not-created/file", drive: drive, mustExist: false)) == nil)
        try fm.createSymbolicLink(atPath: external.appendingPathComponent("broken").path, withDestinationPath: other.appendingPathComponent("missing").path)
        try fm.createSymbolicLink(atPath: external.appendingPathComponent("loop").path, withDestinationPath: external.appendingPathComponent("loop").path)
        for path in ["broken", "broken/child/file", "loop/child/file", "Game.exe/child"] {
            precondition((try? DrivePaths.shared.resolve(mount.relativeRoot + "/" + path, drive: drive, mustExist: false)) == nil)
        }
        var offline = mount; offline.available = false
        DrivePaths.shared.replace([offline])
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) == nil)
        precondition(DrivePaths.shared.problem(relative) == "Disconnected")
        precondition(DrivePaths.shared.steamLibraries.isEmpty)
        DrivePaths.shared.replace([mount])
        try fm.removeItem(at: link)
        try fm.createSymbolicLink(atPath: link.path, withDestinationPath: other.path)
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) == nil)
        precondition((try? DrivePaths.shared.resolve(freshLibrary, drive: drive, mustExist: false)) == nil)
        try fm.removeItem(at: link)
        try fm.createSymbolicLink(atPath: link.path, withDestinationPath: external.path)
        precondition((try? DrivePaths.shared.resolve(relative, drive: drive)) != nil)
        print("PASS: internal paths and registered mappings work; traversal, replaced/escaping/broken/looping links, non-directory parents and offline mappings fail closed even for missing targets")

        let privateError = NSError(domain: NSCocoaErrorDomain, code: 257, userInfo: [
            NSFilePathErrorKey: external.path, NSLocalizedDescriptionKey: "Private folder " + external.path,
            NSUnderlyingErrorKey: NSError(domain: NSPOSIXErrorDomain, code: 1)])
        precondition(DrivePaths.diagnostic(privateError) == "NSCocoaErrorDomain-257:NSPOSIXErrorDomain-1")
        precondition(DrivePaths.diagnostic(DrivePaths.Failure(message: external.path, code: "mapping-changed")) == "mapping-changed")
        print("PASS: storage diagnostics retain system error codes without logging user paths or localized descriptions")

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

        let apps = external.appendingPathComponent("steamapps")
        let common = apps.appendingPathComponent("common")
        try fm.createDirectory(at: common, withIntermediateDirectories: true)
        let regular = common.appendingPathComponent("Regular/Game.exe")
        check(try SteamInstallFiles.confined(regular, to: apps) == regular)
        precondition((try? SteamInstallFiles.confined(other.appendingPathComponent("Game.exe"), to: apps)) == nil)
        let linkedGame = common.appendingPathComponent("Linked")
        try fm.createSymbolicLink(atPath: linkedGame.path, withDestinationPath: other.path)
        precondition((try? SteamInstallFiles.confined(linkedGame.appendingPathComponent("Game.exe"), to: apps)) == nil)
        let linkedFile = common.appendingPathComponent("file-link")
        try fm.createSymbolicLink(atPath: linkedFile.path, withDestinationPath: other.appendingPathComponent("Game.exe").path)
        precondition((try? SteamInstallFiles.confined(linkedFile, to: apps)) == nil)
        precondition((try? SteamInstallFiles.delete(appID: 42, folderName: "Linked", steamApps: apps)) == nil)
        check(try Data(contentsOf: other.appendingPathComponent("Game.exe")) == Data([0x4d, 0x5a]))
        try fm.createDirectory(at: regular.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data([1]).write(to: regular)
        try Data([2]).write(to: apps.appendingPathComponent("appmanifest_42.acf"))
        try SteamInstallFiles.delete(appID: 42, folderName: "Regular", steamApps: apps)
        precondition(!fm.fileExists(atPath: regular.path) && !fm.fileExists(atPath: apps.appendingPathComponent("appmanifest_42.acf").path))
        check(try Data(contentsOf: other.appendingPathComponent("Game.exe")) == Data([0x4d, 0x5a]))
        print("PASS: shared install and uninstall paths reject linked files/directories and preserve unrelated files")

        let journalURL = apps.appendingPathComponent("resume.journal")
        try Data("ab".utf8).write(to: journalURL)
        let journal = try JournalWriter(url: journalURL)
        try journal.append(0xcd)
        try journal.close()
        try journal.close()
        precondition(JournalWriter.load(journalURL) == Set<UInt64>([0xab, 0xcd]))
        let journalLink = apps.appendingPathComponent("linked.journal")
        try fm.createSymbolicLink(atPath: journalLink.path, withDestinationPath: other.appendingPathComponent("Game.exe").path)
        precondition((try? JournalWriter(url: journalLink)) == nil)
        check(try Data(contentsOf: other.appendingPathComponent("Game.exe")) == Data([0x4d, 0x5a]))
        print("PASS: production download journal resumes a partial line, flushes, closes idempotently and rejects symlinks")

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

# Compile the production refresh methods with a controllable disk worker. This
# exercises actual queue/generation handling while iOS bookmarks stay on-device.
external_source = (APP / 'ExternalStorage.swift').read_text(encoding='utf-8')
refresh_methods = '\n'.join(block(external_source, marker).replace('private func', 'func') for marker in [
    'func checkConnectedFolders()', 'func refresh(', 'private func drainPendingCheck()',
    'private func invalidateCheckSuccess()'])
refresh_types = '\n'.join(block(external_source, marker) for marker in ['struct Status:', 'enum CheckFeedback:'])
REFRESH = r'''
import Foundation
@MainActor final class LibraryModel {
    static let drive = URL(fileURLWithPath: "/tmp")
}
@MainActor final class SteamOwnedLibrary {
    static let shared = SteamOwnedLibrary()
    func externalStorageChanged() {}
}
@MainActor final class SteamGamesModel {
    static let shared = SteamGamesModel()
    func refresh() {}
}
@MainActor final class Store {
    struct Record: Sendable {
        var id = UUID(), lastPath = "original", bookmark = Data(), enabled = true
    }
    TYPES
    var records = [Record()]
    var statuses: [UUID: Status] = [:]
    var checking = false, busy = false, pendingWriteCheck = false, pendingReportedCheck = false
    var generation: UInt64 = 0, appliedGeneration: UInt64 = 0
    var checkFeedback: CheckFeedback = .idle
    var canMutateRuntime = true, failSave = false
    let queue = DispatchQueue(label: "storage-refresh-test")
    let engine = Engine()
    func save(_ next: [Record]) -> Bool {
        if failSave { return false }
        records = next; return true
    }
    func publishPaths() {}
    METHODS
    final class Engine: @unchecked Sendable {
        struct ResultRow { var record: Record; var status: Status }
        let lock = NSLock(), gate = DispatchSemaphore(value: 0)
        var writes: [Bool] = []
        var pause = false, ready = true, moved = false
        func configure(pause: Bool = false, ready: Bool = true, moved: Bool = false) {
            lock.lock(); defer { lock.unlock() }
            self.pause = pause; self.ready = ready; self.moved = moved
        }
        var calls: [Bool] {
            lock.lock(); defer { lock.unlock() }; return writes
        }
        func check(_ records: [Record], drive: URL, write: Bool, allowRelink: Bool) -> [ResultRow] {
            lock.lock()
            writes.append(write)
            let paused = pause, available = ready, changed = moved
            pause = false
            lock.unlock()
            if paused { precondition(gate.wait(timeout: .now() + 5) == .success, "test released disk worker") }
            return records.map {
                var record = $0
                if changed { record.lastPath = "reconnected" }
                return ResultRow(record: record, status: Status(ready: record.enabled && available,
                                 message: available ? "Connected" : "Disconnected", freeBytes: available ? 4096 : nil))
            }
        }
    }
}
@MainActor func eventually(_ message: String, _ predicate: () -> Bool) async throws {
    let deadline = Date().addingTimeInterval(5)
    while !predicate(), Date() < deadline { try await Task.sleep(nanoseconds: 5_000_000) }
    precondition(predicate(), message)
}
@MainActor func succeeded(_ store: Store) -> Bool {
    if case .success = store.checkFeedback { return true }; return false
}
@MainActor func failed(_ store: Store) -> Bool {
    if case .failure = store.checkFeedback { return true }; return false
}
@main struct RefreshChecks {
    @MainActor static func main() async throws {
        let polling = Store()
        polling.engine.configure(pause: true)
        polling.refresh()
        try await eventually("poll started") { polling.engine.calls.count == 1 }
        polling.checkConnectedFolders()
        polling.refresh(write: true) // Startup/foreground request during the poll.
        precondition(polling.checkFeedback == .checking)
        polling.engine.gate.signal()
        try await eventually("manual check completed") { !polling.checking && succeeded(polling) }
        precondition(polling.engine.calls == [false, true], "mandatory checks coalesce without losing the write probe")
        print("PASS: foreground and manual checks queued during polling run a full write check and finish with success feedback")

        let busy = Store()
        busy.busy = true
        busy.refresh(write: true)
        busy.checkConnectedFolders()
        precondition(busy.engine.calls.isEmpty && busy.checkFeedback == .checking)
        busy.busy = false
        busy.drainPendingCheck()
        try await eventually("busy check completed") { succeeded(busy) }
        precondition(busy.engine.calls == [true])
        print("PASS: startup/manual requests survive an in-flight storage change")

        let superseded = Store()
        superseded.engine.configure(pause: true)
        superseded.checkConnectedFolders()
        try await eventually("manual check started") { superseded.engine.calls.count == 1 }
        // A storage-loss event or requireAvailable result supersedes the probe.
        superseded.generation += 1; superseded.appliedGeneration = superseded.generation
        superseded.engine.gate.signal()
        try await eventually("superseded check retried") { succeeded(superseded) }
        precondition(superseded.engine.calls == [true, true])
        superseded.engine.configure(ready: false)
        superseded.refresh()
        try await eventually("disconnect poll completed") { !superseded.checking }
        precondition(superseded.checkFeedback == .idle, "disconnect clears stale success")
        superseded.checkConnectedFolders()
        try await eventually("failed check completed") { failed(superseded) }
        print("PASS: superseded results retry without leaving a spinner or false success; unavailable folders show failure")

        let moved = Store()
        moved.failSave = true
        moved.engine.configure(moved: true)
        moved.checkConnectedFolders()
        try await eventually("save failure completed") { failed(moved) }
        precondition(moved.statuses.values.allSatisfy { !$0.ready })
        let empty = Store(); empty.records = []; empty.checkConnectedFolders()
        precondition(failed(empty))
        let disabled = Store(); disabled.records[0].enabled = false; disabled.checkConnectedFolders()
        try await eventually("disabled check completed") { failed(disabled) }
        print("PASS: save failures, missing records, and safely disconnected folders cannot report a successful check")
    }
}
'''.replace('TYPES', refresh_types).replace('METHODS', refresh_methods)

ui_source = (APP / 'ExternalStorageUI.swift').read_text(encoding='utf-8')
assert 'storage.checkConnectedFolders()' in ui_source
assert 'case .checking: ProgressView(' in ui_source
assert 'Label("Check successful", systemImage: "checkmark.circle.fill").foregroundStyle(.green)' in ui_source
assert 'case .failure(let message)' in ui_source
assert 'refresh(write: true)' in block(external_source, 'func start()')
assert 'ExternalStorage.shared.start()' in (APP / 'MadeiraApp.swift').read_text(encoding='utf-8')
print('PASS: startup/foreground request write checks; manual checks display progress, green success, or failure')

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
        # Compile the production journal without its Steam/network dependencies.
        downloader = (APP / 'SwiftSteam/Content/DepotDownloader.swift').read_text(encoding='utf-8')
        journal = path / 'JournalWriter.swift'
        journal.write_text('import Foundation\n#if canImport(Darwin)\nimport Darwin\n#else\nimport Glibc\n#endif\n' +
                           downloader[downloader.index('final class JournalWriter {'):], encoding='utf-8')
        binary = path / 'checks'
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5',
                        str(APP / 'DrivePaths.swift'), str(APP / 'SteamKeyValues.swift'),
                        str(APP / 'SteamInstall.swift'), str(APP / 'SteamExternalLibraries.swift'),
                        str(APP / 'SwiftSteam/Core/SteamError.swift'), str(journal), str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
        refresh = path / 'Refresh.swift'
        refresh.write_text(REFRESH, encoding='utf-8')
        refresh_binary = path / 'refresh-checks'
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(refresh),
                        '-o', str(refresh_binary)], check=True)
        subprocess.run([str(refresh_binary)], check=True, timeout=30)
