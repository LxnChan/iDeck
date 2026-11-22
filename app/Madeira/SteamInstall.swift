// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright 2026 125hz
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

// Where Madeira's own Steam downloads live, and how one is read and removed
// (docs/STEAM_LIBRARY.md). Foundation only, so tests/host/check-steam-library.py
// compiles this file as it is.
//
// A download goes into Madeira Dock's own Steam library folder,
// C:\Program Files (x86)\Steam\steamapps, as `common/<installdir>` plus Steam's
// `appmanifest_<appid>.acf` install record. That is exactly the layout
// Madeira Dock's discovery (MadeiraDock.games) reads and Valve's client, which
// Dock starts the game through, understands: a game is "installed" for Dock
// once its record says so, and the record is written last.

enum SteamInstallPaths {
    /// The library folder, relative to drive_c (the value `DockGame.library` has).
    static let libraryRelative = "Program Files (x86)/Steam/steamapps"

    static func steamApps(drive: URL) -> URL { drive.appendingPathComponent(libraryRelative, isDirectory: true) }
    static func common(drive: URL) -> URL { steamApps(drive: drive).appendingPathComponent("common", isDirectory: true) }

    /// Whether an install (its drive-relative library folder) is in the library
    /// Madeira downloads into, and so can be updated or removed here.
    static func isManaged(library: String) -> Bool {
        library.caseInsensitiveCompare(libraryRelative) == .orderedSame || DrivePaths.shared.isManagedLibrary(library)
    }
}

/// Stored internally before game files change; contains public chunk hashes,
/// install paths and sizes, never depot keys or account credentials.
enum SteamInstallRecovery {
    struct Chunk: Codable, Sendable { var offset: UInt64; var length: UInt32; var sha: Data }
    struct File: Codable, Sendable { var relative: String; var size: UInt64; var chunks: [Chunk] }
    struct Snapshot: Codable, Sendable {
        var version = 1
        var library: String
        var folder: String
        var files: [File]
    }
    struct Audit: Equatable, Sendable { var verified = 0; var damagedOrMissing = 0 }
    nonisolated static func save(_ snapshot: Snapshot, at url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = PropertyListEncoder()
        encoder.outputFormat = .binary
        try encoder.encode(snapshot).write(to: url, options: .atomic)
    }
    nonisolated static func audit(at url: URL, library: String, steamApps: URL,
                                  checkStorage: () throws -> Void, hash: (Data) -> Data) throws -> Audit {
        guard (try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 64 << 20 else {
            throw SteamFileError.invalid("Recovery information is too large. Resume to verify the download with Steam.")
        }
        let snapshot = try PropertyListDecoder().decode(Snapshot.self, from: Data(contentsOf: url))
        guard snapshot.version == 1, snapshot.library == library,
              SteamInstallFiles.safeFolderName(snapshot.folder) == snapshot.folder else {
            throw SteamFileError.invalid("Recovery information is invalid. Resume to verify the download with Steam.")
        }
        var result = Audit(), folded: [String: String] = [:]
        let root = steamApps.resolvingSymlinksInPath().standardizedFileURL
        let install = root.appendingPathComponent("common/" + snapshot.folder)
        for file in snapshot.files {
            try Task.checkCancellation()
            try checkStorage()
            guard let relative = SteamInstallFiles.safeRelativePath(file.relative, folded: &folded) else {
                throw SteamFileError.invalid("An unsafe recovery path was rejected.")
            }
            let target = try SteamInstallFiles.confined(install.appendingPathComponent(relative), to: root)
            for chunk in file.chunks {
                try Task.checkCancellation()
                guard chunk.sha.count == 20, chunk.length > 0, chunk.length <= 32 << 20,
                      chunk.offset <= file.size, UInt64(chunk.length) <= file.size - chunk.offset else {
                    throw SteamFileError.invalid("Recovery chunk information is invalid.")
                }
                // FileHandle reads bridge through Foundation on Apple platforms.
                // Drain their temporary objects per chunk, rather than retaining
                // the whole audit's reads until this background task finishes.
                let matched: Bool
                #if canImport(ObjectiveC)
                matched = autoreleasepool { matches(chunk, at: target, hash: hash) }
                #else
                matched = matches(chunk, at: target, hash: hash)
                #endif
                if matched { result.verified += 1 }
                else { result.damagedOrMissing += 1 }
            }
        }
        try checkStorage()
        return result
    }
    nonisolated static func matches(_ chunk: Chunk, at url: URL, hash: (Data) -> Data) -> Bool {
        guard let handle = try? FileHandle(forReadingFrom: url) else { return false }
        defer { try? handle.close() }
        do {
            try handle.seek(toOffset: chunk.offset)
            var bytes = Data()
            while bytes.count < Int(chunk.length) {
                guard let next = try handle.read(upToCount: Int(chunk.length) - bytes.count), !next.isEmpty else { return false }
                bytes.append(next)
            }
            return hash(bytes) == chunk.sha
        } catch { return false }
    }
}

enum SteamInstallFiles {
    /// A manifest path may be safe while an existing directory or file at that
    /// path is a link. Refuse those links before modifying an installation.
    nonisolated static func confined(_ url: URL, to root: URL) throws -> URL {
        let base = root.standardizedFileURL, target = url.standardizedFileURL
        guard target.path.hasPrefix(base.path + "/") else { throw SteamFileError.invalid("The install path leaves its library.") }
        let relative = String(target.path.dropFirst(base.path.count + 1))
        var current = base
        for part in relative.split(separator: "/") {
            current.appendPathComponent(String(part))
            if let attrs = try? FileManager.default.attributesOfItem(atPath: current.path),
               attrs[.type] as? FileAttributeType == .typeSymbolicLink {
                throw SteamFileError.invalid("An install path contains a symbolic link. Move that link aside before downloading or removing the game.")
            }
        }
        guard target.resolvingSymlinksInPath().path.hasPrefix(base.resolvingSymlinksInPath().path + "/") else {
            throw SteamFileError.invalid("The install path leaves its library.")
        }
        return target
    }
    /// The `buildid` the install record of an app states, or nil when there is
    /// no readable record.
    static func buildID(appID: Int, steamApps: URL) -> Int? {
        guard let state = record(appID: appID, steamApps: steamApps) else { return nil }
        return state["buildid"]?.string.flatMap { Int($0) }
    }

