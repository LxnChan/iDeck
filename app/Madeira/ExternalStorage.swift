// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation
import Combine
import UIKit
import Darwin

/// Security scopes live on the serial disk queue until an explicit safe
/// disconnect. A temporarily missing disk never discards its games or bookmark.
@MainActor final class ExternalStorage: ObservableObject {
    static let shared = ExternalStorage()
    struct Record: Codable, Identifiable {
        var id: UUID
        var name: String
        var bookmark: Data
        var lastPath: String
        var enabled: Bool
        var games: [DockGame]
        var relativeRoot: String { DrivePaths.externalDirectory + "/" + id.uuidString }
    }
    struct Status: Equatable {
        var ready = false
        var message = "Checking external folder…"
        var freeBytes: Int64?
    }
    enum CheckFeedback: Equatable {
        case idle, checking
        case success(Date)
        case failure(String)
    }
    enum ConnectionIndicator: Equatable {
        case connected, partial, unavailable
        var label: String {
            switch self {
            case .connected: return "All external folders are connected"
            case .partial: return "Some external folders are unavailable"
            case .unavailable: return "All external folders are unavailable"
            }
        }
    }
    private struct Document: Codable { var version = 1; var records: [Record] }
    @Published private(set) var records: [Record] = []
    @Published private(set) var statuses: [UUID: Status] = [:]
    @Published private(set) var busy = false
    @Published private(set) var checkFeedback: CheckFeedback = .idle
    @Published var error: String?
    private var readOnly = false
    private var timer: Timer?
    private var checking = false
    private var pendingWriteCheck = false
    private var pendingReportedCheck = false
    private var accesses = 0
    private var generation: UInt64 = 0
    private var appliedGeneration: UInt64 = 0
    private let queue = DispatchQueue(label: "com.ideck.external-storage", qos: .utility)
    private let engine = Engine()
    private var observers: [NSObjectProtocol] = []
    private var file: URL { LibraryModel.documents.appendingPathComponent("ideck-external-storage.json") }
    var canChange: Bool {
        !busy && !checking && accesses == 0 && LibraryModel.shared.current == nil && !LibraryModel.shared.launching && LibraryModel.shared.startingJIT == nil &&
        wine_process_is_running() == 0 && wineserver_is_running() == 0 && !SteamOwnedLibrary.shared.storageBusy
    }
    var offlineGames: [DockGame] {
        records.filter { statuses[$0.id]?.ready != true }.flatMap(\.games)
    }
    var connectionIndicator: ConnectionIndicator? {
        let enabled = records.filter(\.enabled)
        guard !enabled.isEmpty else { return nil }
        let connected = enabled.filter { statuses[$0.id]?.ready == true }.count
        if connected == 0 { return .unavailable }
        return connected == enabled.count ? .connected : .partial
    }
    var downloadLibrary: String {
        get { UserDefaults.standard.string(forKey: "ideck.download-library") ?? SteamInstallPaths.libraryRelative }
        set { UserDefaults.standard.set(newValue, forKey: "ideck.download-library"); objectWillChange.send() }
    }
    func pendingLibrary(_ appID: Int) -> String? { UserDefaults.standard.string(forKey: "ideck.install-library.\(appID)") }
    var pendingInstalls: [Int: String] {
        let stored = UserDefaults.standard.dictionary(forKey: "ideck.pending-external-installs") as? [String: String] ?? [:]
        return Dictionary(stored.compactMap { key, library in
            guard let id = Int(key), id > 0, DrivePaths.mountID(library) != nil else { return nil }
            return (id, library)
        }, uniquingKeysWith: { first, _ in first })
    }
    func pinLibrary(_ library: String, appID: Int) {
        UserDefaults.standard.set(library, forKey: "ideck.install-library.\(appID)")
        if DrivePaths.mountID(library) != nil {
            var pending = pendingInstalls; pending[appID] = library
            UserDefaults.standard.set(Dictionary(uniqueKeysWithValues: pending.map { (String($0.key), $0.value) }), forKey: "ideck.pending-external-installs")
        }
        objectWillChange.send()
    }
    func forgetLibrary(_ appID: Int) {
        UserDefaults.standard.removeObject(forKey: "ideck.install-library.\(appID)")
        var pending = pendingInstalls; pending.removeValue(forKey: appID)
        UserDefaults.standard.set(Dictionary(uniqueKeysWithValues: pending.map { (String($0.key), $0.value) }), forKey: "ideck.pending-external-installs")
        objectWillChange.send()
    }
    private init() {
        if FileManager.default.fileExists(atPath: file.path) {
            do {
                let data = try Data(contentsOf: file)
                guard data.count < 4 << 20 else { throw DrivePaths.Failure(message: "External storage settings are too large.") }
                let doc = try JSONDecoder().decode(Document.self, from: data)
                guard doc.version == 1, Set(doc.records.map(\.id)).count == doc.records.count, doc.records.count <= 16 else {
                    throw DrivePaths.Failure(message: "External storage settings have an unsupported format.")
                }
                records = doc.records
                publishPaths()
            } catch { readOnly = true; self.error = "External storage settings were preserved: " + error.localizedDescription }
        }
    }
    func start() {
        guard timer == nil else { return }
        refresh(write: true)
        let timer = Timer(timeInterval: 1.5, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard UIApplication.shared.applicationState == .active else { return }
                self?.refresh()
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        observers.append(NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh(write: true) }
        })
    }
    private func publishPaths() {
        DrivePaths.shared.replace(records.map { record in
            let status = statuses[record.id] ?? Status()
            return .init(id: record.id, url: URL(fileURLWithPath: record.lastPath, isDirectory: true), available: record.enabled && status.ready,
                         problem: record.enabled ? status.message : "External folder is safely disconnected. Reconnect it in Settings.")
        })
    }
    @discardableResult private func save(_ next: [Record]) -> Bool {
        guard !readOnly else { error = "Repair the original external storage settings before changing them."; return false }
        do {
            try JSONEncoder().encode(Document(records: next)).write(to: file, options: .atomic)
            records = next
            return true
        } catch { self.error = "Could not save external storage settings: " + error.localizedDescription; return false }
    }
    func checkConnectedFolders() {
        checkFeedback = .checking
        refresh(write: true, report: true)
    }
    func refresh(write: Bool = false, report: Bool = false) {
        // Keep startup, foreground, and explicit write checks when a poll or
        // storage change is already in flight. Routine polls can be coalesced.
        pendingWriteCheck = pendingWriteCheck || write
        pendingReportedCheck = pendingReportedCheck || report
        guard !checking, !busy else { return }
        let write = pendingWriteCheck, report = pendingReportedCheck
        pendingWriteCheck = false; pendingReportedCheck = false
        guard !records.isEmpty else {
            if report { checkFeedback = .failure("Add an external folder before checking.") }
            return
        }
        checking = true
        generation += 1
        let request = generation
        let snapshot = records, drive = LibraryModel.drive, allowRelink = canMutateRuntime
        queue.async { [engine] in
            let results = engine.check(snapshot, drive: drive, write: write, allowRelink: allowRelink)
            DispatchQueue.main.async { [self] in
                checking = false
                defer { drainPendingCheck() }
                guard request >= appliedGeneration else {
                    pendingWriteCheck = pendingWriteCheck || write
                    pendingReportedCheck = pendingReportedCheck || report
                    return
                }
                appliedGeneration = request
                let previous = statuses
                var next = records
                var changed = false
                for result in results {
                    statuses[result.record.id] = result.status
                    if let index = next.firstIndex(where: { $0.id == result.record.id }),
                       next[index].lastPath != result.record.lastPath || next[index].bookmark != result.record.bookmark {
                        next[index] = result.record; changed = true
                    }
                }
                if changed, !save(next) {
                    for result in results where result.status.ready {
                        statuses[result.record.id] = Status(message: "The reconnected location could not be saved. Check external storage settings.")
                    }
                }
                publishPaths()
                if report {
                    let enabled = records.filter(\.enabled)
                    if enabled.isEmpty {
                        checkFeedback = .failure("Reconnect an external folder before checking.")
                    } else if enabled.allSatisfy({ statuses[$0.id]?.ready == true }) {
                        checkFeedback = .success(Date())
                    } else {
                        checkFeedback = .failure("Some folders are unavailable or not writable. See their status above.")
                    }
                } else if records.contains(where: { $0.enabled && statuses[$0.id]?.ready != true }) {
                    invalidateCheckSuccess()
                }
                // Capacity can change on every poll. Only availability or path
                // changes need another library scan and recovery notification.
                if changed || results.contains(where: {
                    previous[$0.record.id]?.ready != $0.status.ready || previous[$0.record.id]?.message != $0.status.message
                }) {
                    SteamOwnedLibrary.shared.externalStorageChanged()
                    SteamGamesModel.shared.refresh()
                }
            }
        }
    }
    private func drainPendingCheck() {
        if pendingWriteCheck || pendingReportedCheck { refresh() }
    }
    private func invalidateCheckSuccess() {
        if case .success = checkFeedback { checkFeedback = .idle }
    }
    private var canMutateRuntime: Bool {
        LibraryModel.shared.current == nil && !LibraryModel.shared.launching && LibraryModel.shared.startingJIT == nil &&
        wine_process_is_running() == 0 && wineserver_is_running() == 0 && !SteamOwnedLibrary.shared.storageBusy
    }
    /// A revoke/delete/rename event stops downloads before a potentially slow
    /// filesystem probe. Polling remains the fallback when no event arrives.
    private func directoryLost(_ id: UUID) {
        guard records.contains(where: { $0.id == id }) else { return }
        generation += 1; appliedGeneration = generation
        invalidateCheckSuccess()
        statuses[id] = Status(message: "External folder disconnected or moved. Reconnect it before continuing.")
        publishPaths()
        SteamOwnedLibrary.shared.externalStorageChanged()
        SteamGamesModel.shared.refresh()
        refresh()
    }
    /// A final uncached write check before handing storage to Wine, Cloud, or a
    /// downloader. The caller rechecks after any intervening JIT/network wait.
    func requireAvailable(_ relative: String, write: Bool = true) async throws {
        guard let id = DrivePaths.mountID(relative) else { return }
        guard !busy, !readOnly, let record = records.first(where: { $0.id == id }), record.enabled else {
            throw DrivePaths.Failure(message: "External folder is disconnected or unavailable. Check Settings › External storage.")
        }
        let drive = LibraryModel.drive
        accesses += 1
        generation += 1
        let request = generation
        defer { accesses -= 1 }
        let result = await withCheckedContinuation { continuation in
            queue.async { [engine] in
                continuation.resume(returning: engine.check([record], drive: drive, write: write, allowRelink: false)[0])
            }
        }
        if request >= appliedGeneration {
            appliedGeneration = request
            statuses[id] = result.status
            if !result.status.ready { invalidateCheckSuccess() }
            publishPaths()
        }
        guard result.status.ready else { throw DrivePaths.Failure(message: result.status.message) }
        _ = try DrivePaths.shared.resolve(relative, drive: drive, mustExist: false)
    }
    func add(_ url: URL) {
        guard canChange, !readOnly else { error = "Stop games, downloads, and save sync before changing external storage."; return }
        busy = true
        invalidateCheckSuccess()
        let snapshot = records, drive = LibraryModel.drive
        queue.async { [engine] in
            let result = Result { try engine.add(url, records: snapshot, drive: drive) }
            DispatchQueue.main.async { [self] in
                busy = false
                defer { drainPendingCheck() }
                switch result {
                case .success(let record):
                    var next = records.filter { $0.id != record.id }; next.append(record)
                    if save(next) { statuses[record.id] = Status(); publishPaths(); refresh(write: true) }
                    else {
                        statuses[record.id] = Status(message: "Settings could not be saved. Reconnect this folder.")
                        publishPaths()
                        queue.async { [engine] in engine.disconnect(record, drive: drive) }
                    }
                case .failure(let failure): error = failure.localizedDescription
                }
            }
        }
    }
    func reconnect(_ id: UUID) {
        guard canChange, let index = records.firstIndex(where: { $0.id == id }) else { return }
        var next = records; next[index].enabled = true
        invalidateCheckSuccess()
        if save(next) { statuses[id] = Status(); publishPaths(); refresh(write: true) }
    }
    func disconnect(_ id: UUID, remove: Bool = false) {
        guard canChange, let record = records.first(where: { $0.id == id }) else {
            error = "Stop games, downloads, and save sync before disconnecting storage."; return
        }
        var next = records
        if remove { next.removeAll { $0.id == id } } else if let index = next.firstIndex(where: { $0.id == id }) { next[index].enabled = false }
        guard save(next) else { return }
        invalidateCheckSuccess()
        statuses[id] = Status(message: "Safely disconnected")
        publishPaths()
        busy = true
        let drive = LibraryModel.drive
        queue.async { [engine] in
            engine.disconnect(record, drive: drive)
            DispatchQueue.main.async { [self] in
                busy = false
                drainPendingCheck()
                SteamGamesModel.shared.refresh()
            }
        }
    }
    /// Persist only verified, live scans; an unplugged disk is never uninstalled.
    func remember(_ games: [DockGame], scanned: Set<String>) {
        var next = records, changed = false
        for i in next.indices where statuses[next[i].id]?.ready == true {
            let library = next[i].relativeRoot + "/steamapps"
            guard scanned.contains(library.lowercased()) else {
                if !next[i].games.isEmpty {
                    statuses[next[i].id] = Status(message: "External game library could not be read. Reconnect the drive.")
                }
                continue
            }
            let found = games.filter { $0.library.caseInsensitiveCompare(library) == .orderedSame }
            if next[i].games != found { next[i].games = found; changed = true }
        }
        if changed { _ = save(next) }
        publishPaths()
    }

    private final class Engine: @unchecked Sendable {
        struct ResultRow { var record: Record; var status: Status }
        private var scopes: [UUID: URL] = [:]
        private var ready = Set<UUID>()
        private var failures: [UUID: String] = [:]
        private var watchers: [UUID: DispatchSourceFileSystemObject] = [:]
        private let events = DispatchQueue(label: "com.ideck.external-storage.events", qos: .utility)
        func add(_ source: URL, records: [Record], drive: URL) throws -> Record {
            guard source.startAccessingSecurityScopedResource() else { throw DrivePaths.Failure(message: "Access to the selected folder was denied.") }
            var retained = false
            defer { if !retained { source.stopAccessingSecurityScopedResource() } }
            var result: Result<Record, Error>?
            var coordinationError: NSError?
            NSFileCoordinator(filePresenter: nil).coordinate(writingItemAt: source, options: .forMerging, error: &coordinationError) { root in
                result = Result {
                    let root = root.resolvingSymlinksInPath().standardizedFileURL
                    let values = try root.resourceValues(forKeys: [.volumeIsInternalKey])
                    guard values.volumeIsInternal != true, !DrivePaths.within(root, LibraryModel.documents.resolvingSymlinksInPath()) else {
                        throw DrivePaths.Failure(message: "Choose a folder on a connected external drive.")
                    }
                    for record in records where record.lastPath != root.path {
                        let other = URL(fileURLWithPath: record.lastPath)
                        if DrivePaths.within(root, other) || DrivePaths.within(other, root) {
                            throw DrivePaths.Failure(message: "This folder overlaps another mapping. Choose a separate folder.")
                        }
                    }
                    try ExternalStorageProbe.check(root, write: true)
                    let id = try ExternalStorageProbe.identify(root)
                    guard records.count < 16 || records.contains(where: { $0.id == id }) else {
                        throw DrivePaths.Failure(message: "At most 16 external folders can be registered.")
                    }
                    let bookmark = try source.bookmarkData(options: .minimalBookmark, includingResourceValuesForKeys: nil, relativeTo: nil)
                    let record = Record(id: id, name: source.lastPathComponent, bookmark: bookmark, lastPath: root.path, enabled: true,
                                        games: records.first(where: { $0.id == id })?.games ?? [])
                    try self.link(record, root: root, drive: drive)
                    return record
                }
            }
            if let coordinationError { throw coordinationError }
            guard let result else { throw DrivePaths.Failure(message: "The selected folder could not be coordinated.") }
            let record = try result.get()
            scopes[record.id]?.stopAccessingSecurityScopedResource()
            scopes[record.id] = source
            retained = true
            return record
        }
        func check(_ records: [Record], drive: URL, write: Bool, allowRelink: Bool) -> [ResultRow] {
            records.map { original in
                var record = original
                guard record.enabled else { return ResultRow(record: record, status: Status(message: "Safely disconnected")) }
                var stage = "bookmark"
                do {
                    if scopes[record.id] == nil {
                        var stale = false
                        let source = try URL(resolvingBookmarkData: record.bookmark, options: [.withoutUI], relativeTo: nil, bookmarkDataIsStale: &stale)
                        guard source.startAccessingSecurityScopedResource() else { throw DrivePaths.Failure(message: "Folder permission expired. Select the external folder again.") }
                        scopes[record.id] = source
                        if stale { record.bookmark = try source.bookmarkData(options: .minimalBookmark, includingResourceValuesForKeys: nil, relativeTo: nil) }
                    }
                    guard let source = scopes[record.id] else { throw DrivePaths.Failure(message: "External folder access is unavailable.") }
                    let root = URL(fileURLWithPath: source.path, isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
                    stage = "probe"
                    do { try ExternalStorageProbe.check(root, expected: record.id, write: write || !ready.contains(record.id)) }
                    catch {
                        // iOS may give the same bookmark a different path on reinsert.
                        // Keep the old scope while a session owns file handles.
                        if allowRelink { scopes.removeValue(forKey: record.id)?.stopAccessingSecurityScopedResource() }
                        throw error
                    }
                    stage = "mapping"
                    if root.path != record.lastPath, !allowRelink { throw DrivePaths.Failure(message: "External drive reconnected at a new location. Stop the current operation before reconnecting it.") }
                    if allowRelink { try link(record, root: root, drive: drive) }
                    else {
                        let path = drive.appendingPathComponent(record.relativeRoot).path
                        guard (try? FileManager.default.destinationOfSymbolicLink(atPath: path)) == root.path else {
                            throw DrivePaths.Failure(message: "External mapping is not ready. Reconnect it in Settings before starting.")
                        }
                    }
                    record.lastPath = root.path
                    if ready.insert(record.id).inserted {
                        SteamLog.event("[external-storage] connected mapping=\(record.id.uuidString)")
                    }
                    failures.removeValue(forKey: record.id)
                    watch(record.id, root: root)
                    return ResultRow(record: record, status: Status(ready: true, message: "Connected · writable", freeBytes: StorageCapacity.read(at: root).available))
                } catch {
                    ready.remove(record.id)
                    watchers.removeValue(forKey: record.id)?.cancel()
                    let reason = "stage=\(stage) reason=\(DrivePaths.diagnostic(error))"
                    if failures[record.id] != reason {
                        failures[record.id] = reason
                        SteamLog.event("[external-storage] unavailable mapping=\(record.id.uuidString) \(reason)")
                    }
                    return ResultRow(record: record, status: Status(message: "External folder unavailable: " + error.localizedDescription))
                }
            }
        }
        private func link(_ record: Record, root: URL, drive: URL) throws {
            let fm = FileManager.default
            let parent = drive.appendingPathComponent(DrivePaths.externalDirectory, isDirectory: true)
            try fm.createDirectory(at: parent, withIntermediateDirectories: true)
            guard parent.resolvingSymlinksInPath().path == parent.standardizedFileURL.path else { throw DrivePaths.Failure(message: "The External mapping folder was replaced by a link.") }
            let path = parent.appendingPathComponent(record.id.uuidString).path
            if let target = try? fm.destinationOfSymbolicLink(atPath: path) {
                if target == root.path { return }
                guard target == record.lastPath else { throw DrivePaths.Failure(message: "The mapping was changed outside iDeck. Restore it before reconnecting.") }
                try fm.removeItem(atPath: path) // remove this link only, never its target
            }
            try fm.createSymbolicLink(atPath: path, withDestinationPath: root.path)
        }
        private func watch(_ id: UUID, root: URL) {
            guard watchers[id] == nil else { return }
            let fd = open(root.path, O_EVTONLY | O_CLOEXEC)
            guard fd >= 0 else { return }
            let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.delete, .rename, .revoke], queue: events)
            source.setEventHandler { DispatchQueue.main.async { ExternalStorage.shared.directoryLost(id) } }
            source.setCancelHandler { close(fd) }
            watchers[id] = source
            source.resume()
        }
        func disconnect(_ record: Record, drive: URL) {
            let link = drive.appendingPathComponent(record.relativeRoot)
            if (try? FileManager.default.destinationOfSymbolicLink(atPath: link.path)) == record.lastPath {
                try? FileManager.default.removeItem(at: link)
            }
            watchers.removeValue(forKey: record.id)?.cancel()
            scopes.removeValue(forKey: record.id)?.stopAccessingSecurityScopedResource()
            ready.remove(record.id)
            failures.removeValue(forKey: record.id)
        }
    }
}
