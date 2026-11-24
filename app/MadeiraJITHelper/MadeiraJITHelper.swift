// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

// Madeira's JIT helper: a classic app extension that Madeira starts by its bundle ID
// (app/Madeira/JITBuiltInHost.swift), so a sideloader's renamed install still finds it.
// One MadeiraJITRequest per extension request, answered when the request completes.

import Foundation
#if !targetEnvironment(simulator)
import StikJIT
#endif

#if targetEnvironment(simulator)
private struct DDIPaths {
    static func `default`(in directory: URL) -> DDIPaths { DDIPaths() }
}

private enum StikJIT {
    enum Script { case customBase64(String) }
    struct DeviceSecurityState { let isTXMPresent: Bool? }
    enum PreparationStage { case unavailable }
    enum JITReadiness {
        case unreachable(reason: String)
        case preparationFailed(reason: String)
        case ready(DeviceSecurityState)
    }

    static var isTXMPresent: Bool? { nil }
    static func prepareDevice(pairingFile: URL, paths: DDIPaths,
                              progress: (PreparationStage) -> Void) -> JITReadiness {
        .unreachable(reason: "Built-in JIT is available only on a physical device.")
    }
    static func enableJIT(targetPID: Int32, pairingFile: URL, ddiPaths: DDIPaths,
                          script: Script, forceScript: Bool,
                          preparationProgress: (PreparationStage) -> Void,
                          progress: (String) -> Void) throws {
        throw NSError(domain: "MadeiraJITHelper", code: 100,
                      userInfo: [NSLocalizedDescriptionKey:
                        "Built-in JIT is available only on a physical device."])
    }
    static func resetCachedDDI(at paths: DDIPaths) throws {}
    static func isDDIMounted(pairingFile: URL) throws -> Bool { false }
    static func mountDDI(pairingFile: URL, paths: DDIPaths,
                         progress: (Double) -> Void) throws {
        throw NSError(domain: "MadeiraJITHelper", code: 100,
                      userInfo: [NSLocalizedDescriptionKey: "Built-in JIT is available only on a physical device."])
    }
}
#endif

