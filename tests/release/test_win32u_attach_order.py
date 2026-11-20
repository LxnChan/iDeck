# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise Wine's patched process_attach, including its cycle/failure paths."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "wine_loader_patches", ROOT / "build/wine-pe/apply-loader-patches.py")
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)


def attach_function(text):
    start = text.index("static NTSTATUS process_attach( LDR_DDAG_NODE *node, LPVOID lpReserved )\n{")
    brace = text.index("{", start)
    depth = 0
    for end in range(brace, len(text)):
        depth += (text[end] == "{") - (text[end] == "}")
        if not depth:
            return text[start:end + 1]
    raise AssertionError("Unterminated process_attach")


SHIM = r'''
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
/* Select the production branch after host headers have selected their ABI. */
#ifdef IDECK_TEST_ARM64EC
#define __arm64ec__ 1
#endif
typedef int NTSTATUS;
typedef void *LPVOID;
typedef uintptr_t ULONG_PTR;
typedef struct list { struct list *Flink, *Blink; } LIST_ENTRY;
typedef struct node LDR_DDAG_NODE;
typedef struct {
    LIST_ENTRY NodeModuleLink, InInitializationOrderLinks;
    struct { const wchar_t *Buffer; } BaseDllName;
    unsigned Flags;
    int LoadCount;
    void *ActivationContext;
    LDR_DDAG_NODE *DdagNode;
} LDR_DATA_TABLE_ENTRY;
typedef struct { LDR_DATA_TABLE_ENTRY ldr; } WINE_MODREF;
struct node { LIST_ENTRY Modules; LDR_DDAG_NODE *deps[4]; int count; };
enum { NTDLL, KERNEL32, USER32, GDI32, COMCTL32, WIN32U, HEADLESS,
       MSVCRT, ADVAPI32, SHELL32, VERSION, COUNT };
enum { STATUS_SUCCESS=0, DLL_PROCESS_ATTACH=1, DLL_PROCESS_DETACH=0,
       LDR_DONT_RESOLVE_REFS=1, LDR_LOAD_IN_PROGRESS=2, LDR_PROCESS_ATTACHED=4,
       LDR_WINE_INTERNAL=8,
       LDR_DLL_NOTIFICATION_REASON_LOADED=1, LDR_DLL_NOTIFICATION_REASON_UNLOADED=2 };
#define CONTAINING_RECORD(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
#define TRACE(...) ((void)0)
#define WARN(...) ((void)0)
static struct { WINE_MODREF wm; LDR_DDAG_NODE node; } modules[COUNT];
static int process_detaching, imports_fixup_done, dispatcher_ready, gui_fault;
static int fail_win32u, present_win32u, calls[COUNT], order[COUNT], order_count;
static int activations, deactivations, reenter;
static int present_msvcrt, locale_ready, locale_fault, fail_msvcrt;
static WINE_MODREF *last_failed_modref;
struct ldr { LIST_ENTRY InInitializationOrderModuleList; };
static struct ldr ldr_data;
static struct peb { struct ldr *LdrData; } peb;
static struct { struct peb *Peb; } teb;
#define NtCurrentTeb() (&teb)
static void InsertTailList(LIST_ENTRY *head, LIST_ENTRY *entry) {
    entry->Flink=head; entry->Blink=head->Blink; head->Blink->Flink=entry; head->Blink=entry;
}
static void RtlActivateActivationContext(int flags, void *ctx, ULONG_PTR *cookie) {
    (void)flags; (void)ctx; *cookie=42; ++activations;
}
static void RtlDeactivateActivationContext(int flags, ULONG_PTR cookie) {
    (void)flags; assert(cookie==42); ++deactivations;
}
static WINE_MODREF *find_basename_module(const wchar_t *name) {
    for (int i=0; i<COUNT; ++i)
        if ((i!=WIN32U || present_win32u) && (i!=MSVCRT || present_msvcrt) &&
            !wcscmp(name,modules[i].wm.ldr.BaseDllName.Buffer))
            return &modules[i].wm;
    return NULL;
}
static NTSTATUS process_attach(LDR_DDAG_NODE *, LPVOID);
static NTSTATUS walk_node_dependencies(LDR_DDAG_NODE *node, LPVOID reserved,
                                       NTSTATUS (*callback)(LDR_DDAG_NODE *, LPVOID)) {
    for (int i=0; i<node->count; ++i) {
        NTSTATUS status=callback(node->deps[i],reserved);
        if (status) return status;
    }
    return 0;
}
static void call_ldr_notifications(int reason, LDR_DATA_TABLE_ENTRY *entry) {
    (void)reason; (void)entry;
}
static NTSTATUS MODULE_InitDLL(WINE_MODREF *wm, int reason, LPVOID reserved) {
    if (reason!=DLL_PROCESS_ATTACH) return 0;
    for (int i=0; i<COUNT; ++i) if (wm==&modules[i].wm) {
        ++calls[i]; order[order_count++]=i;
        if (i==WIN32U) {
            if (reenter) assert(!process_attach(&modules[USER32].node,reserved));
            if (fail_win32u) return -77;
            dispatcher_ready=1;
        }
        if (i==COMCTL32 && !dispatcher_ready) gui_fault=1;
        if (i==MSVCRT) {
            if (fail_msvcrt) return -88;
            locale_ready=1;
        }
        /* NativeAOT version.dll calls advapi32!LookupPrivilegeValueW,
         * whose _wcsicmp requires msvcrt's locale during DLL attach. */
        if (i==VERSION && !locale_ready) locale_fault=1;
        return 0;
    }
    assert(0); return -1;
}
'''


