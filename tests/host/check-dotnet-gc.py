#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise the production .NET GC environment policy before PE initialization."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'build/ntdll-unix/env_ios.c').read_text(encoding='utf-8')


def function(signature):
    begin = source.index(signature)
    return source[begin:source.index('\n}', begin) + 2] + '\n'


initial = source[source.index('static RTL_USER_PROCESS_PARAMETERS *build_initial_params('):
                 source.index('void unix_init_startup_info(')]
child = source[source.index('void unix_init_startup_info('):]
for path in (initial, child):
    assert path.index('ios_apply_dotnet_gc_compat(') < path.index('params->Environment =')

# Compile real environment lookup/editing and compatibility code. wchar_t is
# the host's native width; all Wine policy operations use WCHAR element counts.
harness = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <wctype.h>
typedef wchar_t WCHAR;
typedef size_t SIZE_T;
typedef unsigned short USHORT;
typedef int BOOL;
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define max(a,b) ((a) > (b) ? (a) : (b))
static int is_machine_64bit(USHORT machine)
{ return machine == 0x8664 || machine == 0xa641 || machine == 0xaa64; }
#define wcsnicmp test_wcsnicmp
static int wcsnicmp(const WCHAR *a, const WCHAR *b, SIZE_T n)
{
    while (n--) {
        wint_t x = towlower(*a++), y = towlower(*b++);
        if (x != y) return x < y ? -1 : 1;
        if (!x) return 0;
    }
    return 0;
}
static void ascii_to_unicode(WCHAR *out, const char *in, SIZE_T count)
{ while (count--) *out++ = (unsigned char)*in++; }
#ifdef _WIN32
#define dprintf(fd, ...) fprintf(stderr, __VA_ARGS__)
#endif
'''
for name in ('static WCHAR *find_env_var(', 'static void set_env_var(',
             'static void append_envW(', 'static void ios_apply_dotnet_gc_compat('):
    harness += function(name)
harness += r'''
static WCHAR *env;
static SIZE_T pos, capacity;
static void reset(void)
{
    free(env); capacity = 2; pos = 0;
    env = calloc(capacity, sizeof(*env)); assert(env);
}
static void apply(USHORT machine)
{
    ios_apply_dotnet_gc_compat(&env, &pos, &capacity, machine);
    env[pos] = 0;
    assert(pos < capacity);
}
static void put(const char *name, const WCHAR *value)
{ append_envW(&env, &pos, &capacity, name, value); }
static const WCHAR *get(const WCHAR *name)
{
    WCHAR *p = find_env_var(env, pos, name, wcslen(name));
    return p ? p + wcslen(name) + 1 : NULL;
}
static void expect(const WCHAR *name, const WCHAR *value)
{
    const WCHAR *actual = get(name);
    assert(value ? actual && !wcscmp(actual, value) : !actual);
}
int main(void)
{
    const USHORT machines[] = {0x8664, 0xa641, 0xaa64};
    const char *limits[] = {
        "DOTNET_GCRegionRange", "COMPlus_GCRegionRange",
        "DOTNET_GCHeapHardLimit", "COMPlus_GCHeapHardLimit",
        "DOTNET_GCHeapHardLimitPercent", "COMPlus_GCHeapHardLimitPercent",
        "DOTNET_GCHeapHardLimitSOH", "COMPlus_GCHeapHardLimitSOH",
        "DOTNET_GCHeapHardLimitLOH", "COMPlus_GCHeapHardLimitLOH",
        "DOTNET_GCHeapHardLimitPOH", "COMPlus_GCHeapHardLimitPOH",
        "DOTNET_GCHeapHardLimitSOHPercent", "COMPlus_GCHeapHardLimitSOHPercent",
        "DOTNET_GCHeapHardLimitLOHPercent", "COMPlus_GCHeapHardLimitLOHPercent",
        "DOTNET_GCHeapHardLimitPOHPercent", "COMPlus_GCHeapHardLimitPOHPercent"
    };
    for (size_t i = 0; i < ARRAY_SIZE(machines); i++) {
        reset(); put("PATH", L"C:\\windows"); apply(machines[i]);
        expect(L"DOTNET_GCRegionRange", L"200000000");
        expect(L"PATH", L"C:\\windows");
        SIZE_T old_pos = pos;
        apply(machines[i]); assert(pos == old_pos);
        expect(L"DOTNET_GCRegionRange", L"200000000");
        apply(0x14c);
        expect(L"DOTNET_GCRegionRange", NULL);
        expect(L"__IDECK_DOTNET_GC_AUTO", NULL);
        apply(machines[i]); expect(L"DOTNET_GCRegionRange", L"200000000");
    }
    reset(); apply(0x14c); expect(L"DOTNET_GCRegionRange", NULL);
    for (size_t i = 0; i < ARRAY_SIZE(limits); i++) {
        WCHAR key[64]; ascii_to_unicode(key, limits[i], strlen(limits[i]) + 1);
        reset(); put(limits[i], L"40000000"); apply(0x8664);
        expect(key, L"40000000"); expect(L"__IDECK_DOTNET_GC_AUTO", NULL);
        if (i) expect(L"DOTNET_GCRegionRange", NULL);
        // Inherited automatic values yield to a child's explicit heap policy.
        reset(); apply(0x8664); put(limits[i], L"40000000"); apply(0x8664);
        expect(key, L"40000000"); expect(L"__IDECK_DOTNET_GC_AUTO", NULL);
        if (i) expect(L"DOTNET_GCRegionRange", NULL);
    }
    reset(); put("dotnet_gcregionrange", L"0"); apply(0x8664);
    expect(L"DOTNET_GCRegionRange", L"0"); expect(L"__IDECK_DOTNET_GC_AUTO", NULL);
    reset(); put("DOTNET_GCRegionRange", L""); apply(0x8664);
    expect(L"DOTNET_GCRegionRange", L"");
    reset(); put("COMPlus_GCRegionRange", L"200000000"); apply(0x14c);
    expect(L"COMPlus_GCRegionRange", L"200000000");
    reset(); put("__IDECK_DOTNET_GC_AUTO", L"1"); apply(0x8664);
    expect(L"DOTNET_GCRegionRange", L"200000000");
    free(env);
    puts("PASS: .NET GC reservation defaults, overrides, inheritance, x86 cleanup and environment growth");
    return 0;
}
'''

compiler = os.environ.get('CC') or shutil.which('cc') or shutil.which('clang')
if not compiler:
    raise SystemExit('FAIL: C compiler required (set CC if it is outside PATH)')
with tempfile.TemporaryDirectory(prefix='ideck-dotnet-gc-') as directory:
    path = Path(directory)
    c_file = path / 'checks.c'
    executable = path / ('checks.exe' if os.name == 'nt' else 'checks')
    c_file.write_text(harness, encoding='utf-8')
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', str(c_file),
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
