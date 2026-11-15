#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Check the real Steam load policy, settings placement and installed build label.

No Valve binaries, network requests, device accounts or private logs are needed.
The macOS build job must execute both compiled harnesses; other hosts may skip
them when the corresponding compiler is not installed.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
library = (ROOT / 'app/Madeira/Library.swift').read_text(encoding='utf-8')
launch = (ROOT / 'app/Madeira/ContentView.swift').read_text(encoding='utf-8')
loader = (ROOT / 'build/ntdll-unix/loader_ios.c').read_text(encoding='utf-8')
workflow = (ROOT / '.github/workflows/build-ipa.yml').read_text(encoding='utf-8')
historical = (ROOT / 'tools/build/build-runtime223.py').read_text(encoding='utf-8')

settings = library[library.index('Toggle("Open Steam automatically"'):library.index('// Credits, last on the Settings page.')]
assert settings.count('Text("Diagnostics")') == 1
assert 'Text("Appearance")' not in library and 'Text("Interface")' not in library
assert settings.index('SettingsSearchResults(') < settings.index('Toggle("Extended logging"')
assert 'Section {' not in settings[settings.index('Text("Diagnostics")'):]
for option in ('Extended logging', 'Liquid metal', 'Use developer interface'):
    assert settings.count(f'Toggle("{option}"') == 1
assert 'FrontendChoice.choose(new: !on); restartNotice = true' in settings
assert 'Toggle("Disable crashhandler64.dll"' in settings
assert 'MadeiraConfig.set("env.MADEIRA_DISABLE_STEAM_CRASHHANDLER", on ? "1" : "0")' in settings
assert 'wine_process_is_running() != 0 || wineserver_is_running() != 0' in settings
assert 'On by default, for Steam/Dock launches only; DLL files are unchanged.' in settings
assert 'IDeckSteamCrashHandlerPolicySupported' in settings
assert "info['IDeckSteamCrashHandlerPolicySupported'] = False" in historical
assert 'historical diagnostic runtime does not support' in settings
assert 'if dockLaunch.dock || steamUI { setenv("MADEIRA_STEAM_CLIENT_SESSION", "1", 1) }' in launch
assert 'else { unsetenv("MADEIRA_STEAM_CLIENT_SESSION") }' in launch
assert 'setenv("MADEIRA_DISABLE_STEAM_CRASHHANDLER", MadeiraConfig.flag(' in launch
assert 'env.' in (ROOT / 'app/Madeira/WineProcessBridge.m').read_text(encoding='utf-8')

# Every Wine load-order query in this iOS adapter goes through the new gate,
# including native PE mapping and explicit paths. Existing overrides still run.
policy = loader[loader.index('static enum loadorder ideck_module_load_order('):loader.index('#if defined __i386__')]
assert loader.count('get_load_order(') == 1  # Only the wrapper's fallback.
assert loader.count('ideck_module_load_order(') == 5  # Definition + four callers.
assert 'return get_load_order( name );' in policy
assert 'blocked' in policy and 'allowed by setting' in policy
assert "'build/ntdll-unix/'" in (ROOT / 'tools/build/runtime-input-key.py').read_text(encoding='utf-8')
assert 'Add :IDeckSourceCommit string $GITHUB_SHA' in workflow
assert "info['IDeckSourceCommit'] = git(ROOT, 'rev-parse', 'HEAD')" in historical
assert 'Text(LibraryBuildIdentity.current)' in library
assert '.font(.title2.bold())' in library and 'withTextStyle: .title2' in library
print('PASS: settings placement, persistence, session isolation, runtime support, cache inputs and build stamp')


def compiler(name):
    found = shutil.which(name)
    if not found:
        if sys.platform == 'darwin' or os.environ.get('GITHUB_ACTIONS') == 'true':
            raise RuntimeError(f'{name} is required for the CI regression test')
        print(f'SKIP: {name} not installed; compiled checks run in macOS CI')
    return found


