# SPDX-License-Identifier: LGPL-2.1-or-later
"""Exercise the shared Shell overlay, menu ranges and notification membership."""
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("shell_overlay", ROOT / "build/wine-pe/apply-shell-patches.py")
OVERLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERLAY)
FILES = ("changenotify.c", "shell32.rc", "shlview.c", "shlview_cmenu.c")


def function(text, signature):
    start = text.index(signature)
    return text[start:text.index("\n}", start) + 2] + "\n"


SHIM = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef int BOOL, INT;
typedef long LONG, LRESULT;
typedef char ITEMIDLIST;
typedef const ITEMIDLIST *LPCITEMIDLIST;
typedef ITEMIDLIST *LPITEMIDLIST;
typedef intptr_t WPARAM;
typedef intptr_t LPARAM;
typedef struct view {
    const char *pidlNotify;
    struct view *hWndList;
    char rows[16][64];
    unsigned count;
} IShellViewImpl;
enum { FALSE=0, TRUE=1, S_OK=0, S_FALSE=1, LVM_DELETEITEM=1,
       SHCNE_CREATE=1, SHCNE_MKDIR=2, SHCNE_DELETE=4, SHCNE_RMDIR=8,
       SHCNE_RENAMEITEM=16, SHCNE_RENAMEFOLDER=32, SHCNE_UPDATEITEM=64,
       SHCNE_ONEITEMEVENTS=1|2|4|8|64, SHCNE_TWOITEMEVENTS=16|32 };
