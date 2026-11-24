#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Execute production CDN discovery with scripted HTTPS directory replies.

No Steam credentials or live endpoints. Chunk rotation and real HTTP failures
are exercised separately by check-download-recovery.py.
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
source = (APP / 'SwiftSteam/Content/DepotDownloader.swift').read_text(encoding='utf-8')


def block(marker, text=source):
    start = text.index(marker)
    end = text.index('{', start) + 1
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


discovery = block('private func contentServers(')
assert 'https://api.steampowered.com/' in discovery
assert 'Self.directoryCells(session.cellID)' in discovery
assert 'request.timeoutInterval = 12' in discovery
assert 'servers.prefix(20)' in discovery
assert 'localizedDescription' not in discovery
assert 'let pool = Self.contentPool(hosts, maximum: hostPoolSize)' in source
assert 'hosts: pool, validateStorage:' in source
reason = block('nonisolated static func failureReason(')
assert 'failure.domain == NSURLErrorDomain' in reason
assert 'userInfo' not in reason
print('PASS: bounded HTTPS discovery, shared manifest/chunk pool, and credential-free error diagnostics')
swift = shutil.which('swiftc')
if not swift:
    if args.require_swift:
        raise SystemExit('swiftc is required for CDN discovery checks')
    print('SKIP: production Swift execution requires macOS swiftc (required in CI)')
    raise SystemExit(0)

driver = r'''
import Foundation
@MainActor enum SteamLog {
    static var lines: [String] = []
    static func event(_ line: String) { lines.append(line) }
}
@MainActor final class DirectoryHTTP {
    var seen: [UInt32] = []
    var mode = "regional"
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        let url = request.url!
        precondition(url.scheme == "https" && url.host == "api.steampowered.com")
        precondition(request.timeoutInterval == 12)
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)!.queryItems!
        let cell = UInt32(query.first { $0.name == "cell_id" }!.value!)!
        seen.append(cell)
        if mode == "cancel" { throw NSError(domain: NSURLErrorDomain, code: -999) }
        if mode == "offline" { throw NSError(domain: NSURLErrorDomain, code: -1001,
            userInfo: [NSLocalizedDescriptionKey: "secret-auth-value", NSURLErrorFailingURLStringErrorKey: "https://private/?auth=secret-auth-value"]) }
        var servers: [[String: Any]] = []
        if mode == "regional" && cell != 1 {
            servers = ["dl.steam.clngaa.com", "xz.pphimalayanrt.com", "st.dl.eccdnx.com"].map {
                ["host": $0, "https_support": "unavailable"]
            }
        } else if mode == "regional" || mode == "healthy" {
            servers = (0..<8).map { ["host": "edge\($0).regional.example", "https_support": "mandatory"] }
            servers += [servers[0], ["host": "bad.example", "use_as_proxy": true],
                ["host": "restricted.example", "allowed_app_ids": [42]],
                ["host": "unusable.example:8080", "https_support": "optional"],
                ["vhost": "EDGE0.REGIONAL.EXAMPLE", "https_support": "optional"]]
        } else if mode == "malformed" {
            return (Data("invalid JSON".utf8), HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
        }
        let data = try JSONSerialization.data(withJSONObject: ["response": ["servers": servers]])
        return (data, HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: nil)!)
    }
}
@MainActor final class DepotDownloader {
    struct Session { var cellID: UInt32 = 52 }
    var session = Session()
    let hostPoolSize = 6
    static let http = DirectoryHTTP()
'''
for marker in ('enum ServerEligibility:', 'nonisolated static func serverEligibility(',
               'private func contentServers(', 'nonisolated static func directoryCells(',
               'nonisolated static func contentPool(', 'nonisolated static func usableContentHost(',
               'nonisolated static func failureReason(', 'struct HTTPFailure:'):
    driver += block(marker).replace('private func contentServers(', 'func contentServers(') + '\n'
driver += '\n}\n@MainActor enum SteamOwnedLibrary {\n' + block(
    'static func reason(_ error:', (APP / 'SteamOwnedLibrary.swift').read_text(encoding='utf-8')) + '\n}\n'
