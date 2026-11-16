# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Exercise iDeck's actual Windows environment policy without FEX or a device."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "build/ntdll-unix/env_ios.c"

SHIM = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint16_t WCHAR;
typedef uint16_t USHORT;
typedef size_t SIZE_T;
typedef int BOOL;
#define IMAGE_FILE_MACHINE_I386 0x014c
#ifndef max
#define max(a,b) ((a) > (b) ? (a) : (b))
#endif
#define dprintf(...) ((void)0)
#define wcslen test_wcslen
#define wcsnicmp test_wcsnicmp
static void ascii_to_unicode(WCHAR *out, const char *in, size_t n)
{ size_t i; for (i = 0; i < n; i++) out[i] = (unsigned char)in[i]; }
static size_t wcslen(const WCHAR *s)
{ size_t n = 0; while (s[n]) n++; return n; }
static int wcsnicmp(const WCHAR *a, const WCHAR *b, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
    {
        unsigned x = a[i], y = b[i];
        if (x >= 'a' && x <= 'z') x -= 32;
        if (y >= 'a' && y <= 'z') y -= 32;
        if (x != y) return (int)x - (int)y;
        if (!x) break;
    }
    return 0;
}
'''

HARNESS = r'''
static WCHAR *environment(const char *text, SIZE_T *pos, SIZE_T *size)
{
    size_t i, n = strlen(text);
    WCHAR *out = malloc((n + 1) * sizeof(*out));
    assert(out);
    for (i = 0; i < n; i++) out[i] = text[i] == '|' ? 0 : (unsigned char)text[i];
    out[n] = 0;
    *pos = n;
    *size = n + 1;
    return out;
}
static void expect(WCHAR *env, SIZE_T pos, const char *name, const char *value)
{
    WCHAR nameW[64], valueW[64];
    WCHAR *entry;
    ascii_to_unicode(nameW, name, strlen(name) + 1);
    entry = find_env_var(env, pos, nameW, strlen(name));
    if (!value) { assert(!entry); return; }
    assert(entry);
    entry += strlen(name) + 1;
    ascii_to_unicode(valueW, value, strlen(value) + 1);
    assert(wcslen(entry) == strlen(value));
    assert(!memcmp(entry, valueW, (strlen(value) + 1) * sizeof(WCHAR)));
}
static void check(const char *input, USHORT machine, const char *value, const char *marker)
{
    SIZE_T pos, size;
    WCHAR *env = environment(input, &pos, &size);
    ios_apply_wow64_smc_compat(&env, &pos, &size, machine);
    env[pos] = 0;
    assert(pos < size && (!pos || env[pos - 1] == 0));
    expect(env, pos, "MADEIRA_SMC_HOT_PAGE", value);
    expect(env, pos, "__IDECK_WOW64_SMC_AUTO", marker);
    if (value)
    {
        WCHAR hotW[32];
        WCHAR *entry;
        ascii_to_unicode(hotW, "MADEIRA_SMC_HOT_PAGE", sizeof("MADEIRA_SMC_HOT_PAGE"));
        entry = find_env_var(env, pos, hotW, wcslen(hotW));
        assert(entry && !memcmp(entry, hotW, wcslen(hotW) * sizeof(WCHAR)));
    }
    free(env);
}
int main(void)
{
    SIZE_T pos, size, sibling_pos, sibling_size;
    WCHAR *env, *sibling;
    unsigned i;
    const USHORT native[] = {0x8664, 0xaa64, 0xa641, 0x01c4, 0};

    check("", IMAGE_FILE_MACHINE_I386, "0", "1");
    check("PATH=C:\\windows|", IMAGE_FILE_MACHINE_I386, "0", "1");
    check("MADEIRA_SMC_HOT_PAGE=|", IMAGE_FILE_MACHINE_I386, "0", "1");
    check("madeira_smc_hot_page=128|", IMAGE_FILE_MACHINE_I386, "128", NULL);
    check("madeira_smc_hot_page=0|", IMAGE_FILE_MACHINE_I386, "0", NULL);
    check("MADEIRA_SMC_HOT_PAGE=0|", IMAGE_FILE_MACHINE_I386, "0", NULL);
    check("MADEIRA_SMC_HOT_PAGE=128|__IDECK_WOW64_SMC_AUTO=1|",
          IMAGE_FILE_MACHINE_I386, "128", NULL); /* application override */
    check("__IDECK_WOW64_SMC_AUTO=1|", IMAGE_FILE_MACHINE_I386, "0", "1");
    for (i = 0; i < sizeof(native) / sizeof(native[0]); i++)
    {
        check("", native[i], NULL, NULL);
        check("MADEIRA_SMC_HOT_PAGE=0|__IDECK_WOW64_SMC_AUTO=1|", native[i], NULL, NULL);
        check("MADEIRA_SMC_HOT_PAGE=0|", native[i], "0", NULL);
        check("MADEIRA_SMC_HOT_PAGE=64|__IDECK_WOW64_SMC_AUTO=1|", native[i], "64", NULL);
    }

    env = environment("PATH=C:\\windows|MADEIRA_SMC_HOT_PAGEX=77|A=1|", &pos, &size);
    /* Desktop -> x86 game -> x86 helper; repeated initialization is stable. */
    for (i = 0; i < 5; i++) ios_apply_wow64_smc_compat(&env, &pos, &size, IMAGE_FILE_MACHINE_I386);
    expect(env, pos, "MADEIRA_SMC_HOT_PAGE", "0");
    expect(env, pos, "__IDECK_WOW64_SMC_AUTO", "1");
    expect(env, pos, "PATH", "C:\\windows");
    expect(env, pos, "MADEIRA_SMC_HOT_PAGEX", "77");
    expect(env, pos, "A", "1");
    env[pos] = 0;
    sibling_pos = pos;
    sibling_size = pos + 1;
    sibling = malloc(sibling_size * sizeof(*sibling));
    assert(sibling);
    memcpy(sibling, env, sibling_size * sizeof(*sibling));
    /* An x64 descendant drops only the auto default; its sibling keeps it. */
    ios_apply_wow64_smc_compat(&env, &pos, &size, 0x8664);
    expect(env, pos, "MADEIRA_SMC_HOT_PAGE", NULL);
    expect(env, pos, "__IDECK_WOW64_SMC_AUTO", NULL);
    expect(env, pos, "A", "1");
    expect(sibling, sibling_pos, "MADEIRA_SMC_HOT_PAGE", "0");
    ios_apply_wow64_smc_compat(&sibling, &sibling_pos, &sibling_size, IMAGE_FILE_MACHINE_I386);
    expect(sibling, sibling_pos, "MADEIRA_SMC_HOT_PAGE", "0");
    free(sibling);
    free(env);
    return 0;
}
'''


def function(source, signature):
    start = source.index(signature)
    return source[start:source.index("\n}", start) + 2] + "\n"


class Wow64SMCCompat(unittest.TestCase):
    def test_production_policy_and_environment_mutation(self):
        compiler = shutil.which("clang") or shutil.which("cc") or shutil.which("cl")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        source = SOURCE.read_text(encoding="utf-8")
        code = SHIM + "\n".join(function(source, signature) for signature in (
            "static WCHAR *find_env_var(", "static void set_env_var(",
            "static void append_envW(", "static void ios_apply_wow64_smc_compat(")) + HARNESS
        with tempfile.TemporaryDirectory(prefix="ideck-wow64-smc-") as directory:
            work = Path(directory)
            cfile = work / "policy.c"
            binary = work / ("policy.exe" if os.name == "nt" else "policy")
            cfile.write_text(code, encoding="utf-8")
            if Path(compiler).stem.lower() == "cl":
                command = [compiler, "/nologo", "/std:c11", "/W4", "/WX",
                           str(cfile), "/Fe:" + str(binary)]
            else:
                command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                           "-fsanitize=address,undefined", str(cfile), "-o", str(binary)]
            built = subprocess.run(command, cwd=work, capture_output=True, text=True, errors="replace", timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            ran = subprocess.run([str(binary)], cwd=work, capture_output=True, text=True, errors="replace", timeout=30)
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)

    def test_initial_and_child_paths_apply_policy_before_copy_and_crt_start(self):
        source = SOURCE.read_text(encoding="utf-8")
        initial = function(source, "static RTL_USER_PROCESS_PARAMETERS *build_initial_params(")
        child = function(source, "void unix_init_startup_info(")
        initial_call = "ios_apply_wow64_smc_compat( &env, &env_pos, &env_size, main_image_info.Machine );"
        child_call = "ios_apply_wow64_smc_compat( &env, &env_pos, &env_size, machine );"
        self.assertGreater(initial.index(initial_call), initial.index("load_start_exe( &nt_name, module );"))
        for body, call in ((initial, initial_call), (child, child_call)):
            self.assertLess(body.index(call), body.index("size = (sizeof(*params)"))
            self.assertLess(body.index(call), body.index("memcpy( dst, env, env_pos * sizeof(WCHAR) );"))
        policy = function(source, "static void ios_apply_wow64_smc_compat(")
        self.assertNotIn("setenv(", policy)
        self.assertNotIn("getenv(", policy)
        self.assertIn('compile_one "$BUILD_DIR/env_ios.c" "env"',
                      (ROOT / "build/ntdll-unix/build.sh").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