#define TRACE(...) ((void)0)
static int fail_clone;
static BOOL ILIsEqual(const char *a, const char *b) { return a && b && !strcmp(a,b); }
static BOOL ILIsParent(const char *parent, const char *child, BOOL immediate)
{
    size_t n;
    if (!parent || !child) return FALSE;
    n = strlen(parent);
    if (strncmp(parent,child,n) || child[n]!='/' || !child[n+1]) return FALSE;
    return !immediate || !strchr(child+n+1,'/');
}
static const char *ILFindLastID(const char *path)
{
    const char *last = strrchr(path,'/');
    return last ? last+1 : path;
}
static char *ILClone(const char *pidl)
{
    char *copy;
    if (fail_clone) return NULL;
    copy = malloc(strlen(pidl)+1);
    assert(copy);
    strcpy(copy,pidl);
    return copy;
}
static int IncludeObject(IShellViewImpl *view, const char *pidl)
{
    (void)view;
    return !strncmp(pidl,"hidden",6) ? S_FALSE : S_OK;
}
static int LV_FindItemByPidl(IShellViewImpl *view, const char *pidl)
{
    unsigned i;
    for (i=0;i<view->count;i++) if (!strcmp(view->rows[i],pidl)) return (int)i;
    return -1;
}
static void shellview_add_item(IShellViewImpl *view, const char *pidl)
{
    assert(pidl && view->count<16 && strlen(pidl)<64);
    strcpy(view->rows[view->count++],pidl);
    free((void *)pidl);
}
static LRESULT SendMessageW(IShellViewImpl *view, int msg, WPARAM index, LPARAM unused)
{
    unsigned i;
    (void)unused;
    assert(msg==LVM_DELETEITEM && index>=0 && (unsigned)index<view->count);
    for (i=(unsigned)index;i+1<view->count;i++) strcpy(view->rows[i],view->rows[i+1]);
    view->count--;
    return TRUE;
}
static BOOL LV_RenameItem(IShellViewImpl *view, const char *old, const char *updated)
{
    int index=LV_FindItemByPidl(view,ILFindLastID(old));
    if (index<0) return FALSE;
    assert(strlen(ILFindLastID(updated))<64);
    strcpy(view->rows[index],ILFindLastID(updated));
    return TRUE;
}
'''


HARNESS = r'''
static void reset(IShellViewImpl *view)
{
    memset(view,0,sizeof(*view));
    view->pidlNotify="/normalized/view";
    view->hWndList=view;
    fail_clone=0;
}
static void change(IShellViewImpl *view, LONG event, const char *old, const char *updated)
{
    const char *pidls[2]={old,updated};
    ShellView_OnChange(view,pidls,event);
}
static void add(IShellViewImpl *view, const char *name) { shellview_add_item(view,ILClone(name)); }
int main(void)
{
    IShellViewImpl view;
    reset(&view);
    assert(should_notify("/normalized/view/Folder/nested/file",view.pidlNotify,TRUE));
    assert(!should_notify("/normalized/view-other/file",view.pidlNotify,TRUE));
    change(&view,SHCNE_CREATE,"/normalized/view/Folder/nested/file",NULL);
#ifdef EXPECT_STOCK_FAULT
    assert(view.count==1 && !strcmp(view.rows[0],"file"));
    assert(!delivered(SHCNE_RENAMEITEM,"/elsewhere/file","/normalized/view/file",view.pidlNotify));
    puts("PASS: stock view reproduces descendant insertion and missing inbound rename delivery");
#else
    assert(!view.count);
    change(&view,SHCNE_MKDIR,"/normalized/view/Folder/nested",NULL);
    assert(!view.count);
    change(&view,SHCNE_CREATE,"/normalized/view/direct",NULL);
    change(&view,SHCNE_MKDIR,"/normalized/view/Folder",NULL);
    change(&view,SHCNE_CREATE,"/normalized/view/direct",NULL);
    assert(view.count==2);
    change(&view,SHCNE_CREATE,"/normalized/view/hidden-file",NULL);
    assert(view.count==2);
    change(&view,SHCNE_DELETE,"/normalized/view/Folder/direct",NULL);
    change(&view,SHCNE_RMDIR,"/normalized/view/Folder/Folder",NULL);
    change(&view,SHCNE_DELETE,"/elsewhere/direct",NULL);
    assert(view.count==2);
    change(&view,SHCNE_DELETE,"/normalized/view/missing",NULL);
    assert(view.count==2);
    change(&view,SHCNE_RENAMEITEM,"/normalized/view/direct","/normalized/view/renamed");
    assert(LV_FindItemByPidl(&view,"direct")==-1 && LV_FindItemByPidl(&view,"renamed")>=0);
    change(&view,SHCNE_RENAMEITEM,"/normalized/view/Folder/renamed","/normalized/view/Folder/other");
    assert(LV_FindItemByPidl(&view,"renamed")>=0 && view.count==2);
    change(&view,SHCNE_RENAMEITEM,"/normalized/view/renamed","/elsewhere/renamed");
    assert(view.count==1 && !strcmp(view.rows[0],"Folder"));
    assert(delivered(SHCNE_RENAMEITEM,"/elsewhere/incoming","/normalized/view/incoming",view.pidlNotify));
    change(&view,SHCNE_RENAMEITEM,"/elsewhere/incoming","/normalized/view/incoming");
    assert(view.count==2 && LV_FindItemByPidl(&view,"incoming")>=0);
    change(&view,SHCNE_RENAMEITEM,"/normalized/view/incoming","/normalized/view/hidden-new");
    assert(view.count==1);
    change(&view,SHCNE_RENAMEFOLDER,"/normalized/view/Folder","/normalized/view/renamed-folder");
    assert(view.count==1 && !strcmp(view.rows[0],"renamed-folder"));
    change(&view,SHCNE_RENAMEFOLDER,"/normalized/view/renamed-folder","/normalized/view/other/nested");
    assert(!view.count);
    change(&view,SHCNE_RENAMEITEM,"/normalized/view/other/nested","/normalized/view/incoming");
    assert(view.count==1 && !strcmp(view.rows[0],"incoming"));
    change(&view,SHCNE_DELETE,"/normalized/view/incoming",NULL);
    assert(!view.count);
    fail_clone=1;
    change(&view,SHCNE_CREATE,"/normalized/view/no-memory",NULL);
    assert(!view.count);
    fail_clone=0;
    view.pidlNotify=NULL;
    change(&view,SHCNE_CREATE,"/normalized/view/no-subscription",NULL);
    assert(!view.count);
    reset(&view);
    add(&view,"same");
    change(&view,SHCNE_DELETE,"/normalized/view/Folder/same",NULL);
    assert(view.count==1 && !strcmp(view.rows[0],"same"));
    assert(!delivered(SHCNE_CREATE,"/elsewhere/file","/normalized/view/file",view.pidlNotify));
    puts("PASS: direct/nested/filtered/duplicate events, same-name deletion, rename and inbound/outbound moves");
#endif
    return 0;
}
'''


COMMAND_SHIM = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef uint32_t DWORD;
typedef intptr_t LPARAM, LRESULT;
typedef uintptr_t WPARAM;
typedef void *HWND;
typedef int IContextMenu3, IShellBrowser, IShellView;
typedef struct { int desktop; } ContextMenu;
typedef int HRESULT;
typedef struct { HWND hwnd; const char *lpVerb; } CMINVOKECOMMANDINFO;
typedef const CMINVOKECOMMANDINFO *LPCMINVOKECOMMANDINFO;
typedef struct {
    struct { unsigned ViewMode; } FolderSettings;
    struct { unsigned nHeaderID, nLastHeaderID; int bIsAscending; } ListViewSortInfo;
    HWND hWndList;
} IShellViewImpl;
enum { TRUE=1, S_OK=0, WM_COMMAND=1, CWM_GETISHELLBROWSER=2, LVM_SORTITEMS=3,
       FVM_SMALLICON=1, FVM_ICON=2, FVM_LIST=3, FVM_DETAILS=4,
       LVS_SMALLICON=1, LVS_ICON=2, LVS_LIST=3, LVS_REPORT=4, LVS_TYPEMASK=3,
       SW_SHOWNORMAL=1 };
#define WINAPI
#define TRACE(...) ((void)0)
#define FIXME(...) ((void)0)
#define SUCCEEDED(hr) ((hr)>=0)
#define LOWORD(value) ((uintptr_t)(value)&0xffff)
#define HIWORD(value) (((uintptr_t)(value)>>16)&0xffff)
#define MAKEWPARAM(low,high) ((WPARAM)(low)|((WPARAM)(high)<<16))
#define CMDSTR_NEWFOLDERA "NewFolder"
#define CMDSTR_VIEWLISTA "ViewList"
#define CMDSTR_VIEWDETAILSA "ViewDetails"
static IShellViewImpl view;
static IShellBrowser browser;
static IShellView shellview;
static ContextMenu menu;
static unsigned new_folders, pastes, sorts, command_id;
static void SetStyle(IShellViewImpl *v, unsigned style, unsigned mask) { (void)v; (void)style; (void)mask; }
static void CheckToolbar(IShellViewImpl *v) { (void)v; }
static void ShellView_ListViewCompareItems(void) {}
static LRESULT SendMessageW(HWND hwnd, unsigned message, WPARAM wparam, LPARAM lparam)
{
    (void)hwnd; (void)wparam; (void)lparam;
    assert(message==LVM_SORTITEMS);
    sorts++;
    return 0;
}
static LRESULT SendMessageA(HWND hwnd, unsigned message, WPARAM wparam, LPARAM lparam);
static ContextMenu *impl_from_IContextMenu3(IContextMenu3 *iface) { (void)iface; return &menu; }
static HRESULT IShellBrowser_QueryActiveShellView(IShellBrowser *b, IShellView **result)
{ assert(b==&browser); *result=&shellview; return S_OK; }
static void IShellView_GetWindow(IShellView *v, HWND *result) { assert(v==&shellview); *result=&view; }
static void IShellView_Release(IShellView *v) { assert(v==&shellview); }
static void IShellView_Refresh(IShellView *v) { assert(v==&shellview); }
static void DoNewFolder(ContextMenu *m, IShellView *v) { assert(m==&menu && v==&shellview); new_folders++; }
static void do_paste(ContextMenu *m, HWND hwnd) { assert(m==&menu && hwnd==&view); pastes++; }
static void ShellExecuteA(HWND h, const char *v, const char *f, const char *p, const char *d, int s)
{ (void)h; (void)v; (void)f; (void)p; (void)d; (void)s; }
'''