    /// The install size the record states (`SizeOnDisk`, bytes), or nil.
    static func sizeOnDisk(appID: Int, steamApps: URL) -> Int64? {
        guard let state = record(appID: appID, steamApps: steamApps),
              let size = state["SizeOnDisk"]?.string.flatMap({ Int64($0) }), size > 0 else { return nil }
        return size
    }

    /// Removes an app's install: its folder under `common`, its record, its
    /// resume journal and the records of the apps that own its shared depots
    /// (those describe the same folder). Only paths strictly inside
    /// `steamApps/common` are removed.
    nonisolated static func delete(appID: Int, folderName: String, steamApps: URL) throws {
        let fm = FileManager.default
        _ = try confined(steamApps.appendingPathComponent("common/" + safeFolderName(folderName)), to: steamApps)
        _ = try confined(steamApps.appendingPathComponent("downloading/\(appID)"), to: steamApps)
        let common = steamApps.appendingPathComponent("common", isDirectory: true).resolvingSymlinksInPath().standardizedFileURL
        let folder = common.appendingPathComponent(safeFolderName(folderName)).resolvingSymlinksInPath().standardizedFileURL
        if folder.path.hasPrefix(common.path + "/"), folder.deletingLastPathComponent().path == common.path {
            try? fm.removeItem(at: folder)
        }
        let recordURL = steamApps.appendingPathComponent("appmanifest_\(appID).acf")
        if let state = record(appID: appID, steamApps: steamApps) {
            let shared = (state["SharedDepots"]?.fields ?? [:]).sorted(by: { $0.key < $1.key }).prefix(64)
            for (_, owner) in shared {
                guard let ownerID = owner.string.flatMap({ Int($0) }), ownerID > 0, ownerID != appID,
                      let ownerState = record(appID: ownerID, steamApps: steamApps),
                      let dir = ownerState["installdir"]?.string
                else { continue }
                // An owner in another folder (its own installdir) goes too when
                // it holds nothing but depots shared into this app.
                let mine = Set(shared.filter { $0.value.string == owner.string }.map { $0.key })
                let held = Set((ownerState["InstalledDepots"]?.fields ?? [:]).keys)
                guard safeFolderName(dir).caseInsensitiveCompare(safeFolderName(folderName)) == .orderedSame ||
                      held.isSubset(of: mine) else { continue }
                try? fm.removeItem(at: steamApps.appendingPathComponent("appmanifest_\(ownerID).acf"))
            }
        }
        try? fm.removeItem(at: recordURL)
        try? fm.removeItem(at: steamApps.appendingPathComponent("downloading/\(appID)", isDirectory: true))
    }

    /// Validates a manifest path and folds directory spelling to the first
    /// one seen (case-insensitively). Returns nil for anything that could
    /// escape the install folder.
    nonisolated static func safeRelativePath(_ name: String, folded: inout [String: String]) -> String? {
        let parts = name.replacingOccurrences(of: "\\", with: "/").split(separator: "/", omittingEmptySubsequences: true).map(String.init)
        guard !parts.isEmpty, parts.count <= 64, name.utf8.count < 1024,
              !parts.contains(where: { $0 == "." || $0 == ".." || $0.contains(":") ||
                  $0.unicodeScalars.contains(where: { $0.value < 0x20 }) }) else { return nil }
        var built: [String] = []
        for (index, part) in parts.enumerated() {
            if index == parts.count - 1 { built.append(part); break }
            let key = (built + [part]).joined(separator: "/").lowercased()
            if let existing = folded[key] {
                built = existing.split(separator: "/").map(String.init)
            } else {
                built.append(part)
                folded[key] = built.joined(separator: "/")
            }
        }
        return built.joined(separator: "/")
    }

    /// Install folders come from app metadata; keep them to one safe component.
    nonisolated static func safeFolderName(_ name: String) -> String {
        let cleaned = name.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
        guard !cleaned.isEmpty, cleaned != ".", cleaned != "..", !cleaned.contains(":"),
              !cleaned.unicodeScalars.contains(where: { $0.value < 0x20 }) else { return "app" }
        return cleaned
    }

    /// The `AppState` block of `appmanifest_<appid>.acf` when the file is
    /// readable, bounded, and names this app.
    private static func record(appID: Int, steamApps: URL) -> SteamValue? {
        let url = steamApps.appendingPathComponent("appmanifest_\(appID).acf")
        guard let data = try? Data(contentsOf: url), data.count <= 1 << 20,
              var parser = try? SteamKeyValues(data), let root = try? parser.read(),
              let state = root["AppState"], state["appid"]?.string == String(appID) else { return nil }
        return state
    }
}
