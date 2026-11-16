//
//  GameProfiles.swift
//  Madeira
//
//  madeira-bcd: a game's own settings file -- Winlator's per-shortcut
//  overrides, in this app's terms.
//
//  Same syntax as Documents/madeira.cfg (key = value, env.NAME = value, # for
//  comments). The launch exports its path as MADEIRA_CFG_GAME; the native
//  reader (build/madeira_cfg.h) lets a key set here win over madeira.cfg, and
//  WineProcessBridge exports its env.* lines after madeira.cfg's. So any
//  runtime switch -- a D3D12 experiment, a FEX option, a DXMT setting -- can be
//  set for one game without touching the others, and without a new build.
//
//  Game details › This game's config edits the file.
//

import Foundation

/// The per-game process rule, shared by the details control and direct starts.
/// Keep the on-disk format understood by the bundled Wine runtime.
struct ChildLaunchArguments: Equatable {
    static let key = "env.MADEIRA_CHILD_ARGS"
    let program: String
    let arguments: String

    init?(configuration: String) {
        guard let value = GameProfile.parse(configuration)[Self.key],
              let space = value.firstIndex(of: " ") else { return nil }
        program = String(value[..<space])
        arguments = value[value.index(after: space)...].trimmingCharacters(in: .whitespaces)
        guard !program.isEmpty, !arguments.isEmpty else { return nil }
    }

    static func executableName(_ path: String) -> String {
        path.replacingOccurrences(of: "\\", with: "/").split(separator: "/").last.map(String.init) ?? ""
    }

    struct Invalid: LocalizedError {
        let errorDescription: String?
        init(_ message: String) { errorDescription = message }
    }

    static func validateArguments(_ arguments: String, asciiOnly: Bool = true) throws {
        guard arguments.utf8.count < 4096,
              arguments.unicodeScalars.allSatisfy({ $0.value == 9 || ($0.value >= 32 && $0.value != 127 && (!asciiOnly || $0.value <= 126)) }) else {
            throw Invalid("Use a single line of ASCII launch arguments shorter than 4 KB.")
        }
        var quoted = false, inToken = false, tokens = 0
        for character in arguments {
            if character == "\"" { quoted.toggle() }
            if !quoted && (character == " " || character == "\t") { inToken = false }
            else if !inToken { inToken = true; tokens += 1 }
        }
        guard !quoted, tokens <= 64 else {
            throw Invalid("Use balanced double quotes and at most 64 launch arguments in total.")
        }
    }

    /// Update only this rule. Clearing it preserves every other setting/comment.
    static func replacing(in configuration: String, program: String, arguments: String) throws -> String {
        let args = arguments.trimmingCharacters(in: .whitespaces)
        let name = program.trimmingCharacters(in: .whitespaces)
        if !args.isEmpty {
            // child_extra_args has a 64-byte name buffer and splits at a space.
            guard name.lowercased().hasSuffix(".exe"), name.utf8.count < 64,
                  name.unicodeScalars.allSatisfy({ (33...126).contains($0.value) && !"/\\\"<>:|?*".unicodeScalars.contains($0) }) else {
                throw Invalid("Choose an .exe filename without spaces, shorter than 64 ASCII characters.")
            }
            try validateArguments(args)
        }
        var lines = configuration.components(separatedBy: "\n").filter { line in
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.hasPrefix("#"), let equals = trimmed.firstIndex(of: "=") else { return true }
            return trimmed[..<equals].trimmingCharacters(in: .whitespaces) != key
        }
        if lines.last == "" { lines.removeLast() }
        if !args.isEmpty { lines.append("\(key) = \(name) \(args)") }
        return lines.isEmpty ? "" : lines.joined(separator: "\n") + "\n"
    }

    /// The initial Wine process does not pass through child_extra_args. Append
    /// here only when it is the target itself; explorer/cmd/Steam use Wine's hook.
    func appending(to original: String, executable: String) throws -> String {
        guard Self.executableName(executable).caseInsensitiveCompare(program) == .orderedSame else { return original }
        let combined = original.isEmpty ? arguments : original + " " + arguments
        try Self.validateArguments(combined, asciiOnly: false)
        return combined
    }
}

struct GameProfile {
    let windowsPath: String

    static var directory: URL? {
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return nil
        }
        let dir = base.appendingPathComponent("GameConfigs", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    var url: URL? {
        GameProfile.directory?.appendingPathComponent(
            String(format: "%016llx.cfg", LibraryPrefs.stableHash(windowsPath.lowercased())))
    }

    /// The whole file ("" when there is none). Setting "" deletes it.
    var text: String {
        get {
            guard let u = url, let t = try? String(contentsOf: u, encoding: .utf8) else { return "" }
            return t
        }
        nonmutating set {
            guard let u = url else { return }
            if newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                try? FileManager.default.removeItem(at: u)
            } else {
                try? (newValue.hasSuffix("\n") ? newValue : newValue + "\n").write(to: u, atomically: true, encoding: .utf8)
            }
        }
    }

    /// key -> value, the last line winning, as the native reader does.
    var values: [String: String] { GameProfile.parse(text) }

    static func parse(_ text: String) -> [String: String] {
        var out: [String: String] = [:]
        for raw in text.split(whereSeparator: { $0 == "\n" || $0 == "\r\n" }) {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard !line.isEmpty, !line.hasPrefix("#"), let eq = line.firstIndex(of: "=") else { continue }
            let k = line[..<eq].trimmingCharacters(in: .whitespaces)
            if !k.isEmpty { out[k] = line[line.index(after: eq)...].trimmingCharacters(in: .whitespaces) }
        }
        return out
    }

    /// True when the file sets anything at all.
    var hasSettings: Bool { !values.isEmpty }
}
