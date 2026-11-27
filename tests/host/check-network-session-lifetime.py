#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise production transfer methods with counted sessions and injected failures."""
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
depot = (APP / 'SwiftSteam/Content/DepotDownloader.swift').read_text(encoding='utf-8')
cloud = (APP / 'SteamCloud.swift').read_text(encoding='utf-8')


def block(source, marker):
    start = source.index(marker)
    body_start = source.index('async throws -> URL {', start) if marker == 'func install(' else start
    end = source.index('{', body_start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


install = block(depot, 'func install(')
assert install.count('Self.makeHTTP()') == 1
assert 'defer { http.invalidateAndCancel() }' in install
assert 'contentServers(appID: app.appID, http: http)' in install
assert 'hosts: pool, http: http, validateStorage:' in install
assert 'seed: item.file &+ item.chunk, http: http, validateStorage:' in install
assert 'static var http:' not in depot + cloud
for path in APP.rglob('*.swift'):
    assert 'NetworkProxySettings.session' not in path.read_text(encoding='utf-8'), path
for name in ['Library.swift', 'SwiftSteam/Auth/SteamAuthAPI.swift']:
    source = (APP / name).read_text(encoding='utf-8')
    assert source.count('NetworkProxySettings.shared.makeSession()') == source.count('defer { session.invalidateAndCancel() }')
assert 'session.finishTasksAndInvalidate()' in (APP / 'WineMono.swift').read_text(encoding='utf-8')
print('PASS: one scoped install pool reaches directory, manifests, and chunks; temporary callers release sessions')
swift = shutil.which('swiftc')
if not swift:
    if args.require_swift:
        raise SystemExit('swiftc is required for session lifetime checks')
    print('SKIP: Swift transfer execution requires macOS swiftc (required in CI)')
    raise SystemExit(0)

driver = r'''
import Foundation
import CryptoKit
final class FakeHTTP: @unchecked Sendable {
    static var created = 0, closed = 0, requests = 0
    static var failure: Error?, status = 200
    let configuration: URLSessionConfiguration
    var invalidated = false
    init(configuration: URLSessionConfiguration) {
        self.configuration = configuration
        Self.created += 1
    }
    func invalidateAndCancel() {
        precondition(!invalidated)
        invalidated = true; Self.closed += 1
    }
    func data(from url: URL) async throws -> (Data, URLResponse) {
        precondition(!invalidated)
        Self.requests += 1
        try Task.checkCancellation()
        if let error = Self.failure { throw error }
        return (Data("abc".utf8), HTTPURLResponse(url: url, statusCode: Self.status, httpVersion: nil, headerFields: nil)!)
    }
    func data(for request: URLRequest) async throws -> (Data, URLResponse) { try await data(from: request.url!) }
    func upload(for request: URLRequest, from body: Data) async throws -> (Data, URLResponse) {
        try await data(for: request)
    }
}
final class NetworkProxySettings {
    static let shared = NetworkProxySettings()
    var port = 7890
    func apply(to config: URLSessionConfiguration) { config.connectionProxyDictionary = ["HTTPPort": port] }
}
enum SteamLog { static func event(_ value: String) {}; static func trace(_ value: String) {} }
enum ContentDecryptor {
    static func processChunk(encryptedData: Data, depotKey: Data, expectedCRC: UInt32, expectedSize: Int) throws -> Data { encryptedData }
}
struct DepotManifest {
    struct ChunkEntry {
        let shaHex = "fixture", crc: UInt32 = 0, uncompressedSize: UInt32 = 3, offset: UInt64 = 0
    }
}
enum SteamFileError: Error { case invalid(String) }
struct SteamCloudDownloadInfo {
    var encrypted = false, fileSize: UInt64 = 3, rawSize: UInt64 = 3
    let url = URL(string: "https://fixture.invalid/save")
    let headers: [(name: String, value: String)] = []
}
struct SteamCloudUploadBlock {
    let url = URL(string: "https://fixture.invalid/save")
    let explicitBody = Data(), offset: UInt64 = 0, length: UInt64 = 3, method = 3
    let headers: [(name: String, value: String)] = []
}
'''
driver += block(depot, 'final class ContentHostHealth:')
driver += r'''
enum Downloader {
    static var writes = 0
    struct DepotPlan {
        let depotID = 1, key = Data(), hosts = ["https://one.invalid", "https://two.invalid"]
        let auth: [String: String] = [:]
        let health = ContentHostHealth()
    }
    static func write(_ data: Data, to: String, root: URL, offset: UInt64) throws { writes += 1 }
'''
for marker in ['private nonisolated static func makeHTTP(', 'private nonisolated static func fetchChunk(',
               'private nonisolated static func download(', 'nonisolated static func failureReason(', 'struct HTTPFailure:']:
    driver += block(depot, marker).replace('private ', '').replace('URLSession', 'FakeHTTP').replace('FakeHTTPConfiguration', 'URLSessionConfiguration') + '\n'
driver += '\n}\nenum SteamCloudTransfer {\nstatic let maxFileBytes = 256 << 20\n'
driver += 'static func unzipFirstEntry(_ data: Data, rawSize: Int) -> Data? { nil }\n'
for marker in ['private static func makeHTTP(', 'static func fetch(', 'static func send(']:
    driver += block(cloud, marker).replace('URLSession', 'FakeHTTP').replace('FakeHTTPConfiguration', 'URLSessionConfiguration') + '\n'
driver += r'''
}
@main struct Checks {
    static func main() async throws {
        let http = Downloader.makeHTTP(), plan = Downloader.DepotPlan()
        precondition(http.configuration.httpMaximumConnectionsPerHost == 8)
        precondition(http.configuration.urlCache == nil)
        for _ in 0..<512 {
            try await Downloader.fetchChunk(.init(), plan: plan, path: "unused", root: URL(fileURLWithPath: "/"), attempts: 5, seed: 0, http: http, validateStorage: {})
        }
        precondition(FakeHTTP.created == 1 && Downloader.writes == 512)
        for code in [POSIXErrorCode.ENOMEM, .ENOBUFS, .EMFILE, .ENFILE] {
            let memory = NSError(domain: NSPOSIXErrorDomain, code: Int(code.rawValue))
            let wrapped = NSError(domain: NSURLErrorDomain, code: -1005, userInfo: [NSUnderlyingErrorKey: memory])
            for error in [memory, wrapped] {
                FakeHTTP.failure = error
                let before = FakeHTTP.requests
                do {
                    try await Downloader.fetchChunk(.init(), plan: plan, path: "unused", root: URL(fileURLWithPath: "/"), attempts: 5, seed: 0, http: http, validateStorage: {})
                    preconditionFailure("resource failure must stop")
                } catch { precondition(SteamNetworkFailure.isResourceExhaustion(error)) }
                precondition(FakeHTTP.requests == before + 1 && Downloader.writes == 512)
                precondition(!SteamCMTransportPolicy.canTryAnotherServer(error))
                precondition(SteamCMTransportPolicy.sanitized(error) == .transportFailed(domain: NSPOSIXErrorDomain, code: Int(code.rawValue)))
            }
        }
        precondition(!SteamNetworkFailure.isResourceExhaustion(NSError(domain: NSURLErrorDomain, code: 12)))
        precondition(!SteamNetworkFailure.isResourceExhaustion(NSError(domain: NSPOSIXErrorDomain, code: Int(POSIXErrorCode.ENOSPC.rawValue))))
        precondition(SteamCMTransportPolicy.canTryAnotherServer(URLError(.timedOut)))
        http.invalidateAndCancel()
        NetworkProxySettings.shared.port = 9000
        let resumed = Downloader.makeHTTP()
        precondition(resumed.configuration.connectionProxyDictionary?["HTTPPort"] as? Int == 9000)
        precondition(http.configuration.connectionProxyDictionary?["HTTPPort"] as? Int == 7890)
        resumed.invalidateAndCancel()
        print("PASS: 512 chunks reuse one pool; local resource errors stop before retry/write; resumed pool reads new proxy settings")
        let data = Data("abc".utf8), sha = Data(Insecure.SHA1.hash(data: Data("abc".utf8)))
        for mode in 0..<4 {
            FakeHTTP.failure = mode == 1 ? NSError(domain: NSPOSIXErrorDomain, code: 12) : mode == 2 ? CancellationError() : nil
            FakeHTTP.status = mode == 3 ? 503 : 200
            let before = FakeHTTP.created, requests = FakeHTTP.requests
            do {
                let result = try await SteamCloudTransfer.send(data, blocks: Array(repeating: .init(), count: 128))
                precondition(mode == 0 && result.count == 128)
            } catch { precondition(mode != 0) }
            precondition(FakeHTTP.created == before + 1 && FakeHTTP.closed == FakeHTTP.created)
            precondition(FakeHTTP.requests == requests + (mode == 0 ? 128 : 1))
            do {
                let result = try await SteamCloudTransfer.fetch(.init(), expectedSHA: sha)
                precondition(mode == 0 && result == data)
            } catch { precondition(mode != 0) }
            precondition(FakeHTTP.created == before + 2 && FakeHTTP.closed == FakeHTTP.created)
        }
        FakeHTTP.status = 200; FakeHTTP.failure = nil
        do {
            _ = try await SteamCloudTransfer.fetch(.init(), expectedSHA: Data())
            preconditionFailure("bad checksum must fail")
        } catch {}
        precondition(FakeHTTP.closed == FakeHTTP.created)
        print("PASS: multipart cloud upload reuses one pool; success, network error, cancellation, HTTP error and checksum failure release sessions")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='ideck-session-lifetime-') as folder:
    path = Path(folder)
    main = path / 'Checks.swift'
    main.write_text(driver, encoding='utf-8')
    subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(main),
                    str(APP / 'SwiftSteam/Core/SteamError.swift'), '-o', str(path / 'checks')], check=True)
    subprocess.run([str(path / 'checks')], check=True, timeout=30)
