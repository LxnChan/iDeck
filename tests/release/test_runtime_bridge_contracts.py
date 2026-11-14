# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Compile the production synchronization bridges with small host-side stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def function(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for end in range(brace, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if not depth:
            return text[start:end + 1]
    raise AssertionError("Unterminated function: " + signature)


class RuntimeBridgeContracts(unittest.TestCase):
    def compile_run(self, program, *, objc=False, env=None):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.skipTest("A host C compiler is required; also exercised on the macOS CI runner")
        with tempfile.TemporaryDirectory(prefix="ideck-bridge-") as work:
            path = Path(work) / ("bridge.m" if objc else "bridge.c")
            executable = Path(work) / ("bridge.exe" if os.name == "nt" else "bridge")
            path.write_text(program, encoding="utf-8")
            command = [compiler, "-std=c11", "-Werror", str(path), "-o", str(executable)]
            if objc:
                command += ["-fobjc-arc", "-framework", "Foundation"]
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
            subprocess.run([str(executable)], check=True, capture_output=True,
                           text=True, timeout=10, env={**os.environ, **(env or {})})

    def test_atom_translation_boundaries_and_opt_out(self):
        text = source("build/win32u-unix/class_ios.c")
        names = ("static int ios_atom_arg_enabled(void)",
                 "static ULONG_PTR ios_atom_unrebase(", "const WCHAR *ios_atom_arg(")
        production = "\n".join(function(text, name) for name in names)
        program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uintptr_t ULONG_PTR;
typedef uint16_t WCHAR;
static ULONG_PTR base = 0x7000000000ULL;
static ULONG_PTR ios_wow_base(void) { return base; }
''' + production + r'''
int main(void) {
    ULONG_PTR values[] = {0, 1, 0xffff, 0x10000, base - 1, base,
                          base + 1, base + 0xffff, base + 0x10000,
                          base + 0x100000, 0x800000c023ULL};
    int enabled = strcmp(getenv("MADEIRA_ATOM_ARG"), "0") != 0;
    for (unsigned i = 0; i < sizeof(values) / sizeof(values[0]); i++) {
        ULONG_PTR value = values[i];
        ULONG_PTR expected = enabled && value > base && value - base < 0x10000
                             ? value - base : value;
        assert((ULONG_PTR)ios_atom_arg((const WCHAR *)value) == expected);
    }
    base = 0;
    assert((ULONG_PTR)ios_atom_arg((const WCHAR *)0x700000c023ULL) == 0x700000c023ULL);
    return 0;
}
'''
        for setting in ("0", "1"):
            with self.subTest(setting=setting):
                self.compile_run(program, env={"MADEIRA_ATOM_ARG": setting})
        self.assertIn("ios_atom_arg( name->Buffer )", text)

    def test_swap_statistics_report_file_usage_without_inventing_donors(self):
        production = function(source("build/ntdll-unix/virtual_ios.c"),
                              "void madeira_swap_overlay_stats(")
        self.compile_run(r'''
#include <assert.h>
#include <stddef.h>
static unsigned long long ios_swap_bytes;
''' + production + r'''
int main(void) {
    unsigned long long file = 99, donor = 99, pool = 99, guarded = 99;
    madeira_swap_overlay_stats(&file, &donor, &pool, &guarded);
    assert(!file && !donor && !pool && !guarded);
    ios_swap_bytes = (3ULL << 20) + 7;
    madeira_swap_overlay_stats(&file, NULL, NULL, NULL);
    assert(file == 3);
    madeira_swap_overlay_stats(NULL, NULL, NULL, NULL);
    return 0;
}
''')

    @unittest.skipUnless(sys.platform == "darwin", "The production frame bridge uses Foundation")
    def test_frame_marks_exclude_hidden_layers_and_keep_per_layer_intervals(self):
        text = source("app/Madeira/Winios/Winios.m")
        start = text.index("#define MADEIRA_FRAME_RING ")
        end = text.index("/* madeira-bcd: ONE METAL HUD LAYER", start)
        production = text[start:end]
        self.compile_run(r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <stdatomic.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>
@interface MadeiraWindowMetalLayer : NSObject
@property BOOL hidden;
- (BOOL)madeiraWindowHidden;
@end
@implementation MadeiraWindowMetalLayer
- (BOOL)madeiraWindowHidden { return self.hidden; }
@end
''' + production + r'''
int main(void) {
    @autoreleasepool {
        NSObject *visible = [NSObject new], *other = [NSObject new];
        MadeiraWindowMetalLayer *hidden = [MadeiraWindowMetalLayer new];
        hidden.hidden = YES;
        uint32_t times[8], since;
        madeira_frame_mark(NULL);
        madeira_frame_mark((__bridge const void *)hidden);
        assert(!atomic_load(&g_frame_head));
        madeira_frame_mark((__bridge const void *)visible);
        usleep(2000);
        madeira_frame_mark((__bridge const void *)other);
        usleep(2000);
        madeira_frame_mark((__bridge const void *)visible);
        assert(atomic_load(&g_frame_head) == 3);
        assert(madeira_frame_times_us(times, 8, 10000, &since) == 1);
        assert(times[0] > 0);
        assert(madeira_frame_times_us(times, 0, 10000, NULL) == 0);
    }
    return 0;
}
''', objc=True, env={"MADEIRA_FRAME_TIMES": "1"})


if __name__ == "__main__":
    unittest.main()
