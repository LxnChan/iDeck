#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Per-game offline UI/wiring plus real Swift and bridge-policy regressions.

No Steam, private logs or device account is used. macOS CI must compile and run
the production excerpts; hosts without the compilers report the boundary.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / 'app/Madeira'
library = (APP / 'Library.swift').read_text(encoding='utf-8')
games = (APP / 'SteamGames.swift').read_text(encoding='utf-8')
dock = (APP / 'MadeiraDock.swift').read_text(encoding='utf-8')
owned = (APP / 'SteamOwnedLibrary.swift').read_text(encoding='utf-8')
content = (APP / 'ContentView.swift').read_text(encoding='utf-8')
bridge = (APP / 'WineProcessBridge.m').read_text(encoding='utf-8')


def block(source, start):
    begin = source.index(start)
    opening = source.index('{', begin)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[begin:end]


# The detail sheet binds its local entry and already saves it on Play/Done/dismiss.
section = block(games, 'struct SteamEntrySection: View')
toggle = section.index('Toggle("Launch offline"')
assert section.index('if direct {') < section.index('} else {\n                if !dock.clientInstalled') < toggle
assert 'get: { entry.steamOffline == true }' in section
assert 'set: { entry.steamOffline = $0 ? true : nil }' in section
assert '.disabled(!DockOffline.enabled && entry.steamOffline != true)' in section
detail = block(library, 'struct LibraryDetail: View')
assert 'SteamEntrySection(entry: $entry' in detail
assert '.onDisappear { if !leaving { model.save(entry) } }' in detail
assert 'model.save(entry)' in detail
start = block(content, 'private func startDock(')
assert 'let offline = profile?.steamOffline == true' in start
assert start.index('guard !offline || DockOffline.enabled') < start.index('guard cloudConfirmed || cloudClear(')
assert 'name: game.name, offline: offline' in start
assert 'launchOptions(appID: game.id, cachedOnly: offline)' in start
assert 'MadeiraDock.configure(game, launchOption: launchOption, forceOffline: offline)' in start
assert 'SteamSignIn.isSignedIn' in start and 'SteamSignIn.credentialsForDock()' in start
assert 'MadeiraDock.writeHandoff(' in start  # Offline never bypasses the real client.
assert 'DockOffline.configure(appID: game.id, forceOffline: forceOffline)' in dock
worker = block(content, 'private func runWineFullSequence(')
assert worker.index('profile.applyEnvironment()') < worker.index('DockOffline.prepareLaunch(')
assert worker.index('let dockHasHost = !DockInstallers.installsOnly') < worker.index('DispatchQueue.global(')
assert 'dock: dockLaunch.dock && dockHasHost' in worker
assert 'forceOffline: profile?.steamOffline == true' in worker
cleanup = block(dock, '@MainActor static func cleanup()')
assert 'unsetenv("MADEIRA_DOCK_FORCE_OFFLINE")' in cleanup
assert 'unsetenv("MADEIRA_DOCK_OFFLINE")' in cleanup
assert 'cloudHold(appID, offline: offline)' in block(content, 'private func cloudClear(')
assert 'fields["session-offline-requested"] == nil' in dock

# Snapshot before ANY env exports; enforce after BOTH global and per-game exports.
snapshot = bridge[bridge.index('const char *offlineChoice ='):bridge.index('NSString *text = nil;', bridge.index('const char *offlineChoice ='))]
enforce = block(bridge, 'if (forceDockOffline)')
assert bridge.index(snapshot) < bridge.index('setenv(k.UTF8String, v.UTF8String, 1);')
assert bridge.index(enforce) > bridge.index('LOG("game config env:')
print('PASS: per-game switch, persistence wiring, offline preflight, licence checks and final env precedence')

