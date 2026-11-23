// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
#if canImport(CFNetwork)
import CFNetwork
#endif

/// Downloads from the same public repository StikJIT uses. The raw host avoids
/// GitHub's redirect; the Contents API provides an independent HTTPS route.
/// Stage the complete set before replacing the cache so a timeout keeps the old set.
struct DDIDownloader {
    struct Failure: LocalizedError {
        let file: String
        let attempts: [String]
        var errorDescription: String? {
            "Failed to download Developer Disk Image: \(file): \(attempts.joined(separator: "; "))"
        }
    }

    let session: URLSession
    let cryptex: Bool
    var transfer: ((URLRequest) async throws -> (URL, URLResponse))? = nil

    static func configuration(proxy: MadeiraJITRequest.DownloadProxy?) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 120
        configuration.timeoutIntervalForResource = 600
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        if let proxy, !proxy.host.isEmpty, (1...65535).contains(proxy.port) {
            configuration.connectionProxyDictionary = proxy.socks5
                ? ["SOCKSEnable": true, "SOCKSProxy": proxy.host,
                   "SOCKSPort": proxy.port, "SOCKSVersion": "kCFStreamSocketSOCKSVersion5"]
                : ["HTTPEnable": true, "HTTPProxy": proxy.host, "HTTPPort": proxy.port,
                   "HTTPSEnable": true, "HTTPSProxy": proxy.host, "HTTPSPort": proxy.port]
#if canImport(CFNetwork)
            if proxy.socks5 {
                configuration.connectionProxyDictionary?["SOCKSVersion"] = kCFStreamSocketSOCKSVersion5
            }
#endif
        }
        return configuration
    }

    var filenames: [String] {
        let common = ["BuildManifest.plist", "Image.dmg", "Image.dmg.trustcache"]
        return cryptex ? common + ["Image.dmg.cryptex_info", "Image.dmg.root_hash"] : common
    }

    func cacheUsable(at directory: URL) -> Bool {
        let manager = FileManager.default
        return filenames.allSatisfy { name in
            let file = directory.appendingPathComponent(name)
            guard let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey]) else {
                return false
            }
            return values.isRegularFile == true && (values.fileSize ?? 0) > 0
        } && (cryptex || ["Image.dmg.cryptex_info", "Image.dmg.root_hash"].allSatisfy {
            !manager.fileExists(atPath: directory.appendingPathComponent($0).path)
        })
    }

    func request(file: String, source: Int) -> URLRequest {
        let variant = cryptex ? "Xcode_iOS_DDI_Cryptex" : "Xcode_iOS_DDI_Personalized"
        let path = "PersonalizedImages/\(variant)/\(file)"
        let address = source == 0
            ? "https://raw.githubusercontent.com/doronz88/DeveloperDiskImage/main/\(path)"
            : "https://api.github.com/repos/doronz88/DeveloperDiskImage/contents/\(path)?ref=main"
        var request = URLRequest(url: URL(string: address)!)
        request.timeoutInterval = 120
        request.setValue("application/vnd.github.raw+json", forHTTPHeaderField: "Accept")
        request.setValue("iDeck-DDI", forHTTPHeaderField: "User-Agent")
        return request
    }

    func download(to directory: URL,
                  progress: (String) async -> Void = { _ in }) async throws {
        let manager = FileManager.default
        let staging = directory.deletingLastPathComponent()
            .appendingPathComponent("DDI-download-\(UUID().uuidString)", isDirectory: true)
        try manager.createDirectory(at: staging, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: staging) }
        var preferredSource = 0

        for file in filenames {
            var attempts: [String] = []
            var downloaded = false
            for source in [preferredSource, 1 - preferredSource] {
                let request = request(file: file, source: source)
                let host = request.url!.host!
                await progress("Downloading \(file) from \(host)")
                do {
                    let temporary: URL
                    let response: URLResponse
                    if let transfer {
                        (temporary, response) = try await transfer(request)
                    } else {
                        (temporary, response) = try await session.download(for: request)
                    }
                    defer { try? manager.removeItem(at: temporary) }
                    try validate(temporary, response: response, file: file)
                    try manager.moveItem(at: temporary, to: staging.appendingPathComponent(file))
                    preferredSource = source
                    downloaded = true
                    await progress("Downloaded \(file) from \(host)")
                    break
                } catch {
                    if error is CancellationError || (error as? URLError)?.code == .cancelled { throw error }
                    let failure = error as NSError
                    let reason = "\(host): \(failure.localizedDescription) (\(failure.domain) \(failure.code))"
                    attempts.append(reason)
                    await progress("Download failed for \(file): \(reason)")
                }
            }
            guard downloaded else { throw Failure(file: file, attempts: attempts) }
        }

        if manager.fileExists(atPath: directory.path) {
            _ = try manager.replaceItemAt(directory, withItemAt: staging)
        } else {
            try manager.moveItem(at: staging, to: directory)
        }
        await progress("Downloaded the complete DDI file set; cache replaced")
    }

    private func validate(_ url: URL, response: URLResponse, file: String) throws {
        guard let response = response as? HTTPURLResponse, response.statusCode == 200 else {
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw NSError(domain: "DDIDownload", code: status,
                          userInfo: [NSLocalizedDescriptionKey: "The download server returned HTTP \(status)."])
        }
        let data = try Data(contentsOf: url, options: .mappedIfSafe)
        guard !data.isEmpty, response.mimeType != "text/html", response.mimeType != "application/json" else {
            throw NSError(domain: "DDIDownload", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "The server did not return a DDI file."])
        }
        if file == "BuildManifest.plist" {
            let plist = try PropertyListSerialization.propertyList(from: data, format: nil)
            guard let manifest = plist as? [String: Any], manifest["BuildIdentities"] is [Any] else {
                throw NSError(domain: "DDIDownload", code: 2,
                              userInfo: [NSLocalizedDescriptionKey: "The DDI build manifest is invalid."])
            }
        }
    }
}
