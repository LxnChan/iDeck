#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Run production download location, recovery and chunk cancellation on macOS.

Temporary files and a local HTTP server only. Content decoding is a passthrough
stand-in here; existing Steam library checks cover the real decrypt/CRC pipeline.
"""
import argparse
import http.server
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
parser = argparse.ArgumentParser()
parser.add_argument('--require-swift', action='store_true')
args = parser.parse_args()
swift = shutil.which('swiftc')

downloader = (APP / 'SwiftSteam/Content/DepotDownloader.swift').read_text(encoding='utf-8')
owned = (APP / 'SteamOwnedLibrary.swift').read_text(encoding='utf-8')
external = (APP / 'ExternalStorage.swift').read_text(encoding='utf-8')


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


sheet = block((APP / 'SteamGames.swift').read_text(encoding='utf-8'), 'struct SteamGameSheet: View')
assert '@State private var selectedLibrary: String?' in sheet
assert 'steam.install(appID, library: library)' in sheet
assert 'storage.downloadLibrary =' not in sheet
assert 'steam.fixedInstallLibrary(appID) == nil' in sheet
assert '.disabled(storage.statuses[record.id]?.ready != true)' in sheet
assert 'Storage settings and global default' not in sheet
assert 'Manage external folders and the global download default in Settings' in sheet
print('PASS: install page passes a local selection without writing the global default and locks unfinished installs')
status = block((APP / 'SteamGames.swift').read_text(encoding='utf-8'), 'struct SteamDownloadStatus: View')
assert 'if download.isChecking' in status and '.foregroundStyle(.yellow)' in status
assert 'exclamationmark.triangle.fill' in status
assert sheet.count('|| download.isChecking)') == 2
assert '.disabled(!steam.signedIn || download.isChecking)' in (APP / 'SteamGames.swift').read_text(encoding='utf-8')
assert 'item.isChecking = true' in owned and 'downloads[appID]?.isChecking = false' in owned
assert 'guard recoveryTasks[appID] == nil else' in block(owned, 'func install(_ appID:')
print('PASS: recovery state disables resume and retry across installs and updates and shows a yellow verification notice')
background = (APP / 'SteamDownloadBackground.swift').read_text(encoding='utf-8')
assert 'as? Bool ?? true' in background and 'didSet {' in background
assert 'UserDefaults.standard.set(keepScreenAwake' in background
idle = block(background, 'private func updateIdleTimer()')
assert 'applicationState == .active' in idle
assert 'renderingActive || (downloading && keepScreenAwake)' in idle
assert 'downloading = true' in block(background, 'func downloadStarted(')
assert 'downloading = false' in block(background, 'func downloadEnded(')
content = (APP / 'ContentView.swift').read_text(encoding='utf-8')
assert 'renderingActive = !isHidden' in content and 'isIdleTimerDisabled = true' not in content
assert 'Toggle("Keep screen awake while downloading", isOn: $downloads.keepScreenAwake)' in (APP / 'Onboarding.swift').read_text(encoding='utf-8')
print('PASS: foreground download hold is persistent, opt-out, and composed with the rendering hold')
if not swift:
    if args.require_swift:
        raise SystemExit('swiftc is required for download recovery checks')
    print('SKIP: download recovery execution requires macOS swiftc (required in CI)')
    raise SystemExit(0)

# Run the actual persisted preference and idle policy with an in-memory UIKit
# stand-in. Drive both holds to catch one operation releasing another's hold.
idle_source = background[background.index('@MainActor final class SteamDownloadBackground:'):background.index('    /// On iOS 26 and later,')]
idle_driver = r'''
import Foundation
import Combine
@MainActor final class UIApplication {
    enum State { case active, background }
    static let shared = UIApplication()
    var applicationState = State.active
    var isIdleTimerDisabled = false
}
'''
idle_driver += idle_source + r'''
    func simulateDownload(_ active: Bool) { downloading = active; updateIdleTimer() }
    func applicationChanged() { updateIdleTimer() }
}
@main struct IdleCheck {
    @MainActor static func main() {
        let key = "keepScreenAwakeWhileDownloading", defaults = UserDefaults.standard
        let previous = defaults.object(forKey: key)
        defaults.removeObject(forKey: key)
        defer { defaults.set(previous, forKey: key) }
        let policy = SteamDownloadBackground()
        let app = UIApplication.shared
        precondition(policy.keepScreenAwake)
        policy.simulateDownload(true)
        precondition(app.isIdleTimerDisabled)
        policy.keepScreenAwake = false
        precondition(!app.isIdleTimerDisabled)
        precondition(!SteamDownloadBackground().keepScreenAwake)
        policy.renderingActive = true
        precondition(app.isIdleTimerDisabled)
        policy.simulateDownload(false)
        precondition(app.isIdleTimerDisabled)
        policy.renderingActive = false
        precondition(!app.isIdleTimerDisabled)
        policy.keepScreenAwake = true
        policy.simulateDownload(true)
        app.applicationState = .background
        policy.applicationChanged()
        precondition(!app.isIdleTimerDisabled)
        app.applicationState = .active
        policy.applicationChanged()
        precondition(app.isIdleTimerDisabled)
        policy.simulateDownload(false)
        precondition(!app.isIdleTimerDisabled)
    }
}
'''
with tempfile.TemporaryDirectory() as idle_tmp:
    source = Path(idle_tmp) / 'IdleCheck.swift'
    binary = Path(idle_tmp) / 'idle-check'
    source.write_text(idle_driver, encoding='utf-8')
    subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
print('PASS: production idle policy handles preference persistence, live toggles, overlapping holds, backgrounding, and completion')


# Keep the real preparation, journal, networking, hashing and write logic. The
# enclosing app's authentication/session models are stand-ins.
pieces = [block(downloader, marker).replace('private nonisolated static func', 'nonisolated static func') for marker in [
    'struct WorkItem:', 'struct Prepared:', 'private nonisolated static func prepare(',
    'private nonisolated static func checkSpace(',
    'private nonisolated static func sizeFile(', 'private nonisolated static func chunkAlreadyPresent(',
    'private nonisolated static func fetchChunk(', 'nonisolated static func failureReason(', 'struct HTTPFailure:',
    'private nonisolated static func write(', 'private nonisolated static func download(']]
STUBS = r'''
import Foundation
import CryptoKit
import Darwin
func digest(_ data: Data) -> Data { Data(Insecure.SHA1.hash(data: data)) }
let CC_SHA1_DIGEST_LENGTH = 20
typealias CC_LONG = UInt32
@discardableResult func CC_SHA1(_ bytes: UnsafeRawPointer, _ count: CC_LONG,
                               _ output: UnsafeMutablePointer<UInt8>) -> UnsafeMutablePointer<UInt8> {
    let hash = digest(Data(bytes: bytes, count: Int(count)))
    hash.copyBytes(to: output, count: 20)
    return output
}
enum SteamLog { static func trace(_ value: String) {}; static func event(_ value: String) {} }
enum ContentDecryptor {
    static let maximumChunkBytes = 32 << 20
    static func processChunk(encryptedData: Data, depotKey: Data, expectedCRC: UInt32, expectedSize: Int) throws -> Data { encryptedData }
}
struct DepotManifest {
    struct ChunkEntry {
        var sha: Data; var crc: UInt32 = 0; var offset: UInt64
        var compressedSize: UInt32; var uncompressedSize: UInt32
        var shaHex: String { sha.map { String(format: "%02x", $0) }.joined() }
    }
    struct FileEntry {
        var filename: String; var size: UInt64; var flags: UInt32 = 0; var chunks: [ChunkEntry]
        var isDirectory: Bool { flags & 0x40 != 0 }
    }
    var files: [FileEntry]
}
HEALTH_SOURCE
enum Downloader {
    struct DepotPlan {
        var depotID: UInt32 = 1; var manifestGID: UInt64 = 2; var key = Data()
        var manifest: DepotManifest; var hosts: [String]; var auth: [String: String] = [:]
        var health = ContentHostHealth()
    }
    static var http: URLSession { URLSession(configuration: .ephemeral) }
'''
STUBS = STUBS.replace('HEALTH_SOURCE', block(downloader, 'final class ContentHostHealth:'))
DRIVER = r'''
func check(_ value: Bool, _ message: String) { precondition(value, message) }
actor Storage {
    var calls = 0
    func validate() throws {
        calls += 1
        if calls > 1 { throw DrivePaths.Failure(message: "Disconnected") }
    }
}
@MainActor func checkLocations(_ mount: DrivePaths.Mount, library: String) {
    let storage = ExternalStorage.shared
    defer {
        storage.preferences.removePersistentDomain(forName: storage.suite)
        SteamGamesModel.shared.games = []
    }
    var connected = mount; connected.available = true
    DrivePaths.shared.replace([connected])
    let internalLibrary = SteamInstallPaths.libraryRelative
    storage.downloadLibrary = internalLibrary
    let first = Owner()
    check(first.installLibrary(100, selecting: library) == library, "preview uses the per-download choice")
    check(storage.pendingLibrary(100) == nil && storage.downloadLibrary == internalLibrary, "preview has no persistent side effects")
    first.install(100, library: library)
    check(first.queue == [100] && storage.pendingLibrary(100) == library, "enqueue pins the selected external target")
    check(first.installSteamApps(100).path == Owner.drive.appendingPathComponent(library).path, "download files use the per-game destination")
    check(storage.pendingInstalls[100] == library && storage.downloadLibrary == internalLibrary, "external recovery registration leaves the global default unchanged")
    first.install(101, library: internalLibrary)
    check(first.queue == [100, 101] && storage.pendingLibrary(101) == internalLibrary, "queued games keep independent locations")

    // Reload the real preferences and recreate the download owner as after a restart.
    storage.preferences = UserDefaults(suiteName: storage.suite)!
    let restarted = Owner()
    storage.downloadLibrary = library
    let usingDefault = Owner(); usingDefault.install(107)
    check(usingDefault.queue == [107] && storage.pendingLibrary(107) == library, "a new download with no override uses the global default")
    check(restarted.installLibrary(101) == internalLibrary, "changing the default cannot redirect a pending internal download")
    storage.downloadLibrary = internalLibrary
    check(restarted.installLibrary(100) == library, "external target survives owner and preference reloads")
    restarted.install(100, library: internalLibrary)
    check(restarted.error != nil && restarted.queue.isEmpty && storage.pendingLibrary(100) == library, "explicit retargeting of unfinished data is rejected")
    restarted.install(100)
    check(restarted.queue == [100] && restarted.installLibrary(100) == library, "Resume uses the persisted target")

    SteamGamesModel.shared.games = [.init(id: 102, library: internalLibrary)]
    let update = Owner()
    check(update.installLibrary(102, selecting: library) == internalLibrary, "installed location wins over a preview choice")
    update.install(102, library: library)
    check(update.error != nil && update.queue.isEmpty && storage.pendingLibrary(102) == nil, "updates cannot be redirected")
    update.install(102)
    check(update.queue == [102] && storage.pendingLibrary(102) == internalLibrary, "updates pin the installed location")

    let deferred = Owner(); deferred.inSession = true
    deferred.install(103, library: library)
    check(deferred.resumeAfterSession.contains(103) && storage.pendingLibrary(103) == library, "session-deferred installs pin before waiting")
    DrivePaths.shared.replace([mount])
    let offline = Owner()
    offline.install(104, library: library)
    check(offline.queue.isEmpty && offline.error != nil && storage.pendingLibrary(104) == nil, "offline selections fail without fallback or a new pin")
    storage.downloadLibrary = library
    offline.install(105)
    check(offline.queue.isEmpty && storage.pendingLibrary(105) == nil, "an offline default also never falls back")
    offline.install(106, library: "../outside")
    check(offline.queue.isEmpty && storage.pendingLibrary(106) == nil, "unmanaged destinations are refused")
    storage.forgetLibrary(100)
    check(storage.pendingLibrary(100) == nil && storage.pendingInstalls[100] == nil, "removing managed partial data unlocks the destination")
    check(Owner().installLibrary(100, selecting: internalLibrary) == internalLibrary, "a cleared install can choose a different destination")
    print("PASS: per-download locations preserve the global default, persist independent pins, protect updates/resumes and reject offline targets")
}
func checkDurations() {
    check(SteamDownloadProgress.duration(93780) == "1 day 2 hours 3 mins", "days, hours and minutes")
    check(SteamDownloadProgress.duration(172800) == "2 days", "whole days")
    check(SteamDownloadProgress.duration(3600) == "1 hour", "whole hour")
    check(SteamDownloadProgress.duration(60) == "1 min", "exact minute")
    check(SteamDownloadProgress.duration(61) == "2 mins", "round remaining minutes up")
    check(SteamDownloadProgress.duration(20) == "less than 1 min", "sub-minute estimate")
    for seconds in [0, -1, Double.nan, Double.infinity, 1e12] {
        check(SteamDownloadProgress.duration(seconds) == nil, "invalid duration is hidden")
    }
    var progress = SteamDownloadProgress(totalBytes: 937800, bytesPerSecond: 10)
    check(progress.remainingTime == "1 day 2 hours 3 mins", "ETA uses remaining bytes and speed")
    progress.doneBytes = progress.totalBytes
    check(progress.remainingTime == nil, "completed download has no ETA")
    progress.doneBytes = 0
    for speed in [0, -1, Double.nan, Double.infinity] {
        progress.bytesPerSecond = speed
        check(progress.remainingTime == nil, "invalid speed has no ETA")
    }
    print("PASS: production ETA uses readable days/hours/minutes, rounds minutes, and handles completed or invalid estimates")
}
func checkSpacePreparation(apps: URL) throws {
    let fm = FileManager.default
    let install = apps.appendingPathComponent("common/Sparse")
    let journals = apps.appendingPathComponent("downloading/99")
    try fm.createDirectory(at: install, withIntermediateDirectories: true)
    try fm.createDirectory(at: journals, withIntermediateDirectories: true)
    let size: UInt64 = 4 << 20
    let bytes = Data(repeating: 0x61, count: Int(size))
    let chunk = DepotManifest.ChunkEntry(sha: digest(bytes), offset: 0, compressedSize: 100, uncompressedSize: UInt32(size))
    let plan = Downloader.DepotPlan(manifest: .init(files: [.init(filename: "sparse.bin", size: size, chunks: [chunk])]), hosts: [])
    typealias Capacity = StorageCapacity.Reading
    for attempt in 1...2 {
        let prepared = try Downloader.prepare(plans: [plan], steamApps: apps, installURL: install, journalDir: journals)
        let needed = prepared.remainingUncompressed
        check(needed > size / 2 && prepared.pending[0].count == 1, "first try and retry both count sparse, unwritten blocks")
        try Downloader.checkSpace(needed, capacity: Capacity(filesystem: Int64(size), volume: nil, important: 0))
        for free in [Int64(0), Int64(needed - 1)] {
            do {
                try Downloader.checkSpace(needed, capacity: Capacity(filesystem: free, volume: nil, important: 0))
                preconditionFailure("attempt \(attempt) must reject insufficient space")
            } catch SteamError.insufficientDiskSpace(let required, let available) {
                check(required == needed && available == UInt64(free), "accurate insufficient-space details")
            }
        }
        do {
            try Downloader.checkSpace(needed, capacity: Capacity(filesystem: nil, volume: nil, important: nil))
            preconditionFailure("unknown capacity cannot silently allow download")
        } catch SteamError.chunkDownloadFailed {}
    }
    try bytes.write(to: install.appendingPathComponent("sparse.bin"))
    let allocated = try Downloader.prepare(plans: [plan], steamApps: apps, installURL: install, journalDir: journals)
    check(allocated.remainingUncompressed == 0, "already allocated content requires no additional growth")
    try Downloader.checkSpace(allocated.remainingUncompressed, capacity: Capacity(filesystem: 0, volume: nil, important: nil))
    print("PASS: first install and sparse-file retry enforce the same real capacity check; allocated content can be reused on a full volume")
}
@main struct Checks {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let host = CommandLine.arguments[2]
        checkDurations()
        let mount = DrivePaths.Mount(id: UUID(), url: root, available: false, problem: "Disconnected")
        let library = mount.relativeRoot + "/steamapps"
        checkLocations(mount, library: library)
        DrivePaths.shared.replace([mount])
        ExternalStorage.shared.pinLibrary(library, appID: 42)
        ExternalStorage.shared.pinLibrary(library, appID: 43)
        defer { ExternalStorage.shared.preferences.removePersistentDomain(forName: ExternalStorage.shared.suite) }
        let owner = Owner()
        owner.active = (42, Task { do { try await Task.sleep(nanoseconds: 10_000_000_000) } catch {} })
        owner.queue = [43]
        owner.resumeAfterSession = [42, 43]; owner.resumeAfterBackgroundIDs = [42, 43]
        owner.downloads = [42: .init(state: .active), 43: .init(state: .queued)]
        owner.externalStorageChanged()
        check(owner.active!.task.isCancelled && owner.queue.isEmpty, "storage loss cancels active and dequeues affected downloads")
        check(owner.error != nil && owner.storageInterruptions.count == 2, "disconnect reason and prompt survive cancellation")
        check(owner.resumeAfterSession.isEmpty && owner.resumeAfterBackgroundIDs.isEmpty, "offline downloads never auto-resume")
        await owner.active?.task.value
        owner.active = nil
        var reconnected = mount; reconnected.available = true
        DrivePaths.shared.replace([reconnected])
        owner.externalStorageChanged(); owner.externalStorageChanged()
        check(owner.checks == 1 && owner.storageInterruptions.count == 2, "reconnect starts one audit without losing the stop reason")
        print("PASS: production storage-loss policy cancels, prompts, removes automatic resumes and schedules reconnect checking")
        let apps = root.appendingPathComponent("steamapps")
        let install = apps.appendingPathComponent("common/Fixture")
        let journals = apps.appendingPathComponent("downloading/42")
        try fm.createDirectory(at: install, withIntermediateDirectories: true)
        try fm.createDirectory(at: journals, withIntermediateDirectories: true)
        try checkSpacePreparation(apps: apps)
        let file = install.appendingPathComponent("data.bin")
        let data = Data("abcdefghi".utf8)
        let chunks = stride(from: 0, to: 9, by: 3).map { offset in
            DepotManifest.ChunkEntry(sha: digest(data.subdata(in: offset..<(offset + 3))), offset: UInt64(offset), compressedSize: 3, uncompressedSize: 3)
        }
        let plan = Downloader.DepotPlan(manifest: .init(files: [.init(filename: "data.bin", size: 9, chunks: chunks)]), hosts: [host + "/fast"])
        let snapshotURL = root.appendingPathComponent("internal/recovery.plist")
        var snapshot = SteamInstallRecovery.Snapshot(library: "External/fixture/steamapps", folder: "Fixture", files: [
            .init(relative: "data.bin", size: 9, chunks: chunks.map { .init(offset: $0.offset, length: $0.uncompressedSize, sha: $0.sha) })])
        try SteamInstallRecovery.save(snapshot, at: snapshotURL)
        try Data("abcBAD".utf8).write(to: file)
        let before = try Data(contentsOf: file)
        let audit = try SteamInstallRecovery.audit(at: snapshotURL, library: snapshot.library, steamApps: apps, checkStorage: {}, hash: digest)
        check(audit.verified == 1 && audit.damagedOrMissing == 2, "reconnect finds corrupt and truncated blocks")
        check(try Data(contentsOf: file) == before, "audit preserves existing game data")
        try Data("0\n1\n2\n".utf8).write(to: journals.appendingPathComponent("depot_1_2.journal"))
        let prepared = try Downloader.prepare(plans: [plan], steamApps: apps, installURL: install, journalDir: journals)
        check(prepared.doneBytes == 3 && prepared.pending[0].map(\.chunk) == [1, 2], "journal claims never hide damaged data")
        try data.write(to: file)
        let intact = try Downloader.prepare(plans: [plan], steamApps: apps, installURL: install, journalDir: journals)
        check(intact.doneBytes == 9 && intact.pending[0].isEmpty, "intact blocks are reused")
        snapshot.files[0].relative = "../outside"
        try SteamInstallRecovery.save(snapshot, at: snapshotURL)
        check((try? SteamInstallRecovery.audit(at: snapshotURL, library: snapshot.library, steamApps: apps, checkStorage: {}, hash: digest)) == nil, "unsafe recovery paths fail closed")
        print("PASS: persisted reconnect audit detects corruption/truncation; production resume rechecks completed journals and reuses intact chunks")

        try Data("xxxxxxxxx".utf8).write(to: file)
        let storage = Storage()
        do {
            try await Downloader.fetchChunk(chunks[0], plan: plan, path: file.path, root: apps, attempts: 5, seed: 0,
                                             validateStorage: { try await storage.validate() })
            preconditionFailure("disconnect after network response must stop before writing")
        } catch is DrivePaths.Failure {}
        check(try Data(contentsOf: file) == Data("xxxxxxxxx".utf8), "disconnect prevents late writes")
        print("PASS: loss detected after a network response stops before disk write and CDN retry")

        var slow = plan; slow.hosts = [host + "/slow"]
        let request = Task { try await Downloader.fetchChunk(chunks[0], plan: slow, path: file.path, root: apps,
                                                            attempts: 5, seed: 0, validateStorage: {}) }
        let marker = root.appendingPathComponent("request-started")
        let deadline = Date().addingTimeInterval(10)
        while !fm.fileExists(atPath: marker.path), Date() < deadline { try await Task.sleep(nanoseconds: 20_000_000) }
        check(fm.fileExists(atPath: marker.path), "real network request started")
        let stopped = Date()
        request.cancel()
        do { try await request.value; preconditionFailure("cancelled transfer must fail") }
        catch { check(error is CancellationError || (error as? URLError)?.code == .cancelled, "network cancellation propagated") }
        check(Date().timeIntervalSince(stopped) < 2, "in-flight network task stops promptly")
        check(try Data(contentsOf: file) == Data("xxxxxxxxx".utf8), "no post-cancel writes")
        print("PASS: cancelling a real in-flight HTTP transfer stops promptly without retry or file writes")

        // Deliberately reorder after every failure. Each host must still get
        // one attempt before any is repeated, including the sixth pool entry.
        var rotating = plan
        rotating.hosts = (0..<5).map { host + "/bad\($0)" } + [host + "/fast"]
        try await Downloader.fetchChunk(chunks[0], plan: rotating, path: file.path, root: apps,
                                        attempts: 5, seed: 0, validateStorage: {})
        check(try Data(contentsOf: file).prefix(3) == Data("abc".utf8), "sixth host succeeds within the pool-sized budget")
        print("PASS: production chunk retry reaches the sixth host before repeating failed hosts")

        var exhausted = plan; exhausted.hosts = [host + "/bad-final"]
        do {
            try await Downloader.fetchChunk(chunks[0], plan: exhausted, path: file.path, root: apps,
                                            attempts: 2, seed: 0, validateStorage: {})
            preconditionFailure("HTTP failures must propagate after bounded retries")
        } catch {
            check(Downloader.failureReason(error) == "http-503", "terminal HTTP status remains diagnosable")
        }
    }
}
'''

with tempfile.TemporaryDirectory(prefix='ideck-recovery-') as folder:
    work = Path(folder)
    counts = {'fast': 0, 'slow': 0, 'bad': 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            kind = 'bad' if self.path.startswith('/bad') else ('slow' if self.path.startswith('/slow/') else 'fast')
            counts[kind] += 1
            self.send_response(503 if kind == 'bad' else 200)
            self.send_header('Content-Length', '3')
            self.end_headers()
            if kind == 'slow':
                (work / 'request-started').write_text('started')
                time.sleep(3)
            try:
                self.wfile.write(b'abc')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = work / 'Checks.swift'
    policy = '''
struct Publisher { func send() {} }
struct DockGame { var id: Int; var library: String }
@MainActor final class SteamGamesModel {
    static let shared = SteamGamesModel()
    var games: [DockGame] = []
}
@MainActor final class ExternalStorage {
    static let shared = ExternalStorage()
    let suite = "ideck-download-location-" + UUID().uuidString
    lazy var preferences = UserDefaults(suiteName: suite)!
    let objectWillChange = Publisher()
    var busy = false
'''
    policy += '\n'.join(block(external, marker).replace('UserDefaults.standard', 'preferences') for marker in [
        'var downloadLibrary: String', 'func pendingLibrary(', 'var pendingInstalls:', 'func pinLibrary(', 'func forgetLibrary('])
    policy += '''
}
@MainActor final class Owner {
    static let enabled = true
    static let drive = URL(fileURLWithPath: "/tmp/ideck-download-location-drive")
    var signedIn = true
    var downloads: [Int: Download] = [:]
    var queue: [Int] = []
    var active: (id: Int, task: Task<Void, Never>)?
    var resumeAfterSession = Set<Int>(), resumeAfterBackgroundIDs = Set<Int>()
    var storageInterruptions: [Int: String] = [:]
    var recoveryTasks: [Int: Task<Void, Never>] = [:]
    var recoveryChecked = Set<Int>()
    var storageOperations = 0, checks = 0
    var inSession = false, sessionRunning = false
    var error: String?
    func startTimer() {}
    func pump() {}
    func checkRecoveredDownload(_ id: Int, library: String) {
        checks += 1; recoveryChecked.insert(id); recoveryTasks[id] = Task {}
    }
'''
    policy += '\n'.join(block(owned, marker) for marker in [
        'struct Download: Equatable', 'func externalStorageChanged()', 'func fixedInstallLibrary(',
        'func installLibrary(', 'func installSteamApps(', 'func install(_ appID:']) + '\n}\n'
    journal = downloader[downloader.index('final class JournalWriter {'):]
    progress = block(downloader, 'struct SteamDownloadProgress:')
    source.write_text(STUBS + '\n'.join(pieces) + '\n}\n' + journal + '\n' + progress + '\n' + policy + DRIVER, encoding='utf-8')
    binary = work / 'checks'
    try:
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(source),
                        str(APP / 'DrivePaths.swift'), str(APP / 'SteamInstall.swift'),
                        str(APP / 'SteamKeyValues.swift'), str(APP / 'SwiftSteam/Core/SteamError.swift'),
                        '-o', str(binary)], check=True)
        subprocess.run([str(binary), str(work), f'http://127.0.0.1:{server.server_port}'], check=True, timeout=55)
        assert counts == {'fast': 2, 'slow': 1, 'bad': 7}, counts
        print('PASS: no CDN retry after storage loss or cancellation')
    finally:
        server.shutdown()

    # A paused install is audited on startup/reconnect. Exercise enough real
    # FileHandle reads to expose autoreleased NSData accumulating across chunks.
    memory_driver = r'''
import Foundation
import CryptoKit
import Darwin
func digest(_ bytes: Data) -> Data { Data(Insecure.SHA1.hash(data: bytes)) }
@main struct MemoryCheck {
    static func main() throws {
        let fm = FileManager.default
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let apps = root.appendingPathComponent("steamapps")
        let install = apps.appendingPathComponent("common/Fixture")
        try fm.createDirectory(at: install, withIntermediateDirectories: true)
        let data = Data(repeating: 0x61, count: 1 << 20)
        try data.write(to: install.appendingPathComponent("data.bin"))
        let chunk = SteamInstallRecovery.Chunk(offset: 0, length: UInt32(data.count), sha: digest(data))
        let snapshot = SteamInstallRecovery.Snapshot(library: "fixture/steamapps", folder: "Fixture", files: [
            .init(relative: "data.bin", size: UInt64(data.count), chunks: Array(repeating: chunk, count: 384))])
        let url = root.appendingPathComponent("recovery.plist")
        try SteamInstallRecovery.save(snapshot, at: url)
        let result = try SteamInstallRecovery.audit(at: url, library: snapshot.library, steamApps: apps,
                                                     checkStorage: {}, hash: digest)
        precondition(result.verified == 384 && result.damagedOrMissing == 0)
        var usage = rusage()
        precondition(getrusage(RUSAGE_SELF, &usage) == 0)
        print("MAX_RSS=\(usage.ru_maxrss)")
        let fd = open(url.path, O_WRONLY)
        precondition(fd >= 0 && ftruncate(fd, off_t((64 << 20) + 1)) == 0)
        close(fd)
        do {
            _ = try SteamInstallRecovery.audit(at: url, library: snapshot.library, steamApps: apps,
                                                 checkStorage: {}, hash: digest)
            preconditionFailure("oversized recovery must be rejected before decoding")
        } catch SteamFileError.invalid(let message) { precondition(message.contains("too large")) }
    }
}
'''
    memory_source = work / 'MemoryCheck.swift'
    memory_source.write_text(memory_driver, encoding='utf-8')
    install_source = (APP / 'SteamInstall.swift').read_text(encoding='utf-8')
    pooled = 'matched = autoreleasepool { matches(chunk, at: target, hash: hash) }'
    assert pooled in install_source
    peaks = {}
    for kind in ['baseline', 'bounded']:
        production = work / f'Install-{kind}.swift'
        production.write_text(install_source.replace(pooled, 'matched = matches(chunk, at: target, hash: hash)')
                              if kind == 'baseline' else install_source, encoding='utf-8')
        memory_binary = work / f'memory-{kind}'
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(memory_source), str(production),
                        str(APP / 'DrivePaths.swift'), str(APP / 'SteamKeyValues.swift'),
                        '-o', str(memory_binary)], check=True)
        result = subprocess.run([str(memory_binary), str(work / f'audit-{kind}')],
                                capture_output=True, text=True, timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        peaks[kind] = int(re.search(r'MAX_RSS=(\d+)', result.stdout)[1])
    assert peaks['bounded'] < 160 << 20, peaks
    print(f"PASS: startup recovery checks 384 MiB with bounded peak RSS; baseline={peaks['baseline'] // (1 << 20)} MiB, bounded={peaks['bounded'] // (1 << 20)} MiB; oversized metadata rejected")
