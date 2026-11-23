// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// Codable messages shared by Madeira and its JIT helper extension. Each travels as JSON
/// in an extension request's item (userInfo[itemKey]), to the helper and back.
struct MadeiraJITRequest: Codable, Sendable {
    static let itemKey = "madeira-jit-request"

    enum Operation: String, Codable, Sendable {
        case prepare
        case enable
        case resetDDI
        case redownloadDDI
    }

    let operation: Operation
    let targetPID: Int32?
    let pairingData: Data?
    let scriptBase64: String?
    let downloadProxy: DownloadProxy?

    /// Only internet downloads use this proxy; device tunnels always connect directly.
    struct DownloadProxy: Codable, Sendable {
        let host: String
        let port: Int
        let socks5: Bool
    }

    static func prepare(pairingData: Data, downloadProxy: DownloadProxy? = nil) -> MadeiraJITRequest {
        MadeiraJITRequest(operation: .prepare, targetPID: nil,
                          pairingData: pairingData, scriptBase64: nil, downloadProxy: downloadProxy)
    }

    static func enable(targetPID: Int32, pairingData: Data,
                       scriptBase64: String) -> MadeiraJITRequest {
        MadeiraJITRequest(operation: .enable, targetPID: targetPID,
                          pairingData: pairingData, scriptBase64: scriptBase64, downloadProxy: nil)
    }

    static var resetDDI: MadeiraJITRequest {
        MadeiraJITRequest(operation: .resetDDI, targetPID: nil,
                          pairingData: nil, scriptBase64: nil, downloadProxy: nil)
    }

    static func redownloadDDI(pairingData: Data, downloadProxy: DownloadProxy? = nil) -> MadeiraJITRequest {
        MadeiraJITRequest(operation: .redownloadDDI, targetPID: nil,
                          pairingData: pairingData, scriptBase64: nil, downloadProxy: downloadProxy)
    }

    enum FailureStage: String, Codable, Sendable {
        case deviceConnection
        case ddiCheck
        case ddiDownload
        case ddiMount
        case ddiVerification
        case debugServices
    }

    struct Response: Codable, Sendable {
        static let itemKey = "madeira-jit-response"
        let success: Bool
        let message: String
        let txmPresent: Bool?
        let failureStage: FailureStage?
        let diagnostics: [String]?

        init(success: Bool, message: String, txmPresent: Bool?,
             failureStage: FailureStage? = nil, diagnostics: [String]? = nil) {
            self.success = success
            self.message = message
            self.txmPresent = txmPresent
            self.failureStage = failureStage
            self.diagnostics = diagnostics
        }
    }
}