HARNESS = r'''
static void reset(void) {
    static const wchar_t *names[]={L"ntdll.dll",L"kernel32.dll",L"user32.dll",
        L"gdi32.dll",L"comctl32.dll",L"win32u.dll",L"headless.dll",
        L"msvcrt.dll",L"advapi32.dll",L"shell32.dll",L"version.dll"};
    memset(modules,0,sizeof(modules)); memset(calls,0,sizeof(calls));
    process_detaching=dispatcher_ready=gui_fault=fail_win32u=order_count=0;
    activations=deactivations=reenter=0; last_failed_modref=NULL;
    present_msvcrt=locale_ready=locale_fault=fail_msvcrt=0;
    imports_fixup_done=present_win32u=1;
    peb.LdrData=&ldr_data; teb.Peb=&peb;
    ldr_data.InInitializationOrderModuleList.Flink=ldr_data.InInitializationOrderModuleList.Blink=
        &ldr_data.InInitializationOrderModuleList;
    for (int i=0; i<COUNT; ++i) {
        modules[i].wm.ldr.BaseDllName.Buffer=names[i];
        modules[i].wm.ldr.DdagNode=&modules[i].node;
        modules[i].node.Modules.Flink=&modules[i].wm.ldr.NodeModuleLink;
    }
    modules[NTDLL].wm.ldr.Flags=modules[KERNEL32].wm.ldr.Flags=LDR_PROCESS_ATTACHED;
    /* Eager GUI cycle: USER32 -> GDI32 -> COMCTL32 -> USER32.
     * WIN32U is GDI32's next dependency; the stock walk reaches it too late. */
    modules[USER32].node.deps[modules[USER32].node.count++]=&modules[GDI32].node;
    modules[GDI32].node.deps[modules[GDI32].node.count++]=&modules[COMCTL32].node;
    modules[GDI32].node.deps[modules[GDI32].node.count++]=&modules[WIN32U].node;
    modules[COMCTL32].node.deps[modules[COMCTL32].node.count++]=&modules[USER32].node;
    modules[WIN32U].node.deps[modules[WIN32U].node.count++]=&modules[NTDLL].node;
    modules[MSVCRT].node.deps[modules[MSVCRT].node.count++]=&modules[NTDLL].node;
    modules[MSVCRT].node.deps[modules[MSVCRT].node.count++]=&modules[KERNEL32].node;
    modules[MSVCRT].wm.ldr.Flags=LDR_WINE_INTERNAL;
}
static void crt_cycle(void) {
    reset(); present_msvcrt=1;
    /* Shipped eager-import graph, shortened through its transitive edges:
     * ADVAPI32 -> ... -> SHELL32 -> local VERSION -> ADVAPI32 (in progress).
     * ADVAPI32's ordinary MSVCRT import comes after its promoted delays.
     * Stock DFS reaches the proxy before MSVCRT's process attach. */
    modules[ADVAPI32].node.deps[modules[ADVAPI32].node.count++]=&modules[SHELL32].node;
    modules[ADVAPI32].node.deps[modules[ADVAPI32].node.count++]=&modules[MSVCRT].node;
    modules[SHELL32].node.deps[modules[SHELL32].node.count++]=&modules[VERSION].node;
    modules[VERSION].node.deps[modules[VERSION].node.count++]=&modules[ADVAPI32].node;
}
int main(void) {
    reset(); reenter=1;
    modules[USER32].wm.ldr.ActivationContext=(void *)1;
    assert(!process_attach(&modules[USER32].node,(void *)1));
#if defined(__arm64ec__) && !defined(EXPECT_STOCK_FAULT)
    assert(!gui_fault && order[0]==WIN32U);
#else
    assert(gui_fault && order[0]==COMCTL32);
#endif
    assert(calls[WIN32U]==1 && calls[COMCTL32]==1 && calls[USER32]==1);
    assert(!process_attach(&modules[USER32].node,(void *)1));
    assert(calls[WIN32U]==1 && calls[USER32]==1);
    assert(activations==1 && deactivations==1);
    assert(modules[WIN32U].wm.ldr.LoadCount==-1);

    reset(); fail_win32u=1;
    modules[USER32].wm.ldr.ActivationContext=(void *)1;
    assert(process_attach(&modules[USER32].node,NULL)==-77);
    assert(last_failed_modref==&modules[WIN32U].wm);
    assert(!(modules[USER32].wm.ldr.Flags & (LDR_LOAD_IN_PROGRESS|LDR_PROCESS_ATTACHED)));
    assert(!(modules[WIN32U].wm.ldr.Flags & (LDR_LOAD_IN_PROGRESS|LDR_PROCESS_ATTACHED)));
    assert(activations==deactivations);
#if defined(__arm64ec__) && !defined(EXPECT_STOCK_FAULT)
    assert(!calls[COMCTL32] && !calls[USER32]);
#endif

    /* No new GUI load in a headless process; no early attach at bootstrap. */
    reset(); present_win32u=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[WIN32U]);
    reset(); imports_fixup_done=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[WIN32U]);
    reset(); modules[KERNEL32].wm.ldr.Flags=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[WIN32U]);
    reset(); modules[WIN32U].wm.ldr.Flags=LDR_DONT_RESOLVE_REFS;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[WIN32U]);
    reset(); process_detaching=1;
    assert(!process_attach(&modules[USER32].node,NULL) && !order_count);

    crt_cycle();
    modules[MSVCRT].wm.ldr.ActivationContext=(void *)1;
    assert(!process_attach(&modules[ADVAPI32].node,(void *)1));
#if defined(__arm64ec__) && !defined(EXPECT_STOCK_FAULT)
    assert(!locale_fault);
#else
    assert(locale_fault);
#endif
    assert(calls[MSVCRT]==1 && calls[VERSION]==1 && locale_ready);
    assert(modules[MSVCRT].wm.ldr.LoadCount==-1);
    assert(activations==1 && deactivations==1);
    assert(!process_attach(&modules[ADVAPI32].node,NULL));
    assert(calls[MSVCRT]==1 && calls[VERSION]==1);

    crt_cycle(); fail_msvcrt=1;
    assert(process_attach(&modules[ADVAPI32].node,NULL)==-88);
    assert(last_failed_modref==&modules[MSVCRT].wm);
    assert(!(modules[MSVCRT].wm.ldr.Flags & (LDR_LOAD_IN_PROGRESS|LDR_PROCESS_ATTACHED)));
    assert(!(modules[ADVAPI32].wm.ldr.Flags & (LDR_LOAD_IN_PROGRESS|LDR_PROCESS_ATTACHED)));
#if defined(__arm64ec__) && !defined(EXPECT_STOCK_FAULT)
    assert(!calls[VERSION]);
#endif
    reset(); present_msvcrt=1; imports_fixup_done=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[MSVCRT]);
    reset(); present_msvcrt=1; modules[KERNEL32].wm.ldr.Flags=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[MSVCRT]);
    reset(); present_msvcrt=1; modules[MSVCRT].wm.ldr.Flags=LDR_DONT_RESOLVE_REFS;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[MSVCRT]);
    /* An application-supplied CRT may have a different dependency graph. */
    reset(); present_msvcrt=1; modules[MSVCRT].wm.ldr.Flags=0;
    assert(!process_attach(&modules[HEADLESS].node,NULL) && !calls[MSVCRT]);
    return 0;
}
'''


