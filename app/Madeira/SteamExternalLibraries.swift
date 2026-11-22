// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import Foundation

/// Register external libraries before starting Valve's client. Append only:
/// existing entries, spelling, comments, and unknown fields remain byte-for-byte.
enum SteamExternalLibraries {
    static func prepare(drive: URL, clientRelative: String) throws {
        let libraries = DrivePaths.shared.steamLibraries
        guard !libraries.isEmpty else { return }
        _ = try DrivePaths.shared.resolve(clientRelative + "/steamapps", drive: drive, mustExist: false)
        let file = drive.appendingPathComponent(clientRelative + "/steamapps/libraryfolders.vdf")
        let fm = FileManager.default
        let original: Data
        if fm.fileExists(atPath: file.path) {
            guard (try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max) <= 1 << 20 else {
                throw SteamFileError.invalid("Steam's library configuration is too large. External libraries were not registered.")
            }
            original = try Data(contentsOf: file)
        } else {
            let path = "C:\\" + clientRelative.replacingOccurrences(of: "/", with: "\\")
            original = Data(("\"libraryfolders\"\n{\n\t\"0\"\n\t{\n\t\t\"path\" \(quote(path))\n\t}\n}\n").utf8)
        }
        let updated = try adding(libraries, to: original)
        guard updated != original else { return }
        try fm.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
        let backup = file.appendingPathExtension("ideck-before-external")
        if fm.fileExists(atPath: file.path), !fm.fileExists(atPath: backup.path) {
            try original.write(to: backup, options: .withoutOverwriting)
        }
        try updated.write(to: file, options: .atomic)
    }
    static func adding(_ libraries: [String], to data: Data) throws -> Data {
        var parser = try SteamKeyValues(data)
        let parsed = try parser.read()
        guard parsed.fields.count == 1, let root = parsed["libraryfolders"], case .object = root else {
            throw SteamFileError.invalid("Steam's library configuration could not be safely updated.")
        }
        var existing = Set(root.fields.values.compactMap { $0["path"]?.string?.replacingOccurrences(of: "\\", with: "/").lowercased() })
        let maximum = root.fields.keys.compactMap(Int.init).max() ?? -1
        guard maximum >= -1, maximum < 1023 else { throw SteamFileError.invalid("Too many Steam library entries.") }
        var index = maximum + 1
        var text = ""
        for library in libraries {
            guard let parts = DrivePaths.parts(library), parts.last == "steamapps", parts.count >= 2 else {
                throw SteamFileError.invalid("Invalid external Steam library path.")
            }
            let path = "C:/" + parts.dropLast().joined(separator: "/")
            guard existing.insert(path.lowercased()).inserted else { continue }
            text += "\n\t\"\(index)\"\n\t{\n\t\t\"path\" \(quote(path.replacingOccurrences(of: "/", with: "\\")))\n\t\t\"label\" \"iDeck external\"\n\t\t\"apps\"\n\t\t{\n\t\t}\n\t}\n"
            index += 1
        }
        guard !text.isEmpty else { return data }
        let bytes = Array(data)
        var quoted = false, escaped = false, comment = false, depth = 0, closing: Int?
        for i in bytes.indices {
            let byte = bytes[i]
            if comment { if byte == 10 { comment = false }; continue }
            if quoted {
                if escaped { escaped = false }
                else if byte == 92 { escaped = true }
                else if byte == 34 { quoted = false }
                continue
            }
            if byte == 47, i + 1 < bytes.count, bytes[i + 1] == 47 { comment = true; continue }
            if byte == 34 { quoted = true }
            else if byte == 123 { depth += 1 }
            else if byte == 125 { depth -= 1; if depth == 0 { closing = i; break } }
        }
        guard let closing else { throw SteamFileError.invalid("Steam's library configuration is incomplete.") }
        return Data(bytes[..<closing]) + Data(text.utf8) + Data(bytes[closing...])
    }
    private static func quote(_ value: String) -> String {
        "\"" + value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"") + "\""
    }
}
