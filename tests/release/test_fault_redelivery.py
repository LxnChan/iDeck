# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise the production Mach fault counter without Wine or an iOS device.

BreakQuest repeatedly decrypts/re-encrypts guest byte 0xDB304A while rendering.
Its same-PC writes used to accumulate across handled faults and normal work
until the 2,000-delivery terminal killed iDeck. A true unchanged retry loop
must still reach that threshold.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[2] / "build/ntdll-unix/signal_arm64_ios.c"

SHIM = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t thread_t;
typedef struct {
    uint64_t __x[29], __fp, __lr, __sp, __pc;
    uint32_t __cpsr, padding;
} arm_thread_state64_t;
typedef struct {
    unsigned char __v[32][16];
    uint32_t __fpsr, __fpcr;
} arm_neon_state64_t;
#define arm_thread_state64_get_pc(s) ((s).__pc)
#define arm_thread_state64_get_sp(s) ((s).__sp)
#define arm_thread_state64_get_fp(s) ((s).__fp)
#define arm_thread_state64_get_lr(s) ((s).__lr)
'''

HARNESS = r'''
static arm_thread_state64_t state;
static arm_neon_state64_t neon;
static const thread_t game = 0x64c3;
static const uintptr_t target = 0x7300db304aULL;

static unsigned deliver(thread_t thread)
{
    ios_redelivery_observe(thread, &state, &neon, 1, 1, 2, target);
    return ios_redelivery_count(thread);
}

int main(void)
{
    unsigned i;
    thread_t other;
    state.__pc = 0x173ea36f0ULL; /* stlrb w7, [x24] */
    state.__x[24] = target;
    state.__sp = 0x7065f3e100ULL;

    /* The terminal still sees 2,000 truly consecutive unchanged contexts. */
    for (i = 1; i <= 2000; i++) assert(deliver(game) == i);

    /* Same store PC/address, alternating decrypted/ciphertext source byte. */
    for (i = 0; i < 4000; i++)
    {
        state.__x[7] = (i & 1) ? 0xb1 : 0x90;
        assert(deliver(game) == 1);
    }

    /* Even the identical recurring write is not consecutive if the Mach
     * handler serviced another access in between (e.g. an unaligned load). */
    for (i = 0; i < 4000; i++)
    {
        arm_thread_state64_t load = state;
        load.__pc += 16;
        ios_redelivery_observe(game, &load, &neon, 1, 1, 1, target + 0x1000);
        assert(deliver(game) == 1);
    }

    /* A fault completed in place, or serviced by Wine page machinery, also
     * breaks the run even when the next fault has exactly the same state. */
    for (i = 0; i < 4000; i++)
    {
        ios_redelivery_serviced(game);
        assert(deliver(game) == 1);
    }

    /* Progress in any integer/control/vector register breaks the run. */
    for (i = 0; i < 29; i++) { state.__x[i]++; assert(deliver(game) == 1); }
    state.__fp++; assert(deliver(game) == 1);
    state.__lr++; assert(deliver(game) == 1);
    state.__sp++; assert(deliver(game) == 1);
    state.__pc++; assert(deliver(game) == 1);
    state.__cpsr ^= 0x20000000; assert(deliver(game) == 1);
    for (i = 0; i < 32; i++) { neon.__v[i][15]++; assert(deliver(game) == 1); }
    neon.__fpsr++; assert(deliver(game) == 1);
    neon.__fpcr++; assert(deliver(game) == 1);

    /* Ignore ABI padding; do not turn a real loop into differing contexts. */
    state.padding++;
    assert(deliver(game) == 2);

    /* A different fault kind/code or destination cannot continue the run. */
    ios_redelivery_observe(game, &state, &neon, 1, 2, 2, target);
    assert(ios_redelivery_count(game) == 1);
    assert(deliver(game) == 1);
    ios_redelivery_observe(game, &state, &neon, 1, 1, 1, target);
    assert(ios_redelivery_count(game) == 1);
    assert(deliver(game) == 1);
    ios_redelivery_observe(game, &state, &neon, 1, 1, 2, target + 1);
    assert(ios_redelivery_count(game) == 1);
    assert(deliver(game) == 1);

    /* Failed NEON reads never inspect the supplied buffer. */
    ios_redelivery_observe(game, &state, 0, 0, 1, 2, target);
    assert(ios_redelivery_count(game) == 1);
    ios_redelivery_observe(game, &state, 0, 0, 1, 2, target);
    assert(ios_redelivery_count(game) == 2);
    assert(deliver(game) == 1);

    /* Other threads' progress does not mask this thread's real retry loop. */
    for (other = 1; ios_redelivery_entry(other) == ios_redelivery_entry(game); other++);
    for (i = 2; i <= 2000; i++)
    {
        deliver(other);
        ios_redelivery_serviced(other);
        assert(deliver(game) == i);
    }

    /* A colliding slot must not inherit another thread's terminal count. */
    for (other = game + 1; ios_redelivery_entry(other) != ios_redelivery_entry(game); other++);
    assert(deliver(other) == 1);
    assert(deliver(game) == 1);
    return 0;
}
'''


class FaultRedelivery(unittest.TestCase):
    def test_production_counter_distinguishes_progress_from_retry(self):
        compiler = shutil.which("clang") or shutil.which("cc") or shutil.which("cl")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        source = SOURCE.read_text(encoding="utf-8")
        start = source.index("static struct ios_redelivery_entry\n")
        end = source.index("static void *ios_mach_exception_thread(", start)
        with tempfile.TemporaryDirectory(prefix="ideck-redelivery-") as directory:
            work = Path(directory)
            cfile = work / "counter.c"
            binary = work / ("counter.exe" if os.name == "nt" else "counter")
            cfile.write_text(SHIM + source[start:end] + HARNESS, encoding="utf-8")
            if Path(compiler).stem.lower() == "cl":
                command = [compiler, "/nologo", "/std:c11", "/W4", "/WX",
                           str(cfile), "/Fe:" + str(binary)]
            else:
                command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                           str(cfile), "-o", str(binary)]
            built = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], cwd=work, capture_output=True, text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_counter_observes_before_handlers_and_counts_at_delivery(self):
        source = SOURCE.read_text(encoding="utf-8")
        loop = source[source.index("static void *ios_mach_exception_thread("):]
        self.assertLess(loop.index("ios_redelivery_observe( thread, &state,"),
                        loop.index("/* ml939:"))
        self.assertLess(loop.index("if (handled) ios_redelivery_serviced( thread );"),
                        loop.index("if (ios_mach_deliver_guest_exception( thread, &state,"))
        self.assertIn("if (r == 2) ios_redelivery_serviced( thread );", source)
        self.assertIn("if (is_align) ios_redelivery_serviced( thread );", source)
        self.assertIn("unsigned n = ios_redelivery_count( thread );", source)
        self.assertIn("else if (n >= 2000 && !ios_redeliv_terminating)", source)


if __name__ == "__main__":
    unittest.main()