class Win32uAttachOrder(unittest.TestCase):
    def test_production_loader_cycle_and_patch_application(self):
        wine = Path(os.environ.get("IDECK_TEST_WINE_SOURCE", ROOT / "wine"))
        path = wine / "dlls/ntdll/loader.c"
        if not path.is_file():
            self.skipTest("Requires the pinned Wine source checkout (present in IPA CI)")
        compiler = shutil.which("clang") or shutil.which("cc") or shutil.which("cl")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        with tempfile.TemporaryDirectory(prefix="ideck-win32u-") as directory:
            work = Path(directory)
            loader = work / "dlls/ntdll/loader.c"
            loader.parent.mkdir(parents=True)
            original = path.read_text(encoding="utf-8")
            loader.write_text(original, encoding="utf-8", newline="\n")
            # git apply outside a repo still respects an enclosing worktree;
            # make the miniature checkout explicit and keep all tests local.
            subprocess.run(["git", "init", "-q", str(work)], check=True)
            if subprocess.run(["git", "-C", str(work), "apply", "--reverse", "--check",
                               str(overlay.PATCH)], capture_output=True).returncode == 0:
                subprocess.run(["git", "-C", str(work), "apply", "--reverse",
                                str(overlay.PATCH)], check=True)
            original = loader.read_text(encoding="utf-8")
            overlay.apply(work)
            patched = loader.read_bytes()
            overlay.apply(work)
            self.assertEqual(patched, loader.read_bytes(), "Overlay must be idempotent")
            for label, production, defines in (
                ("before", original, ["IDECK_TEST_ARM64EC", "EXPECT_STOCK_FAULT"]),
                ("arm64ec", patched.decode(), ["IDECK_TEST_ARM64EC"]),
                ("other_arch", patched.decode(), []),
            ):
                with self.subTest(variant=label):
                    source = work / (label + ".c")
                    binary = work / (label + (".exe" if os.name == "nt" else ""))
                    source.write_text(SHIM + attach_function(production) + HARNESS, encoding="utf-8")
                    if Path(compiler).stem.lower() == "cl":
                        command = [compiler, "/nologo", "/std:c11", "/W3", "/WX",
                                   str(source), "/Fe:" + str(binary)] + ["/D" + d for d in defines]
                    else:
                        command = [compiler, "-std=c11", "-Werror", str(source), "-o", str(binary)]
                        command += ["-D" + d for d in defines]
                    built = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=30)
                    self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
                    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)


if __name__ == "__main__":
    unittest.main()
