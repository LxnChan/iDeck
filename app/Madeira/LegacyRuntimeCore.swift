// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
import Foundation

enum LegacyRuntimeError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

/// Bounded PE reads shared by dependency detection and user-supplied DLL checks.
/// Import and delay-import thunks retain names/ordinals, not only DLL filenames.
struct LegacyRuntimePE {
    let bytes: [UInt8]
    let machine: Int
    let optional: Int
    let sections: Int
    let sectionCount: Int
    let is64: Bool
    var bits: Int { machine == 0x14c ? 32 : machine == 0x8664 ? 64 : 0 }

    init(_ data: Data) throws {
        let b = [UInt8](data)
        func word(_ p: Int) -> Int { Int(b[p]) | Int(b[p + 1]) << 8 }
        func dword(_ p: Int) -> Int { word(p) | word(p + 2) << 16 }
        guard b.count >= 64, b.count <= 32 * 1024 * 1024, b[0] == 77, b[1] == 90 else { throw Self.invalid }
        let pe = dword(60)
        guard pe >= 64, pe <= b.count - 24, Array(b[pe..<pe + 4]) == [80, 69, 0, 0] else { throw Self.invalid }
        let opt = pe + 24, optSize = word(pe + 20), count = word(pe + 6)
        guard optSize >= 120, optSize <= b.count - opt, count > 0, count <= 96,
              count * 40 <= b.count - opt - optSize, [0x10b, 0x20b].contains(word(opt)) else { throw Self.invalid }
        bytes = b; machine = word(pe + 4); optional = opt
        sections = opt + optSize; sectionCount = count; is64 = word(opt) == 0x20b
    }
    init(url: URL) throws {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        guard size > 0, size <= 32 * 1024 * 1024 else { throw Self.invalid }
        try self.init(Data(contentsOf: url, options: .mappedIfSafe))
    }
    static var invalid: LegacyRuntimeError { .message("The file is not a supported Windows PE executable or DLL.") }
    func u16(_ p: Int) -> Int { Int(bytes[p]) | Int(bytes[p + 1]) << 8 }
    func u32(_ p: Int) -> Int { u16(p) | u16(p + 2) << 16 }
    func offset(_ rva: Int, size: Int = 1) -> Int? {
        guard rva > 0, size >= 0 else { return nil }
        for index in 0..<sectionCount {
            let p = sections + index * 40, va = u32(p + 12), raw = u32(p + 16), file = u32(p + 20)
            if rva >= va, rva - va <= raw, size <= raw - (rva - va) {
                let at = file + rva - va
                if at <= bytes.count, size <= bytes.count - at { return at }
            }
        }
        return nil
    }
    func string(_ rva: Int) -> String? {
        guard let at = offset(rva) else { return nil }
        let end = min(bytes.count, at + 512)
        guard let zero = bytes[at..<end].firstIndex(of: 0) else { return nil }
        return String(bytes: bytes[at..<zero], encoding: .utf8)
    }
    func directory(_ index: Int) -> Int? {
        let base = optional + (is64 ? 112 : 96), countAt = optional + (is64 ? 108 : 92)
        guard countAt + 4 <= sections, index < u32(countAt), base + index * 8 + 8 <= sections else { return nil }
        return offset(u32(base + index * 8))
    }

