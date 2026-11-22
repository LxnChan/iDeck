#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Run production recovery, resume preparation and chunk cancellation on macOS.

Temporary files and a local HTTP server only. Content decoding is a passthrough
stand-in here; existing Steam library checks cover the real decrypt/CRC pipeline.
"""
import argparse
import http.server
from pathlib import Path
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
if not swift:
    if args.require_swift:
        raise SystemExit('swiftc is required for download recovery checks')
    print('SKIP: download recovery execution requires macOS swiftc (required in CI)')
    raise SystemExit(0)

downloader = (APP / 'SwiftSteam/Content/DepotDownloader.swift').read_text(encoding='utf-8')
owned = (APP / 'SteamOwnedLibrary.swift').read_text(encoding='utf-8')


def block(source, marker):
    start = source.index(marker)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


# Keep the real preparation, journal, networking, hashing and write logic. The
# enclosing app's authentication/session and CDN-health models are stand-ins.
pieces = [block(downloader, marker).replace('private nonisolated static func', 'nonisolated static func') for marker in [
    'struct WorkItem:', 'struct Prepared:', 'private nonisolated static func prepare(',
    'private nonisolated static func sizeFile(', 'private nonisolated static func chunkAlreadyPresent(',
    'private nonisolated static func fetchChunk(', 'private nonisolated static func failureReason(',
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
enum SteamLog { static func trace(_ value: String) {} }
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
final class Health: @unchecked Sendable {
    func order(_ hosts: [String], seed: Int) -> [String] { hosts }
    func recordSuccess(_ host: String) {}
    func recordFailure(_ host: String, reason: String) {}
}
enum Downloader {
    struct DepotPlan {
        var depotID: UInt32 = 1; var manifestGID: UInt64 = 2; var key = Data()
        var manifest: DepotManifest; var hosts: [String]; var auth: [String: String] = [:]
        var health = Health()
    }
    static var http: URLSession { URLSession(configuration: .ephemeral) }
'''
DRIVER = r'''
func check(_ value: Bool, _ message: String) { precondition(value, message) }
actor Storage {
    var calls = 0
    func validate() throws {
        calls += 1
        if calls > 1 { throw DrivePaths.Failure(message: "Disconnected") }
    }
}
@main struct Checks {
    @MainActor static func main() async throws {
        let fm = FileManager.default
        let root = URL(fileURLWithPath: CommandLine.arguments[1])
        let host = CommandLine.arguments[2]
        let mount = DrivePaths.Mount(id: UUID(), url: root, available: false, problem: "Disconnected")
        let library = mount.relativeRoot + "/steamapps"
        DrivePaths.shared.replace([mount])
        ExternalStorage.shared.pendingInstalls = [42: library, 43: library]
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
    }
}
'''

with tempfile.TemporaryDirectory(prefix='ideck-recovery-') as folder:
    work = Path(folder)
    counts = {'fast': 0, 'slow': 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            kind = 'slow' if self.path.startswith('/slow/') else 'fast'
            counts[kind] += 1
            self.send_response(200)
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
@MainActor final class ExternalStorage {
    static let shared = ExternalStorage()
    var pendingInstalls: [Int: String] = [:]
}
@MainActor final class Owner {
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
    func checkRecoveredDownload(_ id: Int, library: String) {
        checks += 1; recoveryChecked.insert(id); recoveryTasks[id] = Task {}
    }
'''
    policy += block(owned, 'struct Download: Equatable') + '\n' + block(owned, 'func externalStorageChanged()') + '\n}\n'
    journal = downloader[downloader.index('final class JournalWriter {'):]
    progress = block(downloader, 'struct SteamDownloadProgress:')
    source.write_text(STUBS + '\n'.join(pieces) + '\n}\n' + journal + '\n' + progress + '\n' + policy + DRIVER, encoding='utf-8')
    binary = work / 'checks'
    try:
        subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(source),
                        str(APP / 'DrivePaths.swift'), str(APP / 'SteamInstall.swift'),
                        str(APP / 'SteamKeyValues.swift'), str(APP / 'SwiftSteam/Core/SteamError.swift'),
                        '-o', str(binary)], check=True)
        subprocess.run([str(binary), str(work), f'http://127.0.0.1:{server.server_port}'], check=True, timeout=40)
        assert counts == {'fast': 1, 'slow': 1}, counts
        print('PASS: no CDN retry after storage loss or cancellation')
    finally:
        server.shutdown()
