# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise alias stores against Wine's real logical protection policy.

The callback fixture uses the six stores from CoreCLR 6's UMEntryThunk emitter.
Its small translation-cache model exposes a missed SMC trap without requiring
an iOS device or changing FEX sources.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_fault_page_repair import function


ROOT = Path(__file__).resolve().parents[2]
SIGNAL = ROOT / "build/ntdll-unix/signal_arm64_ios.c"
VIRTUAL = ROOT / "build/ntdll-unix/virtual_ios.c"

SHIM = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
typedef unsigned char BYTE;
#define PROT_NONE 0
#define PROT_READ 1
#define PROT_WRITE 2
#define PROT_EXEC 4
static uintptr_t guest_base = 0x718c1a3000ULL;
static const size_t host_page_size = 0x4000;
static BYTE bucket[4];
static BYTE *pages;
static BYTE get_page_vprot(const void *addr)
{
    uintptr_t offset = (uintptr_t)addr - guest_base;
    assert(offset < host_page_size);
    return pages[offset >> 12];
}
'''

HARNESS = r'''
#include <string.h>

static unsigned char thunk[23];
static uint64_t cached_target;
static unsigned invalidations, stores;
static const uint64_t prestub = 0x71ebd10000ULL + 0x15d330;
static const uint64_t callback = 0x718c2d2270ULL;

static void set_page(BYTE vprot)
{
    pages = bucket;
    pages[0] = vprot;
}

/* A translated callback keeps its decoded target until the write trap is
 * dispatched to the SMC owner. The owner invalidates, then restores WRITE;
 * the alias emulator retries without changing the RX mapping itself. */
static void emit(unsigned offset, uint64_t value, unsigned width)
{
    if (!ios_mach_alias_store_allowed(0, guest_base + 0x64 + offset))
    {
        assert(!(pages[0] & VPROT_WRITE));
        cached_target = 0;
        ++invalidations;
        pages[0] |= VPROT_WRITE;
        assert(ios_mach_alias_store_allowed(0, guest_base + 0x64 + offset));
    }
    memcpy(thunk + offset, &value, width);
    ++stores;
}

static void emit_callback(void)
{
    /* UMEntryThunkCode::Encode: mov r10, self; mov rax, target; jmp rax. */
    emit(0, 0xba49, 2);
    emit(2, 0x718c1a3040ULL, 8);
    emit(10, 0xb848, 2);
    emit(12, callback, 8);
    emit(20, 0xff48, 2);
    emit(22, 0xe0, 1);
}

int main(void)
{
    const BYTE rwx = VPROT_COMMITTED | VPROT_READ | VPROT_WRITE | VPROT_EXEC;
    unsigned flags, calls;

    /* All logical R/W/X combinations, and guard/write-watch restrictions.
     * Native pool buffers may have no Wine guest view at all. */
    for (flags = 0; flags < 8; ++flags)
    {
        int writable = (flags & VPROT_WRITE) != 0;
        set_page(VPROT_COMMITTED | flags);
        assert(!!ios_mach_alias_store_allowed(0, guest_base) == writable);
        assert(ios_mach_alias_store_allowed(1, 0));
        set_page(VPROT_COMMITTED | flags | VPROT_GUARD);
        assert(!ios_mach_alias_store_allowed(0, guest_base));
        set_page(VPROT_COMMITTED | flags | VPROT_WRITEWATCH);
        assert(!ios_mach_alias_store_allowed(0, guest_base));
        set_page(flags); /* -1 (uncommitted) must not pass a bitwise WRITE test */
        assert(!ios_mach_alias_store_allowed(0, guest_base));
    }
    set_page(VPROT_COMMITTED | VPROT_WRITECOPY);
    assert(ios_mach_alias_store_allowed(0, guest_base));

    /* Neighbouring 4KB logical pages share a 16KB physical RX page. Check
     * the addressed page rather than their host-page permission union. */
    set_page(rwx);
    pages[1] = rwx & ~VPROT_WRITE;
    pages[2] = rwx;
    pages[3] = VPROT_COMMITTED | VPROT_GUARD;
    assert(ios_mach_alias_store_allowed(0, guest_base));
    assert(!ios_mach_alias_store_allowed(0, guest_base + 0x1000));
    assert(ios_mach_alias_store_allowed(0, guest_base + 0x2000));
    assert(!ios_mach_alias_store_allowed(0, guest_base + 0x3000));

    /* Original reproduction: compile the initial callback, then patch it.
     * Without the logical permission gate the bytes change but every call
     * re-enters the cached prestub and emits the same six stores forever. */
    memcpy(thunk + 12, &prestub, 8);
    for (calls = 0; calls < 4; ++calls)
    {
        if (!cached_target)
        {
            memcpy(&cached_target, thunk + 12, 8);
            set_page(rwx & ~VPROT_WRITE); /* translator arms SMC */
        }
        if (cached_target == callback) break;
        assert(cached_target == prestub);
        emit_callback();
    }
    assert(calls == 1);
    assert(invalidations == 1);
    assert(stores == 6);
    assert(thunk[0] == 0x49 && thunk[1] == 0xba);
    assert(thunk[20] == 0x48 && thunk[21] == 0xff && thunk[22] == 0xe0);
    return 0;
}
'''


class JitAliasWriteTraps(unittest.TestCase):
    def test_logical_protections_and_callback_cache(self):
        compiler = shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        virtual = VIRTUAL.read_text(encoding="utf-8")
        signal = SIGNAL.read_text(encoding="utf-8")
        flags = virtual[virtual.index("#define VPROT_READ "):
                        virtual.index("/* per-mapping protection flags */")]
        production = (function(virtual, "static int get_unix_prot(") +
                      function(virtual, "int ios_page_expected_prot(") +
                      function(signal, "static int ios_mach_alias_store_allowed("))
        with tempfile.TemporaryDirectory(prefix="ideck-alias-trap-") as directory:
            work = Path(directory)
            cfile = work / "alias.c"
            binary = work / ("alias.exe" if os.name == "nt" else "alias")
            cfile.write_text(SHIM + flags + production + HARNESS, encoding="utf-8")
            built = subprocess.run(
                [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                 str(cfile), "-o", str(binary)],
                cwd=work, capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], cwd=work, capture_output=True,
                                 text=True, timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_all_mach_alias_store_families_share_the_gate(self):
        source = SIGNAL.read_text(encoding="utf-8")
        start = source.index("/* 4. Emulate stores to JIT-pool RX aliases")
        end = source.index("if (have_neon &&", start)
        gate = source[start:end]
        self.assertIn("rw_addr && !ios_mach_alias_store_allowed( in_jit, (uintptr_t)fault_addr )", gate)
        self.assertIn("else if (rw_addr && (uintptr_t)fault_pc >= 0x100000000ULL)", gate)
        self.assertNotIn("memcpy((void *)rw_addr", gate)


if __name__ == "__main__":
    unittest.main()