COMMAND_HARNESS = r'''
static LRESULT SendMessageA(HWND hwnd, unsigned message, WPARAM wparam, LPARAM lparam)
{
    assert(hwnd==&view);
    if (message==CWM_GETISHELLBROWSER) return (LRESULT)&browser;
    assert(message==WM_COMMAND);
    command_id=LOWORD(wparam);
    return ShellView_OnCommand(&view,command_id,HIWORD(wparam),(HWND)lparam);
}
static void invoke(unsigned offset)
{
    CMINVOKECOMMANDINFO info={&view,(const char *)(uintptr_t)offset};
    assert(BackgroundMenu_InvokeCommand(NULL,&info)==S_OK);
}
int main(void)
{
    unsigned firsts[]={0,1,0x100};
    unsigned resource_ids[]={FCIDM_SHVIEW_SMALLICON,FCIDM_SHVIEW_BIGICON,
                             FCIDM_SHVIEW_LISTVIEW,FCIDM_SHVIEW_REPORTVIEW};
    unsigned expected_modes[]={FVM_SMALLICON,FVM_ICON,FVM_LIST,FVM_DETAILS};
    for (unsigned b=0;b<3;b++)
    {
        /* The host subtracts idCmdFirst from each selected merged-menu ID. */
        for (unsigned i=0;i<4;i++)
        {
            unsigned selected=resource_ids[i]+firsts[b]-FCIDM_BASE;
            invoke(selected-firsts[b]);
            assert(command_id==resource_ids[i] && view.FolderSettings.ViewMode==expected_modes[i]);
        }
        for (unsigned column=0;column<4;column++)
        {
            invoke(0x80+column);
            assert(command_id==0x7080+column && view.ListViewSortInfo.nHeaderID==column);
            assert(view.ListViewSortInfo.bIsAscending && view.ListViewSortInfo.nLastHeaderID==column);
        }
        invoke(FCIDM_SHVIEW_NEWFOLDER-FCIDM_BASE);
        invoke(FCIDM_SHVIEW_INSERT-FCIDM_BASE);
    }
    assert(new_folders==3 && pastes==3 && sorts==12);
    return 0;
}
'''


