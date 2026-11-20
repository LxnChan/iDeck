# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Run Wine's fault-repair policy against 4KB guest / 16KB host mappings.

CoreCLR patches precodes in logically writable JIT aliases that must remain
physically RX. A generic repair must not untrap these pages or their neighbours.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
VIRTUAL = ROOT / "build/ntdll-unix/virtual_ios.c"
SIGNAL = ROOT / "build/ntdll-unix/signal_arm64_ios.c"

SHIM = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
typedef unsigned char BYTE;
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4
#define ROUND_ADDR(addr, mask) ((void *)((uintptr_t)(addr) & ~(uintptr_t)(mask)))
static size_t host_page_size, host_page_mask;
static const unsigned page_shift = 12;
static uintptr_t guest_base = 0x718c2a8000ULL;
static BYTE pages[4];
static struct { uintptr_t user_va, user_va_end; } ios_jit_anon_aliases[1];
static int ios_jit_anon_alias_count;

static BYTE get_page_vprot(const void *addr)
{
    uintptr_t offset = (uintptr_t)addr - guest_base;
    assert(offset < host_page_size);
    return pages[offset >> page_shift];
}
'''

HARNESS = r'''
static void reset(BYTE vprot)
{
    unsigned i;
    for (i = 0; i < 4; i++) pages[i] = vprot;
    ios_jit_anon_alias_count = 0;
}

static int repair_at(unsigned page)
{
    return ios_page_fault_repair_prot((void *)(guest_base + page * 0x1000 + 0xd38));
}

int main(void)
{
    const BYTE rw = VPROT_COMMITTED | VPROT_READ | VPROT_WRITE;
    const BYTE ro = VPROT_COMMITTED | VPROT_READ;
    unsigned i, j, count;

    /* The policy works for both native 4KB and iOS 16KB host pages. */
    for (host_page_size = 0x1000; host_page_size <= 0x4000; host_page_size *= 4)
    {
        host_page_mask = host_page_size - 1;
        count = (unsigned)(host_page_size >> page_shift);
        reset(rw);
        assert(repair_at(0) == (PROT_READ | PROT_WRITE));
        reset(ro);
        assert(repair_at(0) == PROT_READ);
        reset(VPROT_COMMITTED | VPROT_WRITECOPY);
        assert(repair_at(0) == (PROT_READ | PROT_WRITE));

        for (i = 0; i < count; i++)
        {
            /* All logical R/W/X combinations with EXEC stay with the code
             * handler, whether the alias has been registered yet or not. */
            for (j = 0; j < 4; j++)
            {
                reset(rw);
                pages[i] = VPROT_COMMITTED | VPROT_EXEC | (BYTE)j;
                assert(repair_at(0) == -1);
            }

            /* Even a currently non-executable RW alias owns its physical
             * protection. Check overlap anywhere in the host page. */
            reset(rw);
            ios_jit_anon_alias_count = 1;
            ios_jit_anon_aliases[0].user_va = guest_base + i * 0x1000;
            ios_jit_anon_aliases[0].user_va_end = guest_base + (i + 1) * 0x1000;
            assert(repair_at(0) == -1);
            assert(repair_at(count - 1) == -1);

            /* Read recovery cannot grant WRITE to a readonly / write-watch
             * neighbour, or READ to a guard, uncommitted or no-access page. */
            reset(rw);
            pages[i] = ro;
            assert(repair_at(0) == PROT_READ);
            pages[i] = rw | VPROT_WRITEWATCH;
            assert(repair_at(0) == PROT_READ);
            pages[i] = rw | VPROT_GUARD;
            assert(repair_at(0) == PROT_NONE);
            pages[i] = VPROT_COMMITTED;
            assert(repair_at(0) == PROT_NONE);
            pages[i] = 0;
            assert(repair_at(0) == -1);
        }

        /* An adjacent alias must not disable recovery of this data page. */
        reset(rw);
        ios_jit_anon_alias_count = 1;
        ios_jit_anon_aliases[0].user_va = guest_base + host_page_size;
        ios_jit_anon_aliases[0].user_va_end = guest_base + host_page_size * 2;
        assert(repair_at(0) == (PROT_READ | PROT_WRITE));
        ios_jit_anon_aliases[0].user_va = guest_base - host_page_size;
        ios_jit_anon_aliases[0].user_va_end = guest_base;
        assert(repair_at(0) == (PROT_READ | PROT_WRITE));
    }
    host_page_size = 0;
    assert(ios_page_fault_repair_prot((void *)guest_base) == -1);
    return 0;
}
'''


def function(source, signature):
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


class FaultPageRepair(unittest.TestCase):
    def test_production_policy_preserves_code_and_neighbour_permissions(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        source = VIRTUAL.read_text(encoding="utf-8")
        flags = source[source.index("#define VPROT_READ "):
                       source.index("/* per-mapping protection flags */")]
        production = "".join(function(source, name) for name in (
            "int ios_jit_anon_alias_overlaps(",
            "static int get_unix_prot(",
            "int ios_page_expected_prot(",
            "int ios_page_fault_repair_prot(",
        ))
        with tempfile.TemporaryDirectory(prefix="ideck-page-repair-") as directory:
            work = Path(directory)
            cfile = work / "repair.c"
            binary = work / ("repair.exe" if os.name == "nt" else "repair")
            cfile.write_text(SHIM + flags + production + HARNESS, encoding="utf-8")
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(cfile), "-o", str(binary)],
                cwd=work, capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], cwd=work, capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_both_signal_repair_paths_use_the_page_policy(self):
        source = SIGNAL.read_text(encoding="utf-8")
        start = source.index("if (rd_kr == KERN_SUCCESS)", source.index("static void bus_handler("))
        end = source.index("/* unreadable target = an access violation", start)
        repair = source[start:end]
        self.assertEqual(repair.count("ios_page_fault_repair_prot( siginfo->si_addr )"), 2)
        self.assertIn("repair >= 0 && (repair & PROT_WRITE)", repair)
        self.assertIn("mprotect( hp, WR_HPAGE, repair )", repair)
        self.assertIn("if (want > 0 && (want & PROT_READ))", repair)


if __name__ == "__main__":
    unittest.main()
