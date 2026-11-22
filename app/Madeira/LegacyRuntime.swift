// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
import SwiftUI
import UniformTypeIdentifiers
import CryptoKit
import Darwin

private final class LegacyRuntimeRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(LegacyRuntimePin.allowed(request.url) ? request : nil)
    }
}

enum LegacyRuntimeStorage {
    static func hash(_ data: Data) -> String { SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined() }
    static func verifiedPackage(_ url: URL) -> Bool {
        guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize, size == LegacyRuntimePin.bytes,
              let data = try? Data(contentsOf: url) else { return false }
        return hash(data) == LegacyRuntimePin.sha256
    }
    /// All writes stay inside real prefix directories, never through symlinks.
    static func destination(_ relative: String, prefix: URL) throws -> URL {
        let base = prefix.standardizedFileURL.resolvingSymlinksInPath()
        var current = base
        for part in relative.split(separator: "/") {
            guard part != ".", part != "..", !part.contains(":"), !part.contains("\\") else { throw LegacyRuntimePE.invalid }
            current.appendPathComponent(String(part))
            if (try? current.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true {
                throw LegacyRuntimeError.message("The runtime destination contains a symbolic link. Restore the Windows environment before installing.")
            }
        }
        guard LegacyRuntimeDependency.inside(current, base) else { throw LegacyRuntimePE.invalid }
        return current
    }
    static func queue(package: URL, prefix: URL) throws {
        guard verifiedPackage(package) else { throw LegacyRuntimeError.message("Microsoft's runtime download did not match the expected checksum.") }
        let target = try destination("drive_c/" + LegacyRuntimePin.relativePackage, prefix: prefix)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !verifiedPackage(target) { try Data(contentsOf: package).write(to: target, options: .atomic) }
        let pending = try destination("drive_c/madeira-runtime/pending-mfc42", prefix: prefix)
        try LegacyRuntimePin.sha256.write(to: pending, atomically: true, encoding: .utf8)
    }
    static func importDLL(_ source: URL, prefix: URL, symbols: Set<String>) throws {
        let pe = try LegacyRuntimePE(url: source)
        let exports = try pe.mfc42Exports()
        guard symbols.isSubset(of: exports) else { throw LegacyRuntimeError.message("This DLL lacks MFC42 functions required by the application.") }
        let target = try destination("drive_c/windows/syswow64/mfc42.dll", prefix: prefix)
        try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = Data(pe.bytes)
        if let old = LegacyRuntimeDependency.matching("mfc42.dll", in: target.deletingLastPathComponent()) {
            guard try Data(contentsOf: old) == data else {
                throw LegacyRuntimeError.message("A different MFC42.DLL is already installed. It was kept; move it aside before importing a replacement.")
            }
            return
        }
        let stage = target.deletingLastPathComponent().appendingPathComponent(".mfc42-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: stage) }
        try data.write(to: stage, options: .atomic)
        try FileManager.default.moveItem(at: stage, to: target)
    }
}

/// The installer runs in the SAME Wine session as the original launch, before
/// any game/client code. Its child receives the original argv without cmd /c.
enum LegacyRuntimeLaunch {
    static func apply(prefix: URL) throws {
        let pending = try LegacyRuntimeStorage.destination("drive_c/madeira-runtime/pending-mfc42", prefix: prefix)
        guard (try? String(contentsOf: pending, encoding: .utf8)) == LegacyRuntimePin.sha256 else { return }
        let destination = try LegacyRuntimeStorage.destination("drive_c/windows/syswow64/mfc42.dll", prefix: prefix)
        let existing = LegacyRuntimeDependency.matching("mfc42.dll", in: destination.deletingLastPathComponent()) ?? destination
        if let pe = try? LegacyRuntimePE(url: existing), (try? pe.mfc42Exports()) != nil {
            try FileManager.default.removeItem(at: pending)
            return
        }
        let package = try LegacyRuntimeStorage.destination("drive_c/" + LegacyRuntimePin.relativePackage, prefix: prefix)
        guard LegacyRuntimeStorage.verifiedPackage(package), let exe = getenv("MADEIRA_EXE").map({ String(cString: $0) }), !exe.isEmpty,
              !exe.contains("\""), !exe.contains("\0") else {
            throw LegacyRuntimeError.message("The pending runtime or launch command could not be verified. Download the runtime again in Settings.")
        }
        let args = getenv("MADEIRA_ARGS").map { String(cString: $0) } ?? ""
        let drive = prefix.appendingPathComponent("drive_c")
        let path = exe.lowercased().hasPrefix("c:\\") ? drive.appendingPathComponent(String(exe.dropFirst(3)).replacingOccurrences(of: "\\", with: "/")) : nil
        let bits = path.flatMap { try? LegacyRuntimePE(url: $0).bits } ?? 64
        let farm = bits == 32 ? "i386-windows" : "arm64ec-windows"
        guard FileManager.default.fileExists(atPath: Bundle.main.bundleURL.appendingPathComponent(farm + "/" + LegacyRuntimePin.helper).path) else {
            throw LegacyRuntimeError.message("This build does not contain the runtime installer. Install a newer iDeck build or import MFC42.DLL manually.")
        }
        let report = try LegacyRuntimeStorage.destination("drive_c/madeira-runtime/result.txt", prefix: prefix)
        if FileManager.default.fileExists(atPath: report.path) { try FileManager.default.removeItem(at: report) }
        let wrapped = LegacyRuntimePin.wrapped(executable: exe, arguments: args, bits: bits)
        guard wrapped.args.utf8.count < 4096 else { throw LegacyRuntimeError.message("The launch arguments are too long to prepare the runtime. Import MFC42.DLL manually first.") }
        let chosen = getenv("MADEIRA_WORKDIR").map { String(cString: $0) }
        if let folder = LegacyRuntimePin.workingDirectory(executable: exe, chosen: chosen) { setenv("MADEIRA_WORKDIR", folder, 1) }
        setenv("MADEIRA_EXE", wrapped.exe, 1); setenv("MADEIRA_ARGS", wrapped.args, 1)
        fputs("[legacy-runtime] verified package; installing before original launch (\(bits)-bit host)\n", stderr)
    }
}

@MainActor final class LegacyRuntimeModel: ObservableObject {
    static let shared = LegacyRuntimeModel()
    @Published var presented = false
    @Published private(set) var busy = false
    @Published private(set) var status = ""
    @Published var error: String?
    @Published var authorized = false
    private var prefix = MadeiraDock.prefix
    private var need: LegacyRuntimeDependency.Need?
    private var resume: (() -> Void)?
    private var afterDismiss: (() -> Void)?
    private var sheetVisible = false
    private var operation: Task<Void, Never>?
    private var generation = UUID()
    private var checkedExecutable: URL?
    private var logStart: UInt64 = 0
    var requested: Bool { need != nil }
    var accepted: Bool { UserDefaults.standard.string(forKey: "legacy-runtime-mfc42-consent") == LegacyRuntimePin.sha256 }
    var installed: Bool {
        guard let file = LegacyRuntimeDependency.matching("mfc42.dll", in: prefix.appendingPathComponent("drive_c/windows/syswow64")) else { return false }
        return (try? LegacyRuntimePE(url: file).mfc42Exports()) != nil
    }
    var importerSummary: String { need?.importers.prefix(4).joined(separator: ", ") ?? "" }
    var limitedScan: Bool { need?.incomplete == true }

    /// Call before JIT/session startup. The continuation runs once, after any
    /// consent/download sheet has closed. Cancelling never launches the game.
    func check(executable: URL, prefix: URL, proceed: @escaping () -> Void) {
        guard !busy, !presented, wine_process_is_running() == 0, wineserver_is_running() == 0 else { return }
        self.prefix = prefix; error = nil; resume = proceed; need = nil
        checkedExecutable = executable
        logStart = UInt64((try? LogStore.shared.runtimeLogURL.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0)
        let observed = (UserDefaults.standard.stringArray(forKey: "legacy-runtime-mfc42-observed") ?? []).contains(executable.path)
        busy = true; status = "Checking Windows runtime dependencies…"
        generation = UUID()
        let current = generation
        operation = Task {
            do {
                let result = try await Task.detached(priority: .userInitiated) {
                    try LegacyRuntimeDependency.scan(executable: executable, drive: prefix.appendingPathComponent("drive_c"), prefix: prefix)
                }.value
                guard generation == current else { return }
                try Task.checkCancellation()
                busy = false
                let forced = observed && !installed ? LegacyRuntimeDependency.Need(symbols: [], importers: [executable.lastPathComponent], incomplete: true) : nil
                guard let result = result ?? forced else { let action = resume; resume = nil; action?(); return }
                need = result; authorized = accepted; status = "32-bit MFC42 is missing."
                presented = true
                if accepted { download() }
            } catch is CancellationError { if generation == current { busy = false; resume = nil } }
            catch {
                guard generation == current else { return }
                busy = false; resume = nil; self.error = error.localizedDescription; LibraryModel.shared.error = error.localizedDescription
            }
        }
    }
    func settings() {
        guard !busy, !presented else { return }
        prefix = SteamUIExperiment.runtimePrefix; need = nil; resume = nil; error = nil
        authorized = accepted; status = installed ? "32-bit MFC42 is installed." : "32-bit MFC42 is not installed."
        presented = true
    }
    func download() {
        guard !busy, authorized || accepted, wine_process_is_running() == 0, wineserver_is_running() == 0 else { return }
        UserDefaults.standard.set(LegacyRuntimePin.sha256, forKey: "legacy-runtime-mfc42-consent")
        busy = true; error = nil; status = "Downloading MFC42 from Microsoft…"
        let prefix = self.prefix
        generation = UUID()
        let current = generation
        operation = Task {
            do {
                let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appendingPathComponent("LegacyRuntimes")
                try FileManager.default.createDirectory(at: cache, withIntermediateDirectories: true)
                let archive = cache.appendingPathComponent("VC6RedistSetup_deu.exe")
                if !LegacyRuntimeStorage.verifiedPackage(archive) {
                    let config = URLSessionConfiguration.ephemeral
                    config.timeoutIntervalForRequest = 45; config.timeoutIntervalForResource = 180
                    config.httpCookieStorage = nil; config.urlCredentialStorage = nil
                    NetworkProxySettings.shared.apply(to: config)
                    let session = URLSession(configuration: config, delegate: LegacyRuntimeRedirects(), delegateQueue: nil)
                    defer { session.invalidateAndCancel() }
                    let (temp, response) = try await session.download(from: LegacyRuntimePin.url)
                    defer { try? FileManager.default.removeItem(at: temp) }
                    guard generation == current else { return }
                    try Task.checkCancellation()
                    guard let http = response as? HTTPURLResponse, http.statusCode == 200, LegacyRuntimePin.allowed(http.url),
                          LegacyRuntimeStorage.verifiedPackage(temp) else {
                        throw LegacyRuntimeError.message("Microsoft's runtime download could not be verified. Retry, or import your own 32-bit MFC42.DLL.")
                    }
                    try Data(contentsOf: temp).write(to: archive, options: .atomic)
                }
                try Task.checkCancellation()
                guard wine_process_is_running() == 0, wineserver_is_running() == 0 else { throw LegacyRuntimeError.message("Close the running session before preparing a runtime.") }
                status = "Preparing the runtime for installation…"
                try LegacyRuntimeStorage.queue(package: archive, prefix: prefix)
                busy = false; status = "MFC42 will be installed before the next program starts."
                finishPreparation()
            } catch is CancellationError { if generation == current { busy = false; status = "Download cancelled." } }
            catch { if generation == current { busy = false; self.error = error.localizedDescription } }
        }
    }
    func importDLL(_ url: URL) {
        guard !busy, wine_process_is_running() == 0, wineserver_is_running() == 0 else { return }
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        do {
            try LegacyRuntimeStorage.importDLL(url, prefix: prefix, symbols: need?.symbols ?? [])
            error = nil; status = "32-bit MFC42 is installed."
            finishPreparation()
        } catch { self.error = error.localizedDescription }
    }
    func cancel() {
        generation = UUID(); operation?.cancel(); busy = false; resume = nil; afterDismiss = nil; presented = false
    }
    func sheetShown() { sheetVisible = true }
    private func finishPreparation() {
        guard let action = resume else { return }
        resume = nil
        if sheetVisible { afterDismiss = action; presented = false }
        else { presented = false; action() }
    }
    func dismissed() {
        sheetVisible = false
        let action = afterDismiss; afterDismiss = nil
        if action == nil { generation = UUID(); operation?.cancel(); resume = nil; busy = false }
        action?()
    }
    func sessionEnded() {
        let report = prefix.appendingPathComponent("drive_c/madeira-runtime/result.txt")
        if let result = try? String(contentsOf: report, encoding: .utf8) {
            try? FileManager.default.removeItem(at: report)
            if result.trimmingCharacters(in: .whitespacesAndNewlines) == "ok" {
                try? FileManager.default.removeItem(at: prefix.appendingPathComponent("drive_c/madeira-runtime/pending-mfc42"))
            } else {
                LibraryModel.shared.error = "MFC42 could not be installed (\(result.trimmingCharacters(in: .whitespacesAndNewlines))). Existing files were kept. Open Settings › Windows runtimes to retry or import the DLL. Restart iDeck before launching again."
            }
        }
        // Static scans cannot predict arbitrary LoadLibrary paths. Remember a
        // confirmed loader failure for the next launch; Wine cannot be safely
        // restarted inside this same app process to retry it immediately.
        guard let executable = checkedExecutable, !installed,
              let handle = try? FileHandle(forReadingFrom: LogStore.shared.runtimeLogURL) else { return }
        defer { try? handle.close() }
        let end = (try? handle.seekToEnd()) ?? 0
        try? handle.seek(toOffset: max(logStart, end > 262144 ? end - 262144 : 0))
        guard let data = try? handle.readToEnd() else { return }
        let direct32 = (try? LegacyRuntimePE(url: executable).bits) == 32
        let missing = String(decoding: data, as: UTF8.self).split(separator: "\n").contains { line in
            let lower = line.lowercased()
            guard lower.contains("err:module:import_dll"), lower.contains("library mfc42.dll"), lower.contains("not found") else { return false }
            if direct32 { return true }
            let original = String(line)
            guard let start = original.range(of: "by l\"", options: .caseInsensitive), let stop = original[start.upperBound...].firstIndex(of: "\"") else { return false }
            let path = String(original[start.upperBound..<stop]).replacingOccurrences(of: "\\\\", with: "\\")
            guard path.lowercased().hasPrefix("c:\\") else { return false }
            let importer = prefix.appendingPathComponent("drive_c/" + String(path.dropFirst(3)).replacingOccurrences(of: "\\", with: "/"))
            return LegacyRuntimeDependency.inside(importer, prefix.appendingPathComponent("drive_c")) && (try? LegacyRuntimePE(url: importer).bits) == 32
        }
        guard missing else { return }
        var known = UserDefaults.standard.stringArray(forKey: "legacy-runtime-mfc42-observed") ?? []
        if !known.contains(executable.path) { known.append(executable.path) }
        UserDefaults.standard.set(Array(known.suffix(128)), forKey: "legacy-runtime-mfc42-observed")
        LibraryModel.shared.error = "The Windows loader reported missing 32-bit MFC42.DLL. Restart iDeck and launch this program again to download the runtime, or import it in Settings › Windows runtimes."
    }
}

struct LegacyRuntimeSheet: View {
    @ObservedObject private var model = LegacyRuntimeModel.shared
    @State private var importing = false
    var body: some View {
        NavigationStack {
            Form {
                Section("Microsoft MFC42 · 32-bit") {
                    if model.busy { ProgressView(model.status) } else { Text(model.status) }
                    if !model.importerSummary.isEmpty { Text("Referenced by: " + model.importerSummary).font(.footnote).foregroundStyle(.secondary) }
                    if model.limitedScan { Text("The scan reached its limit. Other dependencies may still be needed.").font(.footnote).foregroundStyle(.secondary) }
                    if let error = model.error { Text(error).foregroundStyle(.red) }
                }
                if !model.installed {
                    Section {
                        Text("Download the VC6 runtime package directly from Microsoft (1.8 MB). Only its unmodified MFC42.DLL will be installed in this Windows environment, where other 32-bit programs can also use it.")
                        Text("This older package has German system messages. It is not included in the iDeck download.").font(.footnote).foregroundStyle(.secondary)
                        DisclosureGroup("Microsoft's supplemental license (original German)") {
                            Text(LegacyRuntimeLicense.original).font(.footnote).textSelection(.enabled)
                        }
                        Text("The supplement refers to your original Visual Studio / Visual C++ license. Downloading does not grant additional rights or establish permission for every platform.").font(.footnote).foregroundStyle(.secondary)
                        if !model.accepted {
                            Toggle("I accept the supplement and confirm I am authorized under the applicable Microsoft license.", isOn: $model.authorized)
                        }
                        Button(model.accepted ? "Download from Microsoft" : "Agree and Download") { model.download() }
                            .disabled(model.busy || (!model.authorized && !model.accepted))
                    } header: { Text("Download") }
                }
                Section {
                    Button("Import MFC42.DLL…") { importing = true }.disabled(model.busy)
                    Text("You can supply a compatible 32-bit DLL from software you are authorized to use. Existing different files are kept.").font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Windows runtimes").navigationBarTitleDisplayMode(.inline)
            .onAppear { model.sheetShown() }
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button(model.busy ? "Cancel" : "Done") { model.cancel() } } }
            .interactiveDismissDisabled(model.busy)
            .fileImporter(isPresented: $importing, allowedContentTypes: [.item]) { result in
                switch result {
                case .success(let url): model.importDLL(url)
                case .failure(let error): model.error = error.localizedDescription
                }
            }
        }
    }
}

struct LegacyRuntimeSettingsSection: View {
    var body: some View {
        Section("Windows runtimes") {
            Button("Manage Windows runtimes…") { LegacyRuntimeModel.shared.settings() }
            Text("Missing MFC42 dependencies are checked before launch. Download from Microsoft or import your own runtime.").font(.footnote).foregroundStyle(.secondary)
        }
    }
}

// Microsoft-authored license text extracted from the signed, hash-pinned
// redistributable's RCDATA/LICENSE. It retains Microsoft's original terms;
// the SPDX identifier above applies to our code, not to this quotation.
enum LegacyRuntimeLicense {
    static let original = """
    Das Visual C++ 6.0 VCREDIST.EXE Pack enthält aktualisierte Versionen eines oder mehrerer der unten aufgeführten Softwareprodukte. Dieses Dokument dient als Nachtrag ("Nachtrag") zu dem Microsoft-Endbenutzer-Lizenzvertrag ("EULA"), den Sie mit Version 6.0 oder höher eines der unten aufgeführten Microsoft-Produkte erhalten haben. Wenn in diesem Nachtrag nicht anders bestimmt, wird das VCREDIST.EXE Pack unter den gleichen Bestimmungen wie im EULA lizenziert.

    Visual Studio
    Visual C++

    1. Falls Sie sich nicht damit einverstanden erklären, durch die Bestimmungen des EULAs und dieses Nachtrags gebunden zu sein, sind Sie nicht berechtigt, das VCREDIST.EXE Pack zu verwenden.

    2. Das VCREDIST.EXE Pack und seine gesamten Inhalte sind weitervertreibbar. Ihre Verwendung solcher Dateien unterliegt allen Bestimmungen des EULAs, die sich auf "Weitervertreibbare Dateien" (wie im EULA definiert) beziehen.

    3. Microsoft gewährt Ihnen außerdem das nicht ausschließliche Recht, das VCREDIST.EXE Pack und seine gesamten Inhalte zu kopieren und an jeden ordnungsgemäß lizenzierten Endbenutzer eines der oben aufgeführten Produkte weiterzugeben.
    """
}
