// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// The app's logical C: paths stay stable when iOS remounts a selected folder.
/// Only registered links may leave drive_c; ordinary symlink escapes still fail.
/// This registry is also read by the background metadata and Steam scanners.
final class DrivePaths: @unchecked Sendable {
    static let shared = DrivePaths()
    static let externalDirectory = "External"
    struct Mount: Sendable {
        var id: UUID
        var url: URL
        var available: Bool
        var problem: String
        var relativeRoot: String { DrivePaths.externalDirectory + "/" + id.uuidString }
    }
    struct Failure: LocalizedError {
        var message: String
        var code = "validation"
        var errorDescription: String? { message }
    }
    /// Log stable failure codes, never the localized error's folder paths.
    static func diagnostic(_ error: Error) -> String {
        if let failure = error as? Failure { return failure.code }
        let value = error as NSError
        let domains = [NSCocoaErrorDomain, NSPOSIXErrorDomain, NSURLErrorDomain, "NSFileProviderErrorDomain"]
        let domain = domains.contains(value.domain) ? value.domain : "other"
        var result = "\(domain)-\(value.code)"
        if let underlying = value.userInfo[NSUnderlyingErrorKey] as? NSError {
            let domain = domains.contains(underlying.domain) ? underlying.domain : "other"
            result += ":\(domain)-\(underlying.code)"
        }
        return result
    }
    private let lock = NSLock()
    private var registered: [UUID: Mount] = [:]
    func replace(_ mounts: [Mount]) {
        lock.lock(); defer { lock.unlock() }
        registered = Dictionary(uniqueKeysWithValues: mounts.map { ($0.id, $0) })
    }
    var mounts: [Mount] {
        lock.lock(); defer { lock.unlock() }
        return Array(registered.values).sorted { $0.id.uuidString < $1.id.uuidString }
    }
    static func parts(_ relative: String) -> [String]? {
        let path = relative.replacingOccurrences(of: "\\", with: "/")
        guard !path.hasPrefix("/"), !path.contains(":"), !path.contains("\0") else { return nil }
        let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !parts.isEmpty, parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.unicodeScalars.contains(where: { $0.value < 32 }) }) else { return nil }
        return parts
    }
    static func mountID(_ relative: String) -> UUID? {
        guard let parts = parts(relative), parts.count >= 2,
              parts[0].caseInsensitiveCompare(externalDirectory) == .orderedSame else { return nil }
        return UUID(uuidString: parts[1])
    }
    static func within(_ url: URL, _ root: URL) -> Bool {
        let path = url.standardizedFileURL.path, base = root.standardizedFileURL.path
        return path == base || path.hasPrefix(base + "/")
    }
    /// Foundation may leave the entire URL unresolved if its final component
    /// does not exist. Resolve the nearest existing ancestor first so a fresh
    /// steamapps folder still follows its registered drive_c mapping. Do not
    /// treat dangling links, permission errors, or a non-directory as missing.
    private static func resolvedTarget(_ url: URL) throws -> URL {
        let fm = FileManager.default
        var ancestor = url, missing: [String] = []
        while true {
            do {
                let attributes = try fm.attributesOfItem(atPath: ancestor.path)
                if attributes[.type] as? FileAttributeType == .typeSymbolicLink,
                   !fm.fileExists(atPath: ancestor.path) {
                    throw Failure(message: "The path contains a broken symbolic link.", code: "broken-link")
                }
                if !missing.isEmpty {
                    var directory: ObjCBool = false
                    guard fm.fileExists(atPath: ancestor.path, isDirectory: &directory), directory.boolValue else {
                        throw Failure(message: "A parent folder in the path is not a directory.", code: "not-directory")
                    }
                }
                let root = ancestor.resolvingSymlinksInPath().standardizedFileURL
                return missing.reversed().reduce(root) { $0.appendingPathComponent($1) }
            } catch let error as NSError where error.domain == NSCocoaErrorDomain &&
                (error.code == NSFileNoSuchFileError || error.code == NSFileReadNoSuchFileError) {
                let parent = ancestor.deletingLastPathComponent()
                guard parent.path != ancestor.path else { throw error }
                missing.append(ancestor.lastPathComponent)
                ancestor = parent
            }
        }
    }
    /// Return the logical URL, not its resolved target: Wine must keep seeing C:.
    func resolve(_ relative: String, drive: URL, mustExist: Bool = true) throws -> URL {
        guard let parts = Self.parts(relative) else { throw Failure(message: "Invalid C: path.") }
        let base = drive.resolvingSymlinksInPath().standardizedFileURL
        let logical = parts.reduce(base) { $0.appendingPathComponent($1) }
        if let id = Self.mountID(relative) {
            guard let mount = mounts.first(where: { $0.id == id }), mount.available else {
                throw Failure(message: mounts.first(where: { $0.id == id })?.problem ?? "External folder is not connected or its mapping was removed.")
            }
            let root = mount.url.resolvingSymlinksInPath().standardizedFileURL
            try ExternalStorageProbe.check(root, expected: id, write: false)
            let target = try Self.resolvedTarget(logical)
            let link = base.appendingPathComponent(mount.relativeRoot)
            // A replaced link or a symlinked External parent must never grant access.
            guard base.appendingPathComponent(Self.externalDirectory).resolvingSymlinksInPath().path == base.appendingPathComponent(Self.externalDirectory).path,
                  (try? FileManager.default.destinationOfSymbolicLink(atPath: link.path)) == mount.url.path,
                  Self.within(target, root) else { throw Failure(message: "External folder mapping changed. Reconnect it in Settings.", code: "mapping-changed") }
        } else {
            let target = try Self.resolvedTarget(logical)
            guard Self.within(target, base) else { throw Failure(message: "The path leaves drive_c.") }
        }
        if mustExist, !FileManager.default.fileExists(atPath: logical.path) {
            throw Failure(message: "This game's file or folder is missing.")
        }
        return logical
    }
    func relative(_ url: URL, drive: URL) -> String? {
        let base = drive.resolvingSymlinksInPath().standardizedFileURL
        let logical = url.standardizedFileURL
        if Self.within(logical, base), logical.path != base.path {
            let relative = String(logical.path.dropFirst(base.path.count + 1))
            return (try? resolve(relative, drive: base)) == nil ? nil : relative
        }
        let target = url.resolvingSymlinksInPath().standardizedFileURL
        for mount in mounts where mount.available {
            let root = mount.url.resolvingSymlinksInPath().standardizedFileURL
            guard Self.within(target, root) else { continue }
            let suffix = target.path == root.path ? "" : "/" + String(target.path.dropFirst(root.path.count + 1))
            let relative = mount.relativeRoot + suffix
            if (try? resolve(relative, drive: base)) != nil { return relative }
        }
        return nil
    }
    func contains(_ url: URL, drive: URL) -> Bool {
        let base = drive.resolvingSymlinksInPath().standardizedFileURL
        return url.resolvingSymlinksInPath().standardizedFileURL == base || relative(url, drive: base) != nil
    }
    /// nil for ordinary internal paths. Offline mappings retain their identity.
    func problem(_ relative: String) -> String? {
        guard let id = Self.mountID(relative) else { return nil }
        guard let mount = mounts.first(where: { $0.id == id }) else { return "External folder mapping was removed." }
        return mount.available ? nil : mount.problem
    }
    var steamLibraries: [String] { mounts.filter(\.available).map { $0.relativeRoot + "/steamapps" } }
    func isManagedLibrary(_ relative: String) -> Bool {
        mounts.contains { ($0.relativeRoot + "/steamapps").caseInsensitiveCompare(relative) == .orderedSame }
    }
}