class ShellFolderView(unittest.TestCase):
    def setUp(self):
        wine = Path(os.environ.get("IDECK_TEST_WINE_SOURCE", ROOT / "wine"))
        if not (wine / "dlls/shell32/shlview.c").is_file():
            self.skipTest("Requires the pinned Wine source checkout (present in IPA CI)")
        self.directory = tempfile.TemporaryDirectory(prefix="ideck-shell-")
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        target = self.work / "dlls/shell32"
        target.mkdir(parents=True)
        for name in FILES:
            shutil.copyfile(wine / "dlls/shell32" / name, target / name)
        subprocess.run(["git", "init", "-q", str(self.work)], check=True)
        reverse = ["git", "-C", str(self.work), "apply", "--reverse"]
        if subprocess.run(reverse + ["--check", str(OVERLAY.PATCH)], capture_output=True).returncode == 0:
            subprocess.run(reverse + [str(OVERLAY.PATCH)], check=True)
        self.original = {name: (target / name).read_text(encoding="utf-8") for name in FILES}
        OVERLAY.apply(self.work)
        self.patched = {name: (target / name).read_text(encoding="utf-8") for name in FILES}

    def test_production_notification_handling(self):
        compiler = os.environ.get("IDECK_TEST_CC") or shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        for label, sources in (("before", self.original), ("after", self.patched)):
            with self.subTest(variant=label):
                notify = sources["changenotify.c"]
                start = notify.index("else if( wEventId & ( SHCNE_ONEITEMEVENTS")
                routing = notify[start:notify.index("\n            }", start)]
                delivery = "static BOOL delivered(LONG wEventId, const char *old, const char *updated, const char *pidl)\n{\n"
                delivery += "const char *Pidls[2]={old,updated}; BOOL subtree=TRUE, notify=FALSE; if (0) notify=FALSE;\n"
                delivery += routing + "\nreturn notify;\n}\n"
                code = (SHIM + function(notify, "static BOOL should_notify(") + delivery
                        + function(sources["shlview.c"], "static LRESULT ShellView_OnChange(") + HARNESS)
                path = self.work / (label + ".c")
                binary = self.work / (label + (".exe" if os.name == "nt" else ""))
                path.write_text(code, encoding="utf-8")
                command = [compiler, "-std=c11", "-Werror", str(path), "-o", str(binary)]
                if label == "before":
                    command += ["-DEXPECT_STOCK_FAULT"]
                subprocess.run(command, check=True, timeout=60)
                subprocess.run([str(binary)], check=True, timeout=20)

    def test_background_resource_menu_ids(self):
        constants = (ROOT / "wine/include/shlobj.h").read_text(encoding="utf-8")
        ids = {name: int(value, 16) for name, value in re.findall(r"#define\s+(FCIDM_SHVIEW_\w+)\s+(0x[0-9a-fA-F]+)", constants)}
        # Inspect the complete resource, including the comments between its items.
        menu = self.patched["shell32.rc"].split("MENU_002 MENUEX", 1)[1].split("MENU_RECYCLEBIN", 1)[0]
        entries = re.findall(r'(POPUP|MENUITEM)\s+"([^"]*)"\s*,\s*(0x[0-9a-fA-F]+|FCIDM_SHVIEW_\w+)', menu)
        self.assertEqual(len([e for e in entries if e[0] == "POPUP"]), 3)
        for first in (0, 1, 0x100):
            with self.subTest(first=first):
                adjusted = {label: (int(value, 16) if value.startswith("0x") else ids[value]) + first - 0x7000
                            for _, label, value in entries}
                self.assertTrue(all(first <= value <= first + 0x100 for value in adjusted.values()), adjusted)
                self.assertEqual(len(set(adjusted.values())), len(adjusted), "Menu IDs must not alias other commands")
                self.assertEqual(adjusted["New &Folder"] - first, 0x53)
                self.assertEqual(adjusted["By &Name"] - first, 0x80)
                self.assertEqual(adjusted["By &Type"] - first, 0x82)

    def test_background_command_dispatch(self):
        compiler = os.environ.get("IDECK_TEST_CC") or shutil.which("clang") or shutil.which("cc")
        if not compiler:
            self.skipTest("Requires a C compiler (present in IPA CI)")
        header = (ROOT / "wine/include/shlobj.h").read_text(encoding="utf-8")
        constants = "\n".join(re.findall(r"^#define\s+FCIDM_(?:BASE|SHVIEW_\w+)\s+0x[0-9a-fA-F]+.*$",
                                       header + self.patched["shlview_cmenu.c"], re.M))
        source = function(self.patched["shlview_cmenu.c"], "static HRESULT WINAPI BackgroundMenu_InvokeCommand(")
        code = (constants + "\n" + COMMAND_SHIM
                + function(self.patched["shlview.c"], "static LRESULT ShellView_OnCommand(")
                + source + COMMAND_HARNESS)
        path = self.work / "commands.c"
        binary = self.work / ("commands.exe" if os.name == "nt" else "commands")
        path.write_text(code, encoding="utf-8")
        subprocess.run([compiler, "-std=c11", "-Werror", str(path), "-o", str(binary)], check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=20)

    def test_overlay_idempotency_and_build_entry_points(self):
        OVERLAY.apply(self.work)
        for name in FILES:
            self.assertEqual((self.work / "dlls/shell32" / name).read_text(encoding="utf-8"), self.patched[name])
        for name in ("build/windows-runtime/build.sh", "build/wine-i386/build.sh", "build/wine-pe/build-modules.sh"):
            self.assertIn('python3 "$R/build/wine-pe/apply-shell-patches.py"', (ROOT / name).read_text())


if __name__ == "__main__":
    unittest.main()
