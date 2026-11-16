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
assert 'profile.saveChildArguments(program: program, arguments: arguments)' in section
assert 'let current = profile.text' in section and 'profile.childArgumentsDraft' in section
assert '.onChange(of: configuration)' in section
assert 'SteamDirectStart.program(picked: picked, options: options, installFolder: folder)' in section
assert 'cachedOnly: entry.steamOffline == true' in section
assert section.index('guard program.isEmpty, let detected') < section.index('chooseProgram(ChildLaunchArguments.executableName(detected))')
assert 'TextField("Target executable"' not in section
assert 'LabeledContent("Choose game program", value: program.isEmpty ? "Select…" : program)' in section
assert 'entry.steamAppID == nil ? target.deletingLastPathComponent() : target' in section
assert 'Game command preview' in section and 'existing = entry.programArguments' in section
assert 'Enter arguments in the field above' in section
field = library[library.index('private struct LibraryLaunchArgumentsField: UIViewRepresentable'):library.index('private struct LibraryChildArgumentsSection: View')]
for trait in ('smartDashesType', 'smartQuotesType', 'smartInsertDeleteType', 'autocorrectionType', 'spellCheckingType'):
    assert f'field.{trait} = .no' in field
assert 'for: .editingChanged' in field
start = content[content.index('private func startLibraryEntry('):content.index('static func reassertBCDSwitches(')]
assert start.index('entry.configureLaunch()') < start.index('BCDLaunch.appendInitialArguments(entry)') < start.index('library.begin(entry)')
assert bridge.index('LOG("game config env:') < bridge.index('const char *madeira_exe = getenv("MADEIRA_EXE")')
assert 'child_extra_args( getenv( "MADEIRA_CHILD_ARGS" )' in native
print('PASS: unified program chooser, literal punctuation, preview and persistent editor wiring')

# Compile the production child parser, including the quoted-filename boundary.
cc = shutil.which('cc') or shutil.which('clang')
if cc:
    def function(signature):
        start = native.index(signature)
        return native[start:native.index('\n}', start) + 2]

    native_checks = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint16_t WCHAR;
'''
    native_checks += function('static int ios_image_name_is(') + '\n'
    native_checks += function('static const char *child_extra_args(') + '\n'
    native_checks += r'''