/// Disk operations used both by setup and reconnect, and exercised on real host
/// directories by the regression test. Every probe file is exclusively ours.
enum ExternalStorageProbe {
    static let marker = ".ideck-storage-id"
    static func identity(at root: URL) throws -> UUID {
        let file = root.appendingPathComponent(marker)
        let values = try file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true, (values.fileSize ?? Int.max) < 128 else {
            throw DrivePaths.Failure(message: "The external folder's identity file is invalid.", code: "identity-invalid")
        }
        let data = try Data(contentsOf: file)
        guard data.count < 128, let text = String(data: data, encoding: .utf8), let id = UUID(uuidString: text.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            throw DrivePaths.Failure(message: "The external folder's identity could not be verified.", code: "identity-invalid")
        }
        return id
    }
    static func check(_ root: URL, expected: UUID? = nil, write: Bool) throws {
        let fresh = URL(fileURLWithPath: root.path, isDirectory: true)
        let values = try fresh.resourceValues(forKeys: [.isDirectoryKey, .isReadableKey, .isWritableKey, .volumeIsReadOnlyKey, .volumeIsLocalKey, .isUbiquitousItemKey])
        guard values.isDirectory == true, values.isReadable != false else { throw DrivePaths.Failure(message: "External folder is missing or cannot be read.", code: "unreadable") }
        guard values.volumeIsLocal != false, values.isUbiquitousItem != true else { throw DrivePaths.Failure(message: "Choose a folder on a locally connected drive.", code: "nonlocal") }
        guard values.volumeIsReadOnly != true, values.isWritable != false, FileManager.default.isWritableFile(atPath: root.path) else { throw DrivePaths.Failure(message: "External folder is read-only. Choose a writable folder.", code: "read-only") }
        if let expected, try identity(at: root) != expected { throw DrivePaths.Failure(message: "A different folder is at this location. Select the original folder again.", code: "identity-mismatch") }
        guard write else { return }
        let fm = FileManager.default
        let temporary = root.appendingPathComponent(".ideck-write-check-" + UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: temporary, withIntermediateDirectories: false)
        defer { try? fm.removeItem(at: temporary) }
        let file = temporary.appendingPathComponent("probe"), renamed = temporary.appendingPathComponent("renamed")
        let bytes = Data(UUID().uuidString.utf8)
        try bytes.write(to: file, options: .withoutOverwriting)
        guard try Data(contentsOf: file) == bytes else { throw DrivePaths.Failure(message: "External folder failed its read/write check.", code: "write-check") }
        try fm.moveItem(at: file, to: renamed)
        try fm.removeItem(at: renamed)
        try fm.removeItem(at: temporary)
    }
    static func identify(_ root: URL) throws -> UUID {
        let file = root.appendingPathComponent(marker)
        if FileManager.default.fileExists(atPath: file.path) { return try identity(at: root) }
        let id = UUID()
        try Data(id.uuidString.utf8).write(to: file, options: .withoutOverwriting)
        return id
    }
}
