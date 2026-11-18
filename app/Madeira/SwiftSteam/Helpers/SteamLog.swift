// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// Logging for Steam sign-in.
///
/// `event` lines are the always-on, low-volume record ([steam-signin]). They
/// never contain tokens, passwords, Steam Guard codes, account names, Steam
/// IDs or message payloads.
///
/// `trace` lines are protocol-level detail, off by default. Enable with
/// `env.MADEIRA_STEAM_TRACE = 1` in madeira.cfg. They are still written
/// without credentials or payload bytes.
enum SteamLog {
    static let tracing = SteamSignIn.flag("MADEIRA_STEAM_TRACE", default: false)

    /// Connection diagnostics follow the live Extended logging setting without
    /// enabling the much noisier per-message protocol trace.
    static var connectionsEnabled: Bool { tracing || madeira_get_diag_enabled() != 0 }

    static func connection(_ message: @autoclosure () -> String) {
        guard connectionsEnabled else { return }
        LogStore.shared.log("[steam-connection] " + message())
    }

    static func trace(_ message: @autoclosure () -> String) {
        guard tracing else { return }
        // LogStore, not stderr: stderr is only captured into the log once a
        // Wine session starts, and sign-in happens before one.
        LogStore.shared.log("[steam-trace] " + message())
    }

    static func event(_ message: String) {
        LogStore.shared.log(message)
    }
}

/// URLSession timings contain no headers, query strings or response bodies.
/// Missing phases stay '-' so a timeout before TLS can be distinguished from
/// one waiting for the server. A reused connection may have no DNS/TLS phase.
final class SteamNetworkMetrics: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let kind: String
    init(kind: String) { self.kind = kind }

    func urlSession(_ session: URLSession, task: URLSessionTask, didFinishCollecting metrics: URLSessionTaskMetrics) {
        Self.log(metrics, kind: kind)
    }

    static func milliseconds(_ start: Date?, _ end: Date?) -> String {
        guard let start, let end else { return "-" }
        return String(max(0, Int(end.timeIntervalSince(start) * 1000)))
    }

    static func log(_ metrics: URLSessionTaskMetrics, kind: String) {
        guard SteamLog.connectionsEnabled else { return }
        for (index, transaction) in metrics.transactionMetrics.enumerated() {
            SteamLog.connection("kind=\(kind) transaction=\(index + 1) host=\(transaction.request.url?.host ?? "-") "
                + "remote=\(transaction.remoteAddress ?? "-") "
                + "protocol=\(transaction.networkProtocolName ?? "-") proxy=\(transaction.isProxyConnection ? 1 : 0) "
                + "reused=\(transaction.isReusedConnection ? 1 : 0) status=\((transaction.response as? HTTPURLResponse)?.statusCode ?? 0) "
                + "dns-ms=\(milliseconds(transaction.domainLookupStartDate, transaction.domainLookupEndDate)) "
                + "connect-ms=\(milliseconds(transaction.connectStartDate, transaction.connectEndDate)) "
                + "tls-ms=\(milliseconds(transaction.secureConnectionStartDate, transaction.secureConnectionEndDate)) "
                + "dns-started=\(transaction.domainLookupStartDate == nil ? 0 : 1) "
                + "connect-started=\(transaction.connectStartDate == nil ? 0 : 1) tls-started=\(transaction.secureConnectionStartDate == nil ? 0 : 1) "
                + "response-ms=\(milliseconds(transaction.requestEndDate, transaction.responseStartDate)) "
                + "receive-ms=\(milliseconds(transaction.responseStartDate, transaction.responseEndDate)) "
                + "total-ms=\(Int(metrics.taskInterval.duration * 1000))")
        }
    }
}