# Real stored fields, including synthesized Codable, with only UI-only types stubbed.
fields = library[library.index('struct LibraryEntry: Codable, Identifiable {'):library.index('    var gameConfigText:')]
offline = dock[dock.index('enum DockOffline {'):]
cloud_hold = block(owned, 'enum CloudHold: Equatable')
hold_method = block(owned, 'func cloudHold(')
options_method = block(owned, 'func launchOptions(')
swift = r'''
import Foundation
#if canImport(Glibc)
import Glibc
#else
import Darwin
#endif
enum ResolutionChoices { static let defaultValue = "1280x720" }
struct TouchControl: Codable {}
struct ControlAction: Codable {}
enum SteamSignIn {
    static func flag(_ key: String, default fallback: Bool) -> Bool {
        getenv(key).map { String(cString: $0) != "0" } ?? fallback
    }
}
enum SteamLog { static func event(_ text: String) {} }
final class NWPathMonitor {
    struct Path { enum Status { case satisfied, unsatisfied }; var status = Status.satisfied }
    var currentPath = Path()
    func start(queue: DispatchQueue) {}
}
struct SteamLaunchOption { var index: UInt32? }
struct Game { var id: Int; var launches: [SteamLaunchOption]? }
struct AppInfo { var launches: [SteamLaunchOption] }
final class Fetcher {
    var calls = 0
    func fetchAppInfo(appID: UInt32) async throws -> AppInfo? {
        calls += 1
        return AppInfo(launches: [SteamLaunchOption(index: 7)])
    }
}
final class TestLibrary {
    static let enabled = true, cloudPlayCheck = true
    static let cloudNoFolders = "no folders"
    static let cloudFresh: TimeInterval = 600
    var signedIn = true, inSession = false
    var cloudBusy = Set<Int>()
    enum Phase { case checking, downloading, uploading, ready, failed(String) }
    struct State {
        var phase = Phase.ready
        var problem: String?
        var conflicts: [Int] = []
        var checked: Date?
    }
    var cloud: [Int: State] = [:]
    var owned: [Game] = []
    let fetcher = Fetcher()
    func game(_ id: Int) -> Game? { owned.first { $0.id == id } }
    func writeCache() {}
    func handleSessionError(_ error: Error, context: String, report: Bool) {}
'''
swift += cloud_hold + '\n' + hold_method + '\n' + options_method + '\n}\n'
swift += fields + '\n}\n' + offline
swift += r'''
func env(_ key: String) -> String? { getenv(key).map { String(cString: $0) } }
@main struct Checks {
    static func main() async throws {
        if CommandLine.arguments.contains("--disabled") {
            assert(!DockOffline.enabled)
            DockOffline.configure(appID: 42, forceOffline: true)
            assert(env("MADEIRA_DOCK_OFFLINE") == nil)
            DockOffline.prepareLaunch(dock: true, forceOffline: true)
            assert(env("MADEIRA_DOCK_FORCE_OFFLINE") == "0")
            print("PASS: global offline disable is respected")
            return
        }
        // Older library files omit this key; it stays absent when switched off.
        let original = LibraryEntry(title: "Fixture", relativePath: "Games/fixture", bits: 64)
        let encoder = JSONEncoder(), decoder = JSONDecoder()
        let old = try encoder.encode(original)
        assert(!String(decoding: old, as: UTF8.self).contains("steamOffline"))
        var entry = try decoder.decode(LibraryEntry.self, from: old)
        assert(entry.steamOffline == nil)
        entry.steamOffline = true
        let saved = try encoder.encode(entry)
        let restored = try decoder.decode(LibraryEntry.self, from: saved)
        assert(restored.steamOffline == true)
        entry.steamOffline = nil
        let off = try encoder.encode(entry)
        assert(!String(decoding: off, as: UTF8.self).contains("steamOffline"))
        for enabled in [false, true] {
            for down in [false, true] {
                for force in [false, true] {
                    assert(DockOffline.requestsOffline(enabled: enabled, networkDown: down, forceOffline: force)
                           == (enabled && (down || force)))
                }
            }
        }
        DockOffline.configure(appID: 42, forceOffline: true)
        assert(env("MADEIRA_DOCK_OFFLINE") == "1")
        DockOffline.configure(appID: 43)
        assert(env("MADEIRA_DOCK_OFFLINE") == nil) // No stale choice for another game.
        DockOffline.prepareLaunch(dock: true, forceOffline: true)
        assert(env("MADEIRA_DOCK_FORCE_OFFLINE") == "1")
        DockOffline.prepareLaunch(dock: true, forceOffline: false)
        assert(env("MADEIRA_DOCK_FORCE_OFFLINE") == "0")
        setenv("MADEIRA_DOCK_OFFLINE", "1", 1)
        DockOffline.prepareLaunch(dock: false, forceOffline: true)
        assert(env("MADEIRA_DOCK_OFFLINE") == nil)
        assert(env("MADEIRA_DOCK_FORCE_OFFLINE") == "0")
        let lib = TestLibrary()
        assert(lib.cloudHold(42) == .stale)
        assert(lib.cloudHold(42, offline: true) == nil)
        lib.cloud[42] = .init()
        assert(lib.cloudHold(42) == .stale)
        assert(lib.cloudHold(42, offline: true) == nil)
        lib.cloud[42]?.problem = "unreachable"
        assert(lib.cloudHold(42, offline: true) == nil)
        lib.cloud[42]?.conflicts = [1, 2]
        assert(lib.cloudHold(42, offline: true) == .conflict(2))
        lib.cloud[42]?.phase = .downloading
        assert(lib.cloudHold(42, offline: true) == .syncing)
        lib.cloud[42]?.phase = .failed("unreachable")
        assert(lib.cloudHold(42, offline: true) == .conflict(2))
        lib.cloudBusy.insert(43)
        assert(lib.cloudHold(43, offline: true) == .syncing)
        let missing = await lib.launchOptions(appID: 42, cachedOnly: true)
        assert(missing == nil && lib.fetcher.calls == 0)
        lib.owned = [.init(id: 42, launches: [.init(index: 7)])]
        let cached = await lib.launchOptions(appID: 42, cachedOnly: true)
        assert(cached?.first?.index == 7 && lib.fetcher.calls == 0)
        lib.owned[0].launches = [.init(index: nil)]
        let legacy = await lib.launchOptions(appID: 42, cachedOnly: true)
        assert(legacy == nil && lib.fetcher.calls == 0)
        let online = await lib.launchOptions(appID: 42)
        assert(online?.first?.index == 7 && lib.fetcher.calls == 1)
        print("PASS: real Swift Codable, offline policy, session isolation, Cloud safety and cache-only metadata")
    }
}
'''