driver += '\nenum SteamSignIn {\n' + block(
    'static func message(_ error:', (APP / 'SwiftSteam/SteamSignIn.swift').read_text(encoding='utf-8')) + '\n}\n'
driver += r'''
@main struct Checks {
    @MainActor static func main() async throws {
        let downloader = DepotDownloader(), http = DepotDownloader.http
        let fallback = "https://steampipe.akamaized.net"
        let hosts = try await downloader.contentServers(appID: 1)
        precondition(http.seen == [52, 0, 1])
        precondition(hosts.count == 9 && Set(hosts).count == hosts.count)
        precondition(!hosts.contains("https://bad.example") && !hosts.contains("https://restricted.example"))
        precondition(!hosts.contains("https://dl.steam.clngaa.com"))
        let pool = DepotDownloader.contentPool(hosts, maximum: 6)
        precondition(pool.count == 6 && pool.last == fallback)
        precondition(SteamLog.lines.contains { $0.contains("reason=no-https") })
        precondition(SteamLog.lines.contains { $0.contains("reason=proxy-only") })
        precondition(SteamLog.lines.contains { $0.contains("reason=app-restricted") })
        precondition(SteamLog.lines.contains { $0.contains("reason=invalid-host") })
        print("PASS: regional HTTP-only reproduction discovers alternate HTTPS partners, deduplicates hosts, and retains fallback in six-host pool")
        http.mode = "healthy"; http.seen = []
        _ = try await downloader.contentServers(appID: 1)
        precondition(http.seen == [52])
        precondition(DepotDownloader.directoryCells(0) == [0, 1] && DepotDownloader.directoryCells(1) == [1, 0])
        for mode in ["offline", "malformed"] {
            http.mode = mode; http.seen = []
            let recovered = try await downloader.contentServers(appID: 1)
            precondition(recovered == [fallback] && http.seen == [52, 0, 1])
        }
        precondition(SteamLog.lines.contains { $0.contains("reason=url-1001") })
        precondition(!SteamLog.lines.contains { $0.contains("secret-auth-value") })
        http.mode = "cancel"; http.seen = []
        do { _ = try await downloader.contentServers(appID: 1); preconditionFailure("cancel must stop discovery") }
        catch is CancellationError {}
        precondition(http.seen == [52])
        print("PASS: healthy discovery stops early; outages and malformed replies have bounded fallback; cancellation stops immediately")
        for bad in ["localhost", "127.0.0.1", "[::1]", "user@edge.example", "edge.example/path", "edge.example?auth=secret", "x..example", "-x.example", "x.example:443", "lancache.example", "a\n.example", String(repeating: "a", count: 64) + ".example"] {
            precondition(!DepotDownloader.usableContentHost(bad), bad)
        }
        for good in ["dl.steam.clngaa.com", "edge.regional.example", "cache1.steamcontent.com"] {
            precondition(DepotDownloader.usableContentHost(good))
        }
        precondition(DepotDownloader.failureReason(NSError(domain: NSURLErrorDomain, code: -1200)) == "url-1200")
        precondition(DepotDownloader.failureReason(DepotDownloader.HTTPFailure(status: 503)) == "http-503")
        let network = NSError(domain: NSURLErrorDomain, code: -1001, userInfo: [NSLocalizedDescriptionKey: "secret-auth-value"])
        precondition(SteamOwnedLibrary.reason(network) == "url-1001")
        precondition(SteamOwnedLibrary.reason(DepotDownloader.HTTPFailure(status: 403)) == "http-403")
        precondition(SteamSignIn.message(network) == "Steam did not respond in time. Try again.")
        precondition(!SteamSignIn.message(network).contains("secret-auth-value"))
        print("PASS: DNS partner validation and NSError/HTTP diagnostics retain codes without logging URLs or tokens")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='ideck-cdn-') as folder:
    path = Path(folder)
    main = path / 'Checks.swift'
    main.write_text(driver, encoding='utf-8')
    subprocess.run([swift, '-parse-as-library', '-swift-version', '5', str(main),
                    str(APP / 'SwiftSteam/Core/SteamError.swift'), '-o', str(path / 'checks')], check=True)
    subprocess.run([str(path / 'checks')], check=True, timeout=15)