private actor MadeiraJITWork {
    static let shared = MadeiraJITWork()
    private var active = false
    private var stage: MadeiraJITRequest.FailureStage?
    private var diagnostics: [String] = []

    private func record(_ message: String) {
        diagnostics.append(message)
        NSLog("[MadeiraJIT] %@", message)
    }

    private func response(success: Bool, message: String, txmPresent: Bool?) -> MadeiraJITRequest.Response {
        .init(success: success, message: message, txmPresent: txmPresent,
              failureStage: success ? nil : stage, diagnostics: diagnostics)
    }

    private func preparationProgress(_ progress: StikJIT.PreparationStage) {
#if targetEnvironment(simulator)
        stage = .deviceConnection
#else
        switch progress {
        case .checkingReachability: stage = .deviceConnection
        case .checkingDDI: stage = .ddiCheck
        case .downloadingDDI: stage = .ddiDownload
        case .mountingDDI: stage = .ddiMount
        case .verifyingDDI: stage = .ddiVerification
        case .ready: stage = .debugServices
        @unknown default: break
        }
#endif
        record("Preparation stage: \(String(describing: progress))")
    }

    /// One request at a time, as the XPC handler ran them before. The actor can
    /// re-enter while a DDI download awaits, so reject a second request explicitly.
    func handle(_ request: MadeiraJITRequest) async -> MadeiraJITRequest.Response {
        guard !active else {
            return .init(success: false,
                         message: "Madeira's JIT helper is already handling another request.",
                         txmPresent: StikJIT.isTXMPresent)
        }
        active = true
        defer { active = false }
        stage = nil
        diagnostics = []

        let manager = FileManager.default
        let root = manager.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("StikJIT", isDirectory: true)
        let paths = DDIPaths.default(in: root)

        do {
            try manager.createDirectory(at: root, withIntermediateDirectories: true)
            if request.operation == .resetDDI {
                try StikJIT.resetCachedDDI(at: paths)
                return .init(success: true,
                             message: "Developer Disk Image cache reset.",
                             txmPresent: StikJIT.isTXMPresent)
            }

            guard let pairingData = request.pairingData, !pairingData.isEmpty else {
                throw NSError(domain: "MadeiraJITHelper", code: 1,
                              userInfo: [NSLocalizedDescriptionKey: "The pairing file was not provided."])
            }
            let pairingURL = root.appendingPathComponent("pairingFile-\(UUID().uuidString).plist")
            try pairingData.write(to: pairingURL, options: .atomic)
            defer { try? manager.removeItem(at: pairingURL) }

            switch request.operation {
            case .prepare:
                return try await prepare(pairingURL: pairingURL, paths: paths,
                                         root: root, proxy: request.downloadProxy, forceDownload: false)
            case .redownloadDDI:
                return try await prepare(pairingURL: pairingURL, paths: paths,
                                         root: root, proxy: request.downloadProxy, forceDownload: true)
            case .enable:
                guard let targetPID = request.targetPID,
                      let scriptBase64 = request.scriptBase64,
                      !scriptBase64.isEmpty else {
                    throw NSError(domain: "MadeiraJITHelper", code: 2,
                                  userInfo: [NSLocalizedDescriptionKey:
                                    "The target process or Madeira JIT script was not provided."])
                }
                try StikJIT.enableJIT(
                    targetPID: targetPID,
                    pairingFile: pairingURL,
                    ddiPaths: paths,
                    script: .customBase64(scriptBase64),
                    forceScript: true,
                    preparationProgress: { self.preparationProgress($0) },
                    progress: { NSLog("[MadeiraJIT] %@", $0) })
                return .init(success: true,
                             message: "Madeira detached cleanly from its built-in JIT helper.",
                             txmPresent: StikJIT.isTXMPresent)
            case .resetDDI:
                preconditionFailure("Handled above")
            }
        } catch {
            return response(success: false, message: error.localizedDescription,
                            txmPresent: StikJIT.isTXMPresent)
        }
    }

    private func prepare(pairingURL: URL, paths: DDIPaths, root: URL,
                         proxy: MadeiraJITRequest.DownloadProxy?, forceDownload: Bool) async throws
        -> MadeiraJITRequest.Response {
        let version = ProcessInfo.processInfo.operatingSystemVersion
        let cryptex = version.majorVersion > 26 || (version.majorVersion == 26 && version.minorVersion >= 4)
        let session = URLSession(configuration: DDIDownloader.configuration(proxy: proxy))
        defer { session.invalidateAndCancel() }
        let downloader = DDIDownloader(session: session, cryptex: cryptex)
        let cache = root.appendingPathComponent("DDI", isDirectory: true)

        // A forced download must work even when the device's DDI service is missing.
        // Ordinary setup can use an already mounted image without any internet access.
        var mounted = false
        if !forceDownload {
            stage = .ddiCheck
            record("Checking mounted DDI")
            mounted = try StikJIT.isDDIMounted(pairingFile: pairingURL)
        }
        if forceDownload || (!mounted && !downloader.cacheUsable(at: cache)) {
            stage = .ddiDownload
            record("Downloading DDI (app-proxy=\(proxy == nil ? 0 : 1))")
            try await downloader.download(to: cache) { message in await self.record(message) }
        }

        if forceDownload {
            stage = .ddiCheck
            record("Checking mounted DDI after downloading replacement files")
            mounted = try StikJIT.isDDIMounted(pairingFile: pairingURL)
        }

        if !mounted {
            stage = .ddiMount
            record("Installing DDI")
            try StikJIT.mountDDI(pairingFile: pairingURL, paths: paths) { _ in }
        }
        stage = .ddiVerification
        record("Verifying mounted DDI")
        guard try StikJIT.isDDIMounted(pairingFile: pairingURL) else {
            throw NSError(domain: "MadeiraJITHelper", code: 4,
                          userInfo: [NSLocalizedDescriptionKey:
                            "The Developer Disk Image was not mounted after the mount operation completed."])
        }
        return response(success: true,
                        message: forceDownload ? "The Developer Disk Image was downloaded and verified."
                            : "The local debug connection is reachable and the Developer Disk Image is ready.",
                        txmPresent: StikJIT.isTXMPresent)
    }
}

/// NSExtensionPrincipalClass (Info.plist). The request arrives as JSON in the first input
/// item; the response goes back as JSON in the item the request completes with. Enable
/// completes only when Madeira's script has detached, so the request, and this process,
/// last as long as the debugger does.
@objc(MadeiraJITHelperHandler)
final class MadeiraJITHelperHandler: NSObject, NSExtensionRequestHandling {
    func beginRequest(with context: NSExtensionContext) {
        let info = (context.inputItems.first as? NSExtensionItem)?.userInfo
        let data = info?[MadeiraJITRequest.itemKey] as? Data
        Task {
            let response: MadeiraJITRequest.Response
            if let data, let request = try? JSONDecoder().decode(MadeiraJITRequest.self, from: data) {
                response = await MadeiraJITWork.shared.handle(request)
            } else {
                response = .init(success: false, message: "Madeira's JIT helper received no request.",
                                 txmPresent: nil)
            }
            let item = NSExtensionItem()
            item.userInfo = [MadeiraJITRequest.Response.itemKey: (try? JSONEncoder().encode(response)) ?? Data()]
            context.completeRequest(returningItems: [item], completionHandler: nil)
        }
    }
}