static void check(const char *spec, const char *image, const char *expected) {
    WCHAR path[1024];
    size_t i, length = strlen(image);
    for (i = 0; i <= length; i++) path[i] = (unsigned char)image[i];
    const char *result = child_extra_args(spec, path, (int)length);
    if ((!expected && result) || (expected && (!result || strcmp(result, expected)))) {
        fprintf(stderr, "unexpected child args for %s: %s\n", spec ? spec : "NULL", result ? result : "NULL");
        exit(1);
    }
}
int main(void) {
    check("abc.exe --old", "C:\\Games\\ABC.EXE", "--old");
    check("\"Game Name.exe\" --rendering-driver opengl --name \"Two Words\"", "C:\\Games\\Game Name.exe", "--rendering-driver opengl --name \"Two Words\"");
    check(" \t\"GAME NAME.EXE\"\t --x", "C:/Games/Game Name.exe", "--x");
    check("\"Game Name.exe\" --x", "C:\\Games\\Game Name.exe.bak", NULL);
    check("\"Game Name.exe\" --x", "C:\\Games\\Game.exe", NULL);
    check("\"Game Name.exe --x", "Game Name.exe", NULL);
    check("\"Game Name.exe\"--x", "Game Name.exe", NULL);
    check("\"Game Name.exe\"", "Game Name.exe", NULL);
    check("\"Game Name.exe\"   ", "Game Name.exe", NULL);
    check("\"\" --x", "Game Name.exe", NULL);
    check(NULL, "Game Name.exe", NULL);
    char image[300], spec[320];
    memset(image, 'a', 251); strcpy(image + 251, ".exe");
    snprintf(spec, sizeof(spec), "\"%s\" --x", image);
    check(spec, image, "--x");
    memset(image, 'a', 252); strcpy(image + 252, ".exe");
    snprintf(spec, sizeof(spec), "\"%s\" --x", image);
    check(spec, image, NULL);
    puts("PASS: production Wine parser accepts quoted filenames with spaces; rejects malformed/oversized targets");
}
'''
    with tempfile.TemporaryDirectory(prefix='ideck-child-native-') as directory:
        source = Path(directory) / 'checks.c'
        executable = Path(directory) / 'checks'
        source.write_text(native_checks, encoding='utf-8')
        subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
elif args.require_swift:
    raise SystemExit('FAIL: C compiler required on CI')
else:
    print('SKIP: C compiler unavailable locally; macOS CI runs production Wine parser checks')

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
        let profile = GameProfile(windowsPath: #"C:\Games\Game Name.exe"#)
        if CommandLine.arguments.count > 2 {
            let rawArguments = "--rendering-driver opengl --name \"Two Words\" "
            switch CommandLine.arguments[2] {
            case "write-valid":
                profile.text = "# keep across launches\npool = 768\n"
                try profile.saveChildArguments(program: "Game Name.exe", arguments: rawArguments)
            case "read-valid":
                check(profile.childArgumentsDraft?.arguments == rawArguments, "raw input survives process restart")
                check(profile.childArgumentsDraft?.program == "Game Name.exe", "program choice survives restart")
                let rule = ChildLaunchArguments(configuration: profile.text)!
                check(rule.program == "Game Name.exe", "quoted target survives restart")
                check(rule.arguments == rawArguments.trimmingCharacters(in: .whitespaces), "active arguments survive restart")
                check(profile.text.contains("pool = 768"), "unrelated settings survive")
                setenv("MADEIRA_EXE", #"C:\Games\GAME NAME.EXE"#, 1)
                setenv("MADEIRA_ARGS", "--base", 1)
                try BCDLaunch.appendInitialArguments(LibraryEntry(windowsPath: profile.windowsPath))
                check(env("MADEIRA_ARGS") == "--base " + rule.arguments, "restored rule is active at launch")
            case "write-draft":
                rejects { _ = try profile.saveChildArguments(program: "Game Name.exe", arguments: "--name \"unfinished") }
            case "read-draft":
                check(profile.childArgumentsDraft?.arguments == "--name \"unfinished", "incomplete quote survives restart")
                check(ChildLaunchArguments(configuration: profile.text)?.arguments == rawArguments.trimmingCharacters(in: .whitespaces), "invalid draft does not overwrite last valid rule")
            case "write-no-program":
                rejects { _ = try profile.saveChildArguments(program: "", arguments: "--pending") }
            case "read-no-program":
                check(profile.childArgumentsDraft?.program == "" && profile.childArgumentsDraft?.arguments == "--pending", "arguments entered before program detection survive restart")
                try profile.saveChildArguments(program: "Game Name.exe", arguments: "--pending")
                check(ChildLaunchArguments(configuration: profile.text)?.arguments == "--pending", "choosing program activates pending input")
            case "clear":
                try profile.saveChildArguments(program: "Game Name.exe", arguments: "")
            case "read-clear":
                check(ChildLaunchArguments(configuration: profile.text) == nil, "clear survives restart")
                check(profile.childArgumentsDraft?.arguments == "" && profile.childArgumentsDraft?.program == "Game Name.exe", "empty input keeps chosen program")
                check(profile.text.contains("pool = 768"), "clear keeps other settings")
            case "advanced-edit":
                profile.text = "env.MADEIRA_CHILD_ARGS = other.exe --advanced\n"
            case "read-advanced":
                check(profile.childArgumentsDraft == nil, "advanced config invalidates stale draft")
                check(ChildLaunchArguments(configuration: profile.text)?.arguments == "--advanced", "advanced editor wins")
            default: fatalError("unknown test mode")
            }
            print("PASS: restart persistence \(CommandLine.arguments[2])")
            return
        }
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
        check(ChildLaunchArguments.executableName(#"C:\Games\abc.exe"#) == "abc.exe", "Windows name")
        check(ChildLaunchArguments.executableName("bin/abc.exe") == "abc.exe", "Steam relative name")
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-x\nenv.OTHER = 1") }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-name \"unclosed") }
        let spaced = try ChildLaunchArguments.replacing(in: "", program: "Game Name.exe", arguments: "--rendering-driver opengl")
        check(spaced.contains("= \"Game Name.exe\" --rendering-driver opengl"), "spaced filename is quoted")
        let spacedRule = ChildLaunchArguments(configuration: spaced)!
        check(spacedRule.program == "Game Name.exe", "quoted filename round trip")
        let preview = try spacedRule.commandPreview(executable: #"C:\Games\Game Name.exe"#, existingArguments: "--base \"Two Words\"")
        check(preview == #""C:\Games\Game Name.exe" --base "Two Words" --rendering-driver opengl"#, "full command combines existing and appended options once")
        check(ChildLaunchArguments(configuration: "env.MADEIRA_CHILD_ARGS = \"Game Name.exe\"--x") == nil, "quoted name needs separator")
        check(ChildLaunchArguments(configuration: "env.MADEIRA_CHILD_ARGS = \"Game Name.exe --x") == nil, "unclosed target quote rejected")
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: String(repeating: "a", count: 252) + ".exe", arguments: "-x") }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: String(repeating: "x", count: 4096)) }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: Array(repeating: "-x", count: 65).joined(separator: " ")) }
        rejects { _ = try ChildLaunchArguments.replacing(in: "", program: "abc.exe", arguments: "-name 中文") }

        let game = LibraryEntry(windowsPath: #"C:\Games\abc.exe"#)
        let other = LibraryEntry(windowsPath: #"C:\Games\other.exe"#)
        GameProfile(windowsPath: game.windowsPath).text = updated
        check(GameProfile(windowsPath: game.windowsPath).text == updated, "real profile round trip")
        check(GameProfile(windowsPath: other.windowsPath).text.isEmpty, "separate games")
        setenv("MADEIRA_EXE", #"C:\Games\ABC.EXE"#, 1)
        setenv("MADEIRA_ARGS", "-existing", 1)
        try BCDLaunch.appendInitialArguments(game)
        check(env("MADEIRA_ARGS") == "-existing " + rule.arguments, "initial game gets appended arguments")
        for executable in ["explorer.exe", #"C:\windows\system32\cmd.exe"#, "steam.exe", "other.exe"] {
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
    for mode in ('write-valid', 'read-valid', 'write-draft', 'read-draft', 'write-no-program',
                 'read-no-program', 'clear', 'read-clear', 'advanced-edit', 'read-advanced'):
        # Each invocation is a fresh process, with the same on-disk game profile.
        subprocess.run([str(executable), str(folder), mode], check=True)
