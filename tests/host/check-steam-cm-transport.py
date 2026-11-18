#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise production CM discovery and transport with scripted network failures."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--require-swift', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
core = root / 'app/Madeira/SwiftSteam/Core'
connection = (core / 'SteamConnection.swift').read_text(encoding='utf-8')
servers = (core / 'CMServerList.swift').read_text(encoding='utf-8')
errors = (core / 'SteamError.swift').read_text(encoding='utf-8')


def function(signature):
    start = connection.index(signature)
    return connection[start:connection.index('\n    }', start) + 6]


methods = '\n'.join(function(signature) for signature in [
    '    func connect() async throws {', '    private func clearTransport() {',
    '    func disconnect() {', '    private func handleDisconnect(task:',
]).replace('task: URLSessionWebSocketTask', 'task: FakeTask')
assert 'guard webSocketTask === task else { return }' in connection
assert 'serverList.getServer(excluding: tried)' in connection
assert 'didReceive challenge' not in connection, 'TLS trust validation must stay enabled'
assert 'timeoutIntervalForRequest = 10' in servers
assert 'timeoutIntervalForResource = 12' in servers
assert 'NetworkProxySettings.shared.makeSession(configuration: config)' in servers
assert 'defer { http.finishTasksAndInvalidate() }' in servers
model = (root / 'app/Madeira/SteamOwnedLibrary.swift').read_text(encoding='utf-8')
assert 'stage=\\(stage) reason=\\(Self.reason(error))' in model
print('PASS: directory timeouts, proxy routing, session cleanup and failure stage wiring')