    /// "#123" denotes an ordinal; all other entries are case-sensitive exports.
    func mfc42Imports() throws -> Set<String> {
        var result = Set<String>()
        for (index, stride, nameAt, thunkAt) in [(1, 20, 12, 0), (13, 32, 4, 16)] {
            guard let base = directory(index) else { continue }
            for descriptor in 0..<512 {
                let p = base + descriptor * stride
                guard p + stride <= bytes.count else { throw Self.invalid }
                let name = u32(p + nameAt)
                if name == 0 { break }
                let delayedVA = index == 13 && u32(p) & 1 == 0
                guard !delayedVA || !is64 else { throw Self.invalid }
                let imageBase = delayedVA ? u32(optional + 28) : 0
                guard name >= imageBase else { throw Self.invalid }
                guard string(name - imageBase)?.lowercased() == "mfc42.dll" else { continue }
                var thunk = u32(p + thunkAt)
                if index == 1 && thunk == 0 { thunk = u32(p + 16) }
                guard thunk >= imageBase, let table = offset(thunk - imageBase) else { throw Self.invalid }
                let width = is64 ? 8 : 4
                for item in 0..<8192 {
                    let t = table + item * width
                    guard t + width <= bytes.count else { throw Self.invalid }
                    let low = u32(t), high = is64 ? u32(t + 4) : 0
                    if low == 0 && high == 0 { break }
                    if (is64 ? high : low) & 0x80000000 != 0 { result.insert("#\(low & 0xffff)") }
                    else {
                        guard high == 0, low >= imageBase, let symbol = string(low - imageBase + 2) else { throw Self.invalid }
                        result.insert(symbol)
                    }
                }
            }
        }
        return result
    }

    func mfc42Exports() throws -> Set<String> {
        guard bits == 32, let p = directory(0), p + 40 <= bytes.count,
              string(u32(p + 12))?.lowercased() == "mfc42.dll" else {
            throw LegacyRuntimeError.message("Choose the 32-bit MFC42.DLL runtime. The 64-bit Windows DLL cannot serve 32-bit programs.")
        }
        let base = u32(p + 16), count = u32(p + 20), names = u32(p + 24)
        guard count <= 65536, names <= count, let functions = offset(u32(p + 28), size: count * 4),
              let table = offset(u32(p + 32), size: names * 4), let ordinals = offset(u32(p + 36), size: names * 2) else { throw Self.invalid }
        var result = Set<String>()
        for i in 0..<count where u32(functions + i * 4) != 0 { result.insert("#\(base + i)") }
        for i in 0..<names {
            let ordinal = u16(ordinals + i * 2)
            guard ordinal < count, u32(functions + ordinal * 4) != 0, let name = string(u32(table + i * 4)) else { throw Self.invalid }
            result.insert(name)
        }
        guard result.count >= 100 else { throw Self.invalid }
        return result
    }
}

