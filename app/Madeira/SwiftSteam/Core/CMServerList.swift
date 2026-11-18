// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 Jfishin, 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
//
// Derived from Jfishin's Madeira Steam client, used in Madeira with the
// author's permission (see docs/STEAM_SIGNIN.md, "Provenance"). Adapted for
// the owned library and downloads (docs/STEAM_LIBRARY.md).

import Foundation

/// Discovers and manages Steam CM (Connection Manager) WebSocket endpoints.
actor CMServerList {
    /// A CM server endpoint (WebSocket)
    struct CMServer: Codable, Sendable {
        let host: String
        let port: UInt16
        var lastAttempt: Date?
        var failCount: Int = 0

        var isHealthy: Bool { failCount < 3 }

        var endpoint: String { "\(host):\(port)" }

        var url: URL { URL(string: "wss://\(host):\(port)/cmsocket/")! }
    }

    private var servers: [CMServer] = []
    private var lastFetched: Date?
    private let cacheKey = "swiftsteam_cm_servers_websocket"
    private let staleInterval: TimeInterval = 3600
    private let defaults: UserDefaults
    private let directoryRequest: (@Sendable (URLRequest) async throws -> (Data, URLResponse))?

    init(defaults: UserDefaults = .standard,
         directoryRequest: (@Sendable (URLRequest) async throws -> (Data, URLResponse))? = nil) {
        self.defaults = defaults
        self.directoryRequest = directoryRequest
    }

    // MARK: - Public API

    /// Get the best available CM server to connect to
    func getServer(excluding: Set<String> = []) async throws -> CMServer {
        if servers.isEmpty || isListStale {
            try await refreshServerList()
        }

        let available = servers.filter { !excluding.contains($0.endpoint) }
        guard !available.isEmpty else { throw SteamError.noServersAvailable }
        guard let server = available
            .filter({ $0.isHealthy })
            .sorted(by: { ($0.lastAttempt ?? .distantPast) < ($1.lastAttempt ?? .distantPast) })
            .first
        else {
            for i in servers.indices where !excluding.contains(servers[i].endpoint) {
                servers[i].failCount = 0
            }
            guard let server = servers.first(where: { !excluding.contains($0.endpoint) }) else {
                throw SteamError.noServersAvailable
            }
            return server
        }

        return server
    }

    func markFailed(endpoint: String) {
        if let index = servers.firstIndex(where: { $0.endpoint == endpoint }) {
            servers[index].failCount += 1
            servers[index].lastAttempt = Date()
        }
    }

    func markSuccess(endpoint: String) {
        if let index = servers.firstIndex(where: { $0.endpoint == endpoint }) {
            servers[index].failCount = 0
            servers[index].lastAttempt = Date()
        }
    }

    func refreshServerList() async throws {
        for attempt in 1...3 {
            try Task.checkCancellation()
            let started = Date()
            do {
                let freshServers = try await fetchServerList()
                try Task.checkCancellation()
                servers = freshServers
                lastFetched = Date()
                cacheServerList()
                SteamLog.event("[steam-cm-directory] source=network servers=\(servers.count) attempt=\(attempt)")
                return
            } catch {
                if Task.isCancelled || error is CancellationError || (error as? URLError)?.code == .cancelled {
                    throw CancellationError()
                }
                let failure = (error as? SteamError) ?? SteamCMTransportPolicy.sanitized(error)
                let elapsed = Int(Date().timeIntervalSince(started) * 1000)
                SteamLog.event("[steam-cm-directory] failed attempt=\(attempt) elapsed-ms=\(elapsed) proxy=\(NetworkProxySettings.shared.isAppActive ? 1 : 0) reason=\(failure)")

                // A failed directory request must not discard endpoints from a
                // previous successful request. Each cached endpoint still goes
                // through the normal authenticated TLS WebSocket handshake.
                // Explicit certificate failures and cancellation remain fatal.
                if let url = error as? URLError,
                   !SteamCMTransportPolicy.canTryAnotherServer(url) { throw failure }
                let cached = servers.isEmpty ? (loadCachedServers() ?? []) : servers
                if !cached.isEmpty {
                    servers = cached
                    // Retry discovery after a minute, rather than treating a
                    // cache fallback as a fresh directory response for an hour.
                    lastFetched = Date().addingTimeInterval(60 - staleInterval)
                    SteamLog.event("[steam-cm-directory] source=cache servers=\(servers.count)")
                    return
                }
                guard attempt < 3 else { throw failure }
                try await Task.sleep(nanoseconds: UInt64(attempt) * 400_000_000)
            }
        }
    }

    // MARK: - Private

    private var isListStale: Bool {
        guard let lastFetched else { return true }
        return Date().timeIntervalSince(lastFetched) > staleInterval
    }

    /// Fetch WebSocket CM server list from Steam Web API
    private func fetchServerList() async throws -> [CMServer] {
        let urlString = "https://api.steampowered.com/ISteamDirectory/GetCMListForConnect/v1/?cellid=0&cmtype=websockets"
        guard let url = URL(string: urlString) else {
            throw SteamError.connectionFailed("Invalid CM directory URL")
        }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.httpMethod = "GET"
        let data: Data, response: URLResponse
        if let directoryRequest {
            (data, response) = try await directoryRequest(request)
        } else {
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = 10
            config.timeoutIntervalForResource = 12
            let http = NetworkProxySettings.shared.makeSession(configuration: config)
            defer { http.finishTasksAndInvalidate() }
            (data, response) = try await http.data(for: request)
        }

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            throw SteamError.connectionFailed("CM directory HTTP \((response as? HTTPURLResponse)?.statusCode ?? 0)")
        }

        // Response format: { "response": { "serverlist": [ { "endpoint": "host:port", ... }, ... ] } }
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let serverResponse = json["response"] as? [String: Any],
              let serverList = serverResponse["serverlist"] as? [[String: Any]] else {
            throw SteamError.connectionFailed("Invalid CM directory response format")
        }

        // Each entry has an "endpoint" field: "hostname:port"
        var seen = Set<String>()
        let servers = serverList.compactMap { entry -> CMServer? in
            guard let endpoint = entry["endpoint"] as? String else { return nil }
            let parts = endpoint.split(separator: ":")
            guard parts.count == 2,
                  let port = UInt16(parts[1]),
                  Self.validHost(String(parts[0])), port > 0,
                  seen.insert(endpoint).inserted else { return nil }
            return CMServer(host: String(parts[0]), port: port)
        }
        guard !servers.isEmpty else { throw SteamError.noServersAvailable }
        SteamLog.trace("Fetched \(servers.count) WebSocket CM servers")
        return servers
    }

    private nonisolated static func validHost(_ host: String) -> Bool {
        !host.isEmpty && host.utf8.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 46
        }
    }

    // MARK: - Caching

    private func cacheServerList() {
        if let data = try? JSONEncoder().encode(servers) {
            defaults.set(data, forKey: cacheKey)
        }
    }

    private func loadCachedServers() -> [CMServer]? {
        guard let data = defaults.data(forKey: cacheKey),
              let cached = try? JSONDecoder().decode([CMServer].self, from: data) else {
            return nil
        }
        var seen = Set<String>()
        return cached.filter { Self.validHost($0.host) && $0.port > 0 && seen.insert($0.endpoint).inserted }
    }
}
