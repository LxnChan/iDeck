#!/usr/bin/env python3
"""Exercise DDI fallback, error classification and cache preservation without a device."""

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--require-swift", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
swift = shutil.which("swiftc")
if not swift:
    if args.require_swift:
        raise SystemExit("FAIL: swiftc is required for DDI download regression checks")
    print("SKIP: swiftc is unavailable; DDI runtime checks require the macOS CI runner")
    raise SystemExit(0)

setup = (root / "app/Madeira/JITSetup.swift").read_text(encoding="utf-8")
start = setup.index("    enum DDIProblem: Equatable {")
end = setup.index("    @Published var method:", start)
problem = setup[start:end]

checks = r'''
import Foundation

enum CheckFailure: Error { case failed(String) }
func check(_ value: @autoclosure () -> Bool, _ name: String) throws {
    guard value() else { throw CheckFailure.failed(name) }
    print("PASS: \(name)")
}

actor Fixture {
    enum Mode: Equatable { case success, rawTimeout, allTimeout, failImage, html, http, cancelled }
    let root: URL
    let mode: Mode
    var requests: [URLRequest] = []
    init(root: URL, mode: Mode) { self.root = root; self.mode = mode }

    func transfer(_ request: URLRequest) throws -> (URL, URLResponse) {
        requests.append(request)
        let url = request.url!
        let raw = url.host == "raw.githubusercontent.com"
        if mode == .cancelled { throw URLError(.cancelled) }
        if mode == .allTimeout || (mode == .rawTimeout && raw)
            || (mode == .failImage && url.lastPathComponent == "Image.dmg") {
            throw URLError(.timedOut)
        }
        let payload: Data
        let html = mode == .html && raw
        if html {
            payload = Data("<html>upstream gateway</html>".utf8)
        } else if url.lastPathComponent == "BuildManifest.plist" {
            payload = try PropertyListSerialization.data(fromPropertyList: ["BuildIdentities": []],
                                                          format: .xml, options: 0)
        } else {
            payload = Data("downloaded \(url.lastPathComponent)".utf8)
        }
        let temporary = root.appendingPathComponent(UUID().uuidString)
        try payload.write(to: temporary)
        return (temporary, HTTPURLResponse(url: url, statusCode: mode == .http && raw ? 503 : 200,
                                           httpVersion: "HTTP/1.1",
                                           headerFields: ["Content-Type": html ? "text/html" : "application/octet-stream"])!)
    }
}

@main struct Checks {
    static func main() async throws {
        let manager = FileManager.default
        let root = manager.temporaryDirectory.appendingPathComponent("ddi-checks-\(UUID().uuidString)")
        try manager.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: root) }
        let configuration = DDIDownloader.configuration(proxy: nil)
        try check(configuration.timeoutIntervalForRequest == 120
                  && configuration.timeoutIntervalForResource == 600, "DDI transfer timeouts are explicit")
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let http = DDIDownloader.configuration(proxy: .init(host: "192.0.2.1", port: 7890, socks5: false))
        try check(http.connectionProxyDictionary?["HTTPSProxy"] as? String == "192.0.2.1",
                  "DDI HTTPS requests honor the app HTTP proxy")
        let socks = DDIDownloader.configuration(proxy: .init(host: "192.0.2.2", port: 1080, socks5: true))
        try check(socks.connectionProxyDictionary?["SOCKSPort"] as? Int == 1080,
                  "DDI transfers support the app SOCKS5 proxy")

        for mode in [Fixture.Mode.success, .rawTimeout, .html, .http] {
            let fixture = Fixture(root: root, mode: mode)
            let downloader = DDIDownloader(session: session, cryptex: true,
                                            transfer: { request in try await fixture.transfer(request) })
            let cache = root.appendingPathComponent("cache-\(mode)")
            try await downloader.download(to: cache)
            try check(downloader.cacheUsable(at: cache), "complete Cryptex cache: \(mode)")
            let requests = await fixture.requests
            if mode != .success {
                try check(requests.count == 6 && requests.dropFirst().allSatisfy {
                    $0.url?.host == "api.github.com"
                    && $0.value(forHTTPHeaderField: "Accept") == "application/vnd.github.raw+json"
                }, "fallback sticks to the working GitHub source: \(mode)")
            }
            try await downloader.download(to: cache)
            try check(downloader.cacheUsable(at: cache), "complete replacement of an existing cache: \(mode)")
        }

        for mode in [Fixture.Mode.allTimeout, .failImage, .cancelled] {
            let fixture = Fixture(root: root, mode: mode)
            let downloader = DDIDownloader(session: session, cryptex: true,
                                            transfer: { request in try await fixture.transfer(request) })
            let cache = root.appendingPathComponent("preserved-\(mode)")
            try manager.createDirectory(at: cache, withIntermediateDirectories: true)
            let old = Data("old cache".utf8)
            let sentinel = cache.appendingPathComponent("sentinel")
            try old.write(to: sentinel)
            do {
                try await downloader.download(to: cache)
                throw CheckFailure.failed("expected download failure")
            } catch let failure as DDIDownloader.Failure {
                try check(failure.localizedDescription.contains("raw.githubusercontent.com")
                          && failure.localizedDescription.contains("api.github.com")
                          && failure.localizedDescription.contains("-1001"),
                          "timeout error includes both hosts and the network error code: \(mode)")
            } catch let error as URLError where error.code == .cancelled {
                let requests = await fixture.requests
                try check(requests.count == 1, "cancellation does not retry")
            }
            let retained = try Data(contentsOf: sentinel)
            let cachedFiles = try manager.contentsOfDirectory(atPath: cache.path)
            try check(retained == old && cachedFiles == ["sentinel"],
                      "failed download preserves the old cache: \(mode)")
            let remainingFiles = try manager.contentsOfDirectory(atPath: root.path)
            try check(!remainingFiles.contains {
                $0.hasPrefix("DDI-download-")
            }, "failed download removes its staging folder: \(mode)")
        }

        let legacy = DDIDownloader(session: session, cryptex: false)
        try check(legacy.filenames.count == 3 && !legacy.filenames.contains("Image.dmg.root_hash"),
                  "personalized DDI does not request Cryptex-only files")
        let timeout = DDIProblem(helperMessage: "The request timed out.", stage: .ddiDownload)
        try check(timeout?.message.contains("redownload the DDI") == true,
                  "a raw network timeout keeps DDI recovery guidance")
        try check(DDIProblem(helperMessage: "ServiceNotFound (idevice code 21/0).", stage: .debugServices) == nil,
                  "a missing debugger service is not labeled a DDI download failure")
        let service = DDIProblem(helperMessage: "ServiceNotFound (idevice code 21/0).", stage: .ddiCheck)
        try check(service?.message.contains("readiness check failed") == true,
                  "a DDI service lookup failure retains its preparation stage")
        let oldResponse = Data(#"{"success":false,"message":"old helper","txmPresent":true}"#.utf8)
        let decoded = try JSONDecoder().decode(MadeiraJITRequest.Response.self, from: oldResponse)
        try check(decoded.failureStage == nil && decoded.diagnostics == nil,
                  "helper responses without new diagnostics remain decodable")
    }
}
'''

with tempfile.TemporaryDirectory(prefix="jit-ddi-check-") as folder:
    folder = Path(folder)
    source = folder / "Checks.swift"
    source.write_text(problem + checks, encoding="utf-8")
    executable = folder / "checks"
    sources = [root / "app/Madeira/JITBuiltInMessages.swift", root / "app/MadeiraJITHelper/DDIDownloader.swift", source]
    subprocess.run([swift, "-parse-as-library", "-swift-version", "5", *map(str, sources), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