source = r'''
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
final class NetworkProxySettings: @unchecked Sendable {
    static let shared = NetworkProxySettings()
    let isAppActive = false
    func makeSession(configuration: URLSessionConfiguration) -> URLSession {
        fatalError("Host tests must never contact Steam")
    }
}
enum SteamLog {
    private static let lock = NSLock()
    private static var lines: [String] = []
    static func trace(_ line: String) {}
    static func event(_ line: String) {
        lock.lock(); defer { lock.unlock() }; lines.append(line)
    }
    static var events: String {
        lock.lock(); defer { lock.unlock() }; return lines.joined(separator: "\n")
    }
}
''' + errors + '\n' + servers + r'''
extension CMServerList {
    func seed(_ count: Int, stale: Bool = false) {
        servers = (0..<count).map { CMServer(host: "cm\($0).steampowered.com", port: 443) }
        lastFetched = Date().addingTimeInterval(stale ? -7200 : 0)
    }
    func failures() -> [Int] { servers.map { $0.failCount } }
    func timeUntilRefresh() -> TimeInterval {
        staleInterval + (lastFetched ?? .distantPast).timeIntervalSinceNow
    }
}
actor DirectoryScript {
    enum Reply: Sendable { case fail(Int), http(Int, String), waitForCancellation }
    var replies: [Reply]
    var requests: [URLRequest] = []
    init(_ replies: [Reply]) { self.replies = replies }
    func respond(_ request: URLRequest) async throws -> (Data, URLResponse) {
        requests.append(request)
        precondition(!replies.isEmpty, "directory exceeded its request budget")
        switch replies.removeFirst() {
        case .fail(let code):
            throw NSError(domain: NSURLErrorDomain, code: code, userInfo: [
                NSLocalizedDescriptionKey: "secret-token",
                NSURLErrorFailingURLErrorKey: URL(string: "https://private.invalid/?secret-token")!,
            ])
        case .http(let status, let body):
            return (Data(body.utf8), HTTPURLResponse(url: request.url!, statusCode: status,
                                                   httpVersion: nil, headerFields: nil)!)
        case .waitForCancellation:
            try await Task.sleep(nanoseconds: 30_000_000_000)
            fatalError("request was not cancelled")
        }
    }
    var count: Int { requests.count }
}
final class FakeTask {
    enum CloseCode { case goingAway }
    var cancelled = false
    func cancel(with: CloseCode, reason: Data?) { cancelled = true }
}
final class FakeSession {
    var invalidated = false
    func invalidateAndCancel() { invalidated = true }
}
actor Harness {
    let serverList: CMServerList
    var currentEndpoint: String?, activeConnect: UUID?
    var webSocketTask: FakeTask?, urlSession: FakeSession?
    var attempts: [String] = [], tasks: [FakeTask] = [], sessions: [FakeSession] = []
    var receives = 0
    var codes: [Int?]
    var disconnectHandler: ((Error?) -> Void)?
    init(_ list: CMServerList, _ codes: [Int?]) { serverList = list; self.codes = codes }
    func scheduleReceive(_ task: FakeTask) { receives += 1 }
    private func connect(to server: CMServerList.CMServer) async throws {
        currentEndpoint = server.endpoint; attempts.append(server.endpoint)
        let task = FakeTask(), session = FakeSession()
        tasks.append(task); sessions.append(session)
        webSocketTask = task; urlSession = session
        if let code = codes.removeFirst() {
            throw NSError(domain: NSURLErrorDomain, code: code,
                          userInfo: [NSLocalizedDescriptionKey: "secret-token"])
        }
    }
''' + methods + r'''
    func staleDisconnect() { handleDisconnect(task: tasks[0], error: nil) }
    func status() -> (Int, Int, Int, Int) {
        (attempts.count, receives, tasks.filter { $0.cancelled }.count,
         sessions.filter { $0.invalidated }.count)
    }
}
@main struct Main {
    static let success = #"{"response":{"serverlist":[{"endpoint":"cm-new.steampowered.com:443"}]}}"#
    static var suites: [String] = []
    static func directory(_ replies: [DirectoryScript.Reply], cached: [CMServerList.CMServer] = [])
        -> (CMServerList, DirectoryScript, UserDefaults) {
        let suite = "ideck-cm-test-\(UUID().uuidString)"; suites.append(suite)
        let defaults = UserDefaults(suiteName: suite)!
        if !cached.isEmpty {
            defaults.set(try! JSONEncoder().encode(cached), forKey: "swiftsteam_cm_servers_websocket")
        }
        let script = DirectoryScript(replies)
        return (CMServerList(defaults: defaults, directoryRequest: { try await script.respond($0) }),
                script, defaults)
    }
    static func checkDirectory() async throws {
        defer { for suite in suites { UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite) } }
        let cached = [CMServerList.CMServer(host: "cm-cached.steampowered.com", port: 443)]
        // Both errors from the device log must recover from the persisted cache immediately.
        for code in [-1001, -1200] {
            let (list, script, defaults) = directory([.fail(code)], cached: cached)
            let first = try await list.getServer(); assert(first.endpoint == cached[0].endpoint)
            let calls = await script.count; assert(calls == 1)
            let remaining = await list.timeUntilRefresh(); assert(remaining > 55 && remaining <= 60)
            let second = try await list.getServer(); assert(second.endpoint == first.endpoint)
            let afterSecond = await script.count; assert(afterSecond == 1, "discovery cooldown missing")
            let stored = try JSONDecoder().decode([CMServerList.CMServer].self,
                from: defaults.data(forKey: "swiftsteam_cm_servers_websocket")!)
            assert(stored[0].endpoint == cached[0].endpoint)
        }
        // Stale memory retains endpoint penalties; it must not reset failed hosts on fallback.
        let (stale, staleScript, _) = directory([.fail(-1001)])
        await stale.seed(2, stale: true); await stale.markFailed(endpoint: "cm0.steampowered.com:443")
        _ = try await stale.getServer()
        let penalties = await stale.failures(); assert(penalties == [1, 0])
        let staleCalls = await staleScript.count; assert(staleCalls == 1)
        // A cold start retries transient errors, then persists a successful response.
        let (retry, retryScript, retryDefaults) = directory([.fail(-1001), .fail(-1200), .http(200, success)])
        let recovered = try await retry.getServer(); assert(recovered.host == "cm-new.steampowered.com")
        let retryCalls = await retryScript.count; assert(retryCalls == 3)
        let requests = await retryScript.requests
        assert(requests.allSatisfy { $0.timeoutInterval == 10 && $0.httpMethod == "GET" })
        let persisted = try JSONDecoder().decode([CMServerList.CMServer].self,
            from: retryDefaults.data(forKey: "swiftsteam_cm_servers_websocket")!)
        assert(persisted[0].host == recovered.host)
        let fresh = await retry.timeUntilRefresh(); assert(fresh > 3590)
        // HTTP errors, invalid JSON and empty lists must also use known endpoints.
        for reply in [DirectoryScript.Reply.http(503, ""), .http(200, "invalid"),
                      .http(200, #"{"response":{"serverlist":[]}}"#)] {
            let (list, script, _) = directory([reply], cached: cached)
            let server = try await list.getServer(); assert(server.endpoint == cached[0].endpoint)
            let calls = await script.count; assert(calls == 1)
        }
        let (exhausted, exhaustedScript, _) = directory([.fail(-1001), .fail(-1200), .fail(-1001)])
        do { _ = try await exhausted.getServer(); fatalError("retry budget ignored") }
        catch { assert((error as? SteamError) == .transportFailed(domain: NSURLErrorDomain, code: -1001)) }
        let exhaustedCalls = await exhaustedScript.count; assert(exhaustedCalls == 3)
        // Trust errors and cancellation remain fatal even with a cache.
        for code in [-1201, -1202, -1203, -1204, -1205, -1206, -1009, -999] {
            let (list, script, _) = directory([.fail(code)], cached: cached)
            do { _ = try await list.getServer(); fatalError("nonrecoverable error ignored") }
            catch {
                if code == -999 { assert(error is CancellationError) }
                else { assert((error as? SteamError) == .transportFailed(domain: NSURLErrorDomain, code: code)) }
            }
            let calls = await script.count; assert(calls == 1)
        }
        let (cancelList, cancelScript, _) = directory([.waitForCancellation], cached: cached)
        let cancelled = Task { try await cancelList.getServer() }
        while await cancelScript.count == 0 { await Task.yield() }
        cancelled.cancel()
        do { _ = try await cancelled.value; fatalError("task cancellation ignored") }
        catch { assert(error is CancellationError) }
        // Invalid endpoints in the cache or response must not reach the URL force-unwrap.
        let invalid = [CMServerList.CMServer(host: "private.invalid/?secret-token", port: 443)]
        let badBody = #"{"response":{"serverlist":[{"endpoint":"private.invalid/?secret-token:443"},{"endpoint":"cm-new.steampowered.com:0"}]}}"#
        let (validated, validationScript, _) = directory([.fail(-1001), .http(200, badBody), .http(200, success)], cached: invalid)
        let valid = try await validated.getServer(); assert(valid.host == "cm-new.steampowered.com")
        let validCalls = await validationScript.count; assert(validCalls == 3)
        assert(SteamLog.events.contains("[steam-cm-directory] source=cache"))
        assert(SteamLog.events.contains("[steam-cm-directory] failed"))
        assert(!SteamLog.events.contains("secret-token") && !SteamLog.events.contains("private.invalid"))
        print("PASS: production CM directory recovery, retry bounds, cooldown, persistence, cancellation and redaction")
    }
    static func checkTransport() async throws {
        for code in [-1201, -1202, -1203, -1204, -1205, -1206, -999, -1009] {
            assert(!SteamCMTransportPolicy.canTryAnotherServer(URLError(URLError.Code(rawValue: code))))
        }
        let list = CMServerList(); await list.seed(3)
        let harness = Harness(list, [-1200, -1003, nil]); try await harness.connect()
        let status = await harness.status()
        assert(status.0 == 3 && status.1 == 1 && status.2 == 2 && status.3 == 2)
        await harness.staleDisconnect()
        let afterStale = await harness.status(); assert(afterStale.2 == 2 && afterStale.3 == 2)
        let names = await harness.attempts; assert(Set(names).count == 3)
        let failures = await list.failures(); assert(failures == [1, 1, 0])
        let scenarios: [(Int, [Int?])] = [(3, [-1202, nil]), (1, [-1200]), (3, [-999, nil]),
                                         (5, [-1200, -1200, -1200, nil])]
        for (count, codes) in scenarios {
            let list = CMServerList(); await list.seed(count)
            let harness = Harness(list, codes)
            do { try await harness.connect(); fatalError("transport accepted failure or exceeded budget") }
            catch {
                if codes[0] == -999 { assert(error is CancellationError) }
                else {
                    assert((error as? SteamError) == .transportFailed(domain: NSURLErrorDomain, code: codes[0]!))
                    assert(!error.localizedDescription.contains("secret-token"))
                }
            }
            let status = await harness.status(); let expected = count == 5 ? 3 : 1
            assert(status.0 == expected && status.1 == 0 && status.2 == expected && status.3 == expected)
        }
        print("PASS: production CM selection, cleanup, certificate validation, cancellation and transport retry bounds")
    }
    static func main() async throws {
        try await checkDirectory()
        try await checkTransport()
    }
}
'''

compiler = shutil.which('swiftc')
if not compiler:
    if args.require_swift or os.environ.get('GITHUB_ACTIONS') == 'true':
        raise RuntimeError('swiftc is required for CM directory and transport regression tests')
    print('SKIP: swiftc unavailable; compiled CM regression tests run in macOS CI')
else:
    with tempfile.TemporaryDirectory(prefix='ideck-cm-') as temporary:
        directory = Path(temporary)
        path = directory / 'cm.swift'
        path.write_text(source, encoding='utf-8')
        executable = directory / ('cm-check.exe' if os.name == 'nt' else 'cm-check')
        subprocess.run([compiler, '-parse-as-library', '-swift-version', '5', str(path),
                        '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True, timeout=30)