c_harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "steam_crashhandler_policy.h"
#define WINE_IOS 1
typedef uint16_t WCHAR;
typedef struct { unsigned short Length; WCHAR *Buffer; } UNICODE_STRING;
enum loadorder { LO_DISABLED, LO_NATIVE_BUILTIN };
static int fallback_calls;
static enum loadorder get_load_order(const UNICODE_STRING *name) {
    (void)name; fallback_calls++; return LO_NATIVE_BUILTIN;
}
'''
c_test = r'''
static enum loadorder check(const char *path) {
    WCHAR units[512]; size_t i, length = strlen(path);
    assert(length < 512);
    for (i = 0; i < length; i++) units[i] = (unsigned char)path[i];
    /* Deliberately no NUL: production receives a counted UNICODE_STRING. */
    UNICODE_STRING name = { (unsigned short)(length * sizeof(WCHAR)), units };
    return ideck_module_load_order(&name);
}
int main(void) {
    unsetenv("MADEIRA_STEAM_CLIENT_SESSION");
    unsetenv("MADEIRA_DISABLE_STEAM_CRASHHANDLER");
    assert(check("crashhandler64.dll") == LO_NATIVE_BUILTIN);
    for (const char **s = (const char *[]){"", "0", "true", "2", NULL}; *s; s++) {
        setenv("MADEIRA_STEAM_CLIENT_SESSION", *s, 1);
        assert(check("crashhandler64.dll") == LO_NATIVE_BUILTIN);
    }
    setenv("MADEIRA_STEAM_CLIENT_SESSION", "1", 1);
    const char *targets[] = {"crashhandler64.dll", "CRASHHANDLER64.DLL",
        "crashhandler64", "\\??\\C:\\Program Files (x86)\\Steam\\crashhandler64.dll",
        "C:/Steam/CrAsHhAnDlEr64.DlL", NULL};
    for (const char **s = targets; *s; s++) assert(check(*s) == LO_DISABLED);
    const char *other[] = {"", "crashhandler.dll", "crashhandler64.dll.disabled",
        "mycrashhandler64.dll", "crashhandler64.dll/other.dll", "steamclient64.dll",
        "crashhandler64.", "crashhandler64.dl", "crashhandler64.dllx", NULL};
    for (const char **s = other; *s; s++) assert(check(*s) == LO_NATIVE_BUILTIN);
    assert(!ideck_block_steam_crashhandler(NULL, 17, 1, 1));
    const uint16_t unicode[] = {0x263a, '\\', 'C', 'R', 'A', 'S', 'H', 'H', 'A', 'N', 'D', 'L', 'E', 'R', '6', '4'};
    assert(ideck_block_steam_crashhandler(unicode, 16, 1, 1));
    assert(!ideck_block_steam_crashhandler(unicode, 16, 0, 1));
    assert(!ideck_block_steam_crashhandler(unicode, 16, 1, 0));
    /* The switch is read afresh, not cached by Wine's override parser. */
    for (int i = 0; i < 3; i++) {
        setenv("MADEIRA_DISABLE_STEAM_CRASHHANDLER", "0", 1);
        assert(check("crashhandler64.dll") == LO_NATIVE_BUILTIN);
        setenv("MADEIRA_DISABLE_STEAM_CRASHHANDLER", "1", 1);
        assert(check("crashhandler64.dll") == LO_DISABLED);
    }
    unsetenv("MADEIRA_STEAM_CLIENT_SESSION");
    assert(check("crashhandler64.dll") == LO_NATIVE_BUILTIN);
    assert(fallback_calls > 0);
    puts("PASS: real C load-order gate, default/on/off, full paths, counted UTF-16 and desktop isolation");
}
'''

identity = library[library.index('enum LibraryBuildIdentity {'):library.index('\n/// Two compact lines')]
swift_test = r'''
let full = "ABCDEF0" + String(repeating: "1", count: 33)
assert(LibraryBuildIdentity.label(["CFBundleShortVersionString": "0.1.3", "CFBundleVersion": "237",
    "IDeckSourceCommit": full]) == "v0.1.3 (237) · abcdef0")
assert(LibraryBuildIdentity.label([:]) == "vunknown (unknown) · local")
for bad in ["", "123456", "ggggggg", full + "a", " abcdef0", "abcdef0\n"] {
    assert(LibraryBuildIdentity.label(["IDeckSourceCommit": bad]).hasSuffix(" · local"))
}
assert(LibraryBuildIdentity.label(["IDeckSourceCommit": "123abcd"]).hasSuffix(" · 123abcd"))
assert(LibraryBuildIdentity.label(["CFBundleVersion": 237, "IDeckSourceCommit": false]).hasSuffix("(unknown) · local"))
print("PASS: installed version/build/commit identity, invalid metadata and local fallback")
'''

with tempfile.TemporaryDirectory(prefix='ideck-steam-crashhandler-') as directory:
    directory = Path(directory)
    clang = compiler('clang')
    if clang:
        source = directory / 'policy.c'
        source.write_text(c_harness + policy + c_test, encoding='utf-8')
        binary = directory / 'policy-check'
        subprocess.run([clang, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-I', str(ROOT / 'build/ntdll-unix'),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    swiftc = compiler('swiftc')
    if swiftc:
        source = directory / 'main.swift'
        source.write_text('import Foundation\n' + identity + swift_test, encoding='utf-8')
        binary = directory / 'identity-check'
        subprocess.run([swiftc, '-module-cache-path', str(directory / 'module-cache'),
                        str(source), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