enum LegacyRuntimeDependency {
    struct Need: Sendable {
        let symbols: Set<String>
        let importers: [String]
        let incomplete: Bool
    }
    static func inside(_ url: URL, _ root: URL) -> Bool {
        let path = url.resolvingSymlinksInPath().standardizedFileURL.path
        let base = root.resolvingSymlinksInPath().standardizedFileURL.path
        return path == base || path.hasPrefix(base + "/")
    }
    static func matching(_ name: String, in directory: URL) -> URL? {
        (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil))?
            .first { $0.lastPathComponent.caseInsensitiveCompare(name) == .orderedSame }
    }
    /// Scan only this installation (including dynamically loaded plugin DLLs).
    /// Budgets keep an unrelated large library from blocking launch forever.
    static func scan(executable: URL, drive: URL, prefix: URL) throws -> Need? {
        guard DrivePaths.shared.contains(executable, drive: drive), !Task.isCancelled else { return nil }
        let fm = FileManager.default
        var isDirectory: ObjCBool = false
        guard fm.fileExists(atPath: executable.path, isDirectory: &isDirectory) else { return nil }
        let folder = isDirectory.boolValue ? executable : executable.deletingLastPathComponent()
        var root = folder
        let binaryFolders: Set<String> = ["bin", "binaries", "win32", "win64", "x86", "x64", "release"]
        for _ in 0..<4 {
            guard binaryFolders.contains(root.lastPathComponent.lowercased()) else { break }
            let parent = root.deletingLastPathComponent()
            guard parent != drive, DrivePaths.shared.contains(parent, drive: drive), !["games", "common", "steamapps", "program files", "program files (x86)"].contains(parent.lastPathComponent.lowercased()) else { break }
            root = parent
        }
        var candidates = isDirectory.boolValue ? [] : [executable]
        var incomplete = false, visited = 0
        if root != drive, let walker = fm.enumerator(at: root, includingPropertiesForKeys: [.isSymbolicLinkKey], options: [.skipsHiddenFiles]) {
            while let file = walker.nextObject() as? URL {
                try Task.checkCancellation()
                visited += 1
                if visited > 8192 || candidates.count >= 512 { incomplete = true; break }
                if (try? file.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true { walker.skipDescendants(); continue }
                if ["exe", "dll"].contains(file.pathExtension.lowercased()), file != executable { candidates.append(file) }
            }
        }
        var required = Set<String>(), importers: [String] = [], budget = 64 * 1024 * 1024
        for file in candidates {
            try Task.checkCancellation()
            let size = (try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            guard size > 0, size <= 32 * 1024 * 1024, size <= budget else { incomplete = true; continue }
            budget -= size
            guard let pe = try? LegacyRuntimePE(url: file), pe.bits == 32,
                  let symbols = try? pe.mfc42Imports(), !symbols.isEmpty else { continue }
            required.formUnion(symbols); importers.append(file.lastPathComponent)
        }
        guard !required.isEmpty else { return nil }
        let local = matching("mfc42.dll", in: folder)
        let system = matching("mfc42.dll", in: prefix.appendingPathComponent("drive_c/windows/syswow64"))
        if let runtime = local ?? system {
            if let exports = try? LegacyRuntimePE(url: runtime).mfc42Exports(), required.isSubset(of: exports) { return nil }
            throw LegacyRuntimeError.message("An existing MFC42.DLL is incompatible or lacks required exports: \(runtime.path). Move that copy aside or supply a compatible 32-bit runtime; it will not be overwritten.")
        }
        return Need(symbols: required, importers: importers, incomplete: incomplete)
    }
}

enum LegacyRuntimePin {
    static let url = URL(string: "https://download.microsoft.com/download/vc60pro/Update/2/W9XNT4/EN-US/VC6RedistSetup_deu.exe")!
    static let bytes = 1_837_888
    static let sha256 = "c2eb91d9c4448d50e46a32fecbcc3b418706d002beab9b5f4981de552098cee7"
    static let dllSHA256 = "ec63a85030c60716acdcf060abfaa95a6a3528631622fa60e7d17fbea2f751f9"
    static let relativePackage = "madeira-runtime/VC6RedistSetup_deu.exe"
    static let helper = "madeira-runtime-install.exe"
    /// The initial program becomes a child only while this install is pending.
    /// Let the existing child-launch path apply its profile arguments once.
    static func requiresInstallation(prefix: URL) -> Bool {
        let marker = prefix.appendingPathComponent("drive_c/madeira-runtime/pending-mfc42")
        guard (try? String(contentsOf: marker, encoding: .utf8)) == sha256 else { return false }
        let folder = prefix.appendingPathComponent("drive_c/windows/syswow64")
        guard let file = LegacyRuntimeDependency.matching("mfc42.dll", in: folder) else { return true }
        return (try? LegacyRuntimePE(url: file).mfc42Exports()) == nil
    }
    static func allowed(_ url: URL?) -> Bool {
        url?.scheme == "https" && url?.host?.lowercased() == "download.microsoft.com"
            && (url?.port == nil || url?.port == 443) && url?.user == nil && url?.password == nil
    }
    static func wrapped(executable: String, arguments: String, bits: Int) -> (exe: String, args: String) {
        let helper = "C:\\windows\\\(bits == 32 ? "syswow64" : "system32")\\\(helper)"
        return (helper, "\"C:\\madeira-runtime\\VC6RedistSetup_deu.exe\" \"C:\\windows\\syswow64\\mfc42.dll\" \"C:\\madeira-runtime\\result.txt\" --launch \"\(executable)\"" + (arguments.isEmpty ? "" : " " + arguments))
    }
    static func workingDirectory(executable: String, chosen: String?) -> String? {
        if let chosen { return chosen }
        guard executable.lowercased().hasPrefix("c:\\"), let slash = executable.lastIndex(of: "\\") else { return nil }
        let folder = String(executable[..<slash])
        return folder.count <= 2 ? folder + "\\" : folder
    }
}
