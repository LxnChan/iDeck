#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise per-game argument persistence and initial/child process routing."""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--require-swift', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
app = root / 'app/Madeira'
profiles = (app / 'GameProfiles.swift').read_text(encoding='utf-8')
library = (app / 'Library.swift').read_text(encoding='utf-8')
content = (app / 'ContentView.swift').read_text(encoding='utf-8')
bridge = (app / 'WineProcessBridge.m').read_text(encoding='utf-8')
native = (root / 'build/ntdll-unix/process_ios.c').read_text(encoding='utf-8')

# Steam entries get the control too; it uses the advanced editor's same profile.
assert 'if entry.desktop != true {\n                    LibraryChildArgumentsSection(entry: entry, configuration: $bcd.configText)' in library
section = library[library.index('private struct LibraryChildArgumentsSection: View'):library.index('struct BCDGameValues')]
assert 'ChildLaunchArguments.replacing(in: configuration' in section
assert 'try updated.write(to: url, atomically: true, encoding: .utf8)' in section
assert '.onChange(of: configuration)' in section
assert 'SteamDirectStart.program(picked: picked, options: options, installFolder: folder)' in section
assert 'cachedOnly: entry.steamOffline == true' in section
assert section.index('guard !Task.isCancelled, program.isEmpty') < section.index('chooseProgram(ChildLaunchArguments.executableName(detected))')
start = content[content.index('private func startLibraryEntry('):content.index('static func reassertBCDSwitches(')]
assert start.index('entry.configureLaunch()') < start.index('BCDLaunch.appendInitialArguments(entry)') < start.index('library.begin(entry)')
assert bridge.index('LOG("game config env:') < bridge.index('const char *madeira_exe = getenv("MADEIRA_EXE")')
assert 'child_extra_args( getenv( "MADEIRA_CHILD_ARGS" )' in native
print('PASS: details/advanced share storage; Steam detection and native/direct launch wiring')

swiftc = shutil.which('swiftc')
if not swiftc:
    if args.require_swift:
        raise SystemExit('FAIL: Swift compiler required')
    print('SKIP: Swift compiler unavailable locally; macOS CI runs the production Swift checks')
    raise SystemExit(0)

# Only the profile directory is redirected; compile the production parser,
# read/write storage, argument validation and BCD launch code unchanged.
begin = profiles.index('    static var directory: URL? {')
end = profiles.index('\n    var url: URL?', begin)
profiles = profiles[:begin] + '''    static var directory: URL? {
        URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    }
''' + profiles[end:]
harness = r'''
import Foundation
struct LibraryEntry {
    var desktop: Bool? = nil
    var windowsPath: String
}
final class LogStore {
    static let shared = LogStore()
    func log(_ message: String) {}
}
func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else { fatalError(message) }
}
func env(_ key: String) -> String { getenv(key).map { String(cString: $0) } ?? "" }
func rejects(_ operation: () throws -> Void) {
    do { try operation(); fatalError("invalid input accepted") } catch {}
}
@main struct Checks {
    static func main() throws {
        let original = "# keep my settings\npool = 768\nenv.MADEIRA_CHILD_ARGS = old.exe -old\n# env.MADEIRA_CHILD_ARGS = example.exe -keep\ndxmt = a=b\nenv.MADEIRA_CHILD_ARGS = final.exe -last\n"
        check(ChildLaunchArguments(configuration: original)?.arguments == "-last", "last rule wins")
        let updated = try ChildLaunchArguments.replacing(in: original, program: "abc.exe", arguments: "--rendering-driver opengl --name \"Two Words\"")
        let rule = ChildLaunchArguments(configuration: updated)!
        check(rule.program == "abc.exe", "automatic filename")
        check(rule.arguments == "--rendering-driver opengl --name \"Two Words\"", "quoted argument kept")
        let unicodeOriginal = try rule.appending(to: "--name 中文", executable: "abc.exe")
        check(unicodeOriginal.hasPrefix("--name 中文 "), "existing direct Unicode arguments are preserved")
        check(updated.contains("pool = 768\n") && updated.contains("dxmt = a=b\n"), "other settings kept")
        check(updated.contains("# env.MADEIRA_CHILD_ARGS = example.exe -keep\n"), "comments kept")
        check(updated.components(separatedBy: "\n").filter { $0.hasPrefix(ChildLaunchArguments.key) }.count == 1, "duplicate rules replaced")
        let cleared = try ChildLaunchArguments.replacing(in: updated, program: "", arguments: "   ")
        check(ChildLaunchArguments(configuration: cleared) == nil && cleared.contains("pool = 768"), "clear only removes this rule")
        let empty = try ChildLaunchArguments.replacing(in: "", program: "", arguments: "")
        check(empty == "", "empty stays empty")
        check(ChildLaunchArguments.executableName("C:\Games\abc.exe") == "abc.exe", "Windows name")
        check(ChildLaunchArguments.executableName("bin/abc.exe") == "abc.exe", "Steam relative name")
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-x\nenv.OTHER = 1") }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-name \"unclosed") }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "Game Name.exe", arguments: "-x") }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: String(repeating: "x", count: 4096)) }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: Array(repeating: "-x", count: 65).joined(separator: " ")) }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-name 中文") }

        let game = LibraryEntry(windowsPath: "C:\Games\abc.exe")
        let other = LibraryEntry(windowsPath: "C:\Games\other.exe")
        GameProfile(windowsPath: game.windowsPath).text = updated
        check(GameProfile(windowsPath: game.windowsPath).text == updated, "real profile round trip")
        check(GameProfile(windowsPath: other.windowsPath).text.isEmpty, "separate games")
        setenv("MADEIRA_EXE", "C:\Games\ABC.EXE", 1)
        setenv("MADEIRA_ARGS", "-existing", 1)
        try BCDLaunch.appendInitialArguments(game)
        check(env("MADEIRA_ARGS") == "-existing " + rule.arguments, "initial game gets appended arguments")
        for executable in ["explorer.exe", "C:\windows\system32\cmd.exe", "steam.exe", "other.exe"] {
            setenv("MADEIRA_EXE", executable, 1)
            setenv("MADEIRA_ARGS", "-existing", 1)
            try BCDLaunch.appendInitialArguments(game)
            check(env("MADEIRA_ARGS") == "-existing", "wrapper stays unchanged; Wine appends to the child")
        }
        setenv("MADEIRA_EXE", "abc.exe", 1)
        try BCDLaunch.appendInitialArguments(other)
        check(env("MADEIRA_ARGS") == "-existing", "no rule leaks to another game")
        GameProfile(windowsPath: game.windowsPath).text = cleared
        try BCDLaunch.appendInitialArguments(game)
        check(env("MADEIRA_ARGS") == "-existing", "clearing disables initial append too")
        print("PASS: production Swift persistence, replacement/clear, validation, direct/child routing and isolation")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='ideck-child-args-') as directory:
    folder = Path(directory)
    files = []
    for name, source in [('Profiles.swift', profiles), ('Checks.swift', harness)]:
        path = folder / name
        path.write_text(source, encoding='utf-8')
        files.append(str(path))
    executable = folder / 'checks'
    subprocess.run([swiftc, '-parse-as-library', '-swift-version', '5', *files,
                    str(app / 'LibraryPrefs.swift'), str(app / 'LibraryBCD.swift'),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(folder)], check=True)