c_test = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL;
static void launch(const char *choice) {
    setenv("MADEIRA_DOCK_FORCE_OFFLINE", choice, 1);
'''
c_test += snapshot
c_test += r'''
    /* Simulate contradictory global/per-game exports after the snapshot. */
    setenv("MADEIRA_DOCK_FORCE_OFFLINE", "0", 1);
    setenv("MADEIRA_DOCK_OFFLINE", "0", 1);
    setenv("MADEIRA_DOCK_OFFLINE_LOGON", "0", 1);
'''
c_test += enforce
c_test += r'''
}
int main(void) {
    launch("1");
    assert(!strcmp(getenv("MADEIRA_DOCK_OFFLINE"), "1"));
    assert(!strcmp(getenv("MADEIRA_DOCK_OFFLINE_LOGON"), "1"));
    launch("0");
    assert(!strcmp(getenv("MADEIRA_DOCK_OFFLINE"), "0"));
    assert(!strcmp(getenv("MADEIRA_DOCK_OFFLINE_LOGON"), "0"));
    puts("PASS: real bridge enforces only the explicit offline choice after config exports");
}
'''

with tempfile.TemporaryDirectory(prefix='ideck-offline-launch-') as temporary:
    directory = Path(temporary)
    for name, source, flags in [
        ('swiftc', swift, ['-parse-as-library', '-swift-version', '5']),
        ('clang', c_test, ['-x', 'c', '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                           '-Wall', '-Wextra', '-Werror']),
    ]:
        compiler = shutil.which(name)
        if not compiler:
            if sys.platform == 'darwin' or os.environ.get('GITHUB_ACTIONS') == 'true':
                raise RuntimeError(f'{name} required for the CI regression test')
            print(f'SKIP: {name} unavailable; compiled checks run in macOS CI')
            continue
        path = directory / ('main.swift' if name == 'swiftc' else 'policy.c')
        path.write_text(source, encoding='utf-8')
        executable = directory / f'{name}-check'
        subprocess.run([compiler, *flags, str(path), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
        if name == 'swiftc':
            subprocess.run([str(executable), '--disabled'], check=True,
                           env=dict(os.environ, MADEIRA_DOCK_OFFLINE_LOGON='0'))
