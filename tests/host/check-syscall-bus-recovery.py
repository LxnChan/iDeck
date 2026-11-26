#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run production syscall recovery, TLS probe, and process watch code on the host.

The signal adapter models ARM64 context redirection; the protected pages and
signals are real. This does not replace an iPad Steam launch test.
"""
from pathlib import Path
import argparse
import importlib.util
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--require-native', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
signal = (root/'build/ntdll-unix/signal_arm64_ios.c').read_text(encoding='utf-8')
virtual = (root/'build/ntdll-unix/virtual_ios.c').read_text(encoding='utf-8')
thread = (root/'build/ntdll-unix/thread_ios.c').read_text(encoding='utf-8')
bridge = (root/'app/Madeira/WineProcessBridge.m').read_text(encoding='utf-8')
server = (root/'build/ntdll-unix/server_ios.c').read_text(encoding='utf-8')
screen = (root/'app/Madeira/DockStartScreen.swift').read_text(encoding='utf-8')

def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}', start)+2] + '\n'

bus = function(signal, 'static void bus_handler(')
assert bus.index('handle_syscall_fault( sigcontext, &rec )') < bus.index('    setup_exception( sigcontext, &rec );')
assert 'ios_fixup_x18_for_return( sigcontext );' in bus[bus.index('handle_syscall_fault( sigcontext, &rec )'):]
wrapper = function(server, 'void process_exit_wrapper( int status )')
assert wrapper.index('wine_process_did_exit( params->ImagePathName.Buffer,') < wrapper.index('ios_jit_reclaim_process( dead_peb );')
assert 'wine_watched_process_exit_status(&status)' in screen
assert 'hostExit: hostExit' in screen and 'wine_watch_process_exit(nil, 0)' in screen
print('PASS: SIGBUS returns through syscall recovery; process exit is observed before reclaim')

spec = importlib.util.spec_from_file_location('loader_overlays', root/'build/wine-pe/apply-loader-patches.py')
overlay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overlay)
with tempfile.TemporaryDirectory(prefix='ideck-bus-recovery-') as directory:
    work = Path(directory)
    loader = work/'dlls/ntdll/loader.c'
    loader.parent.mkdir(parents=True)
    loader.write_text((root/'wine/dlls/ntdll/loader.c').read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    overlay.apply(work)
    patched = loader.read_text(encoding='utf-8')
    overlay.apply(work)
    assert loader.read_text(encoding='utf-8') == patched
    assert 'NtReadVirtualMemory( GetCurrentProcess(), blocks[' not in patched
    probe = function(patched, 'static NTSTATUS detach_probe_read(')
    print('PASS: both TLS diagnostic reads use the bounded overlay; application is idempotent')
    cc = shutil.which('cc') or shutil.which('clang')
    if not cc:
        if args.require_native:
            raise SystemExit('A native C compiler is required')
        print('SKIP: native signal, guard-page, and process watch checks require cc/clang')
        raise SystemExit(0)

    headers = r''' 
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
#include <signal.h>
#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>
typedef int BOOL;
typedef uint32_t DWORD, NTSTATUS;
typedef uint64_t DWORD64;
typedef uintptr_t ULONG_PTR;
typedef size_t SIZE_T;
typedef void *HANDLE;
#define WINAPI
#define TRUE 1
#define FALSE 0
#define TRACE(...) ((void)0)
#define STATUS_SUCCESS 0
#define STATUS_PARTIAL_COPY 0x8000000du
#define STATUS_ACCESS_VIOLATION 0xc0000005u
#define STATUS_INVALID_PARAMETER 0xc000000du
#define min(a,b) ((a)<(b)?(a):(b))
struct test_context { uintptr_t sp, pc, lr, fp, r[32]; };
struct syscall_frame { uintptr_t pc; };
static struct syscall_frame frame;
static struct { void *jmp_buf; } thread_data;
static void *ntdll_get_thread_data(void) { return &thread_data; }
#define ntdll_get_thread_data() (&thread_data)
static struct syscall_frame *get_syscall_frame(void) { return &frame; }
static BOOL is_inside_syscall(uintptr_t sp) { return sp == 1; }
static void *NtCurrentTeb(void) { return (void*)0x1234; }
static HANDLE GetCurrentProcess(void) { return (void*)-1; }
static void __wine_syscall_dispatcher_return(void) {}
#define SP_sig(c) ((c)->sp)
#define PC_sig(c) ((c)->pc)
#define LR_sig(c) ((c)->lr)
#define FP_sig(c) ((c)->fp)
#define REGn_sig(n,c) ((c)->r[n])
typedef struct { uint32_t ExceptionCode, ExceptionFlags, NumberParameters; void *ExceptionAddress; uintptr_t ExceptionInformation[15]; } EXCEPTION_RECORD;
static size_t host_page_size;
'''
    unixlib = (root/'wine/include/wine/unixlib.h').read_text(encoding='utf-8')
    macros = unixlib[unixlib.index('#define __TRY'):unixlib.index('\nNTSYSAPI BOOLEAN KeAddSystemServiceTable')]
    recovery = function(signal, 'static BOOL handle_syscall_fault(').replace('ucontext_t', 'struct test_context')
    set_jump = function(thread, 'void ntdll_set_exception_jmp_buf(')
    write_check = function(virtual, 'BOOL virtual_check_buffer_for_write(')
    read_start = virtual.index('NTSTATUS WINAPI NtReadVirtualMemory(')
    read = virtual[read_start:virtual.index('#ifdef WINE_IOS', read_start)]
    read += '    if (bytes_read) *bytes_read = size;\n    return status;\n}\n'
    server_stubs = r'''
struct test_request { HANDLE handle; const void *addr; };
#define SERVER_START_REQ(name) do { struct test_request data; struct test_request *req = &data;
#define SERVER_END_REQ } while(0);
#define wine_server_obj_handle(h) (h)
#define wine_server_client_ptr(p) (p)
#define wine_server_set_reply(req,buffer,size) ((void)0)
#define wine_server_call(req) STATUS_INVALID_PARAMETER
static SIZE_T heap_size;
static void *GetProcessHeap(void) { return (void*)1; }
static SIZE_T RtlSizeHeap(void *heap, int flags, const void *block) { (void)heap; (void)flags; (void)block; return heap_size; }
'''
    watch_start = bridge.index('static pthread_mutex_t g_process_exit_lock')
    watch_end = bridge.index('static char *g_prefix_path', watch_start)
    watch = bridge[watch_start:watch_end]
    checks = r'''
static volatile sig_atomic_t signal_count;
static void signal_adapter(int sig) {
    struct test_context ctx = {.sp = 1};
    EXCEPTION_RECORD rec = {.ExceptionCode = STATUS_ACCESS_VIOLATION};
    assert(handle_syscall_fault(&ctx, &rec));
    assert(ctx.pc == (uintptr_t)longjmp && !thread_data.jmp_buf);
    signal_count++;
    sigset_t unblock;
    sigemptyset(&unblock); sigaddset(&unblock, sig);
    sigprocmask(SIG_UNBLOCK, &unblock, NULL);
    longjmp(*(jmp_buf*)ctx.r[0], (int)ctx.r[1]);
}
static void watch_path(const uint16_t *image, size_t length) { wine_watch_process_exit(image, (uint32_t)length); }
static void *exit_worker(void *arg) {
    const uint16_t *image = arg;
    for (unsigned i=0; i<10000; i++) wine_process_did_exit(image, 3, (int)0x80000101u);
    return NULL;
}
int main(void) {
    struct sigaction action = {0};
    action.sa_handler = signal_adapter;
    sigemptyset(&action.sa_mask);
    assert(!sigaction(SIGBUS, &action, NULL));
    assert(!sigaction(SIGSEGV, &action, NULL));
    host_page_size = (size_t)sysconf(_SC_PAGESIZE);
    char *pages = mmap(NULL, host_page_size*2, PROT_READ|PROT_WRITE, MAP_ANON|MAP_PRIVATE, -1, 0);
    assert(pages != MAP_FAILED);
    memset(pages, 0x5a, host_page_size);
    assert(!mprotect(pages+host_page_size, host_page_size, PROT_NONE));
    char out[1024]; SIZE_T got = 123;
    /* Reproduce a small TLS block ending at an inaccessible reservation. */
    heap_size = 773;
    char *tls = pages+host_page_size-heap_size;
    assert(!detach_probe_read(tls, out, sizeof(out), &got) && got == heap_size);
    assert(signal_count == 0);
    assert(NtReadVirtualMemory(GetCurrentProcess(), tls, out, sizeof(out), &got) == STATUS_PARTIAL_COPY && got == 0);
    assert(signal_count && !thread_data.jmp_buf);
    for (unsigned i=0; i<20; i++) {
        assert(!NtReadVirtualMemory(GetCurrentProcess(), tls, out, 32, &got) && got == 32);
        assert(NtReadVirtualMemory(GetCurrentProcess(), pages+host_page_size, out, 16, &got) == STATUS_PARTIAL_COPY && got == 0);
        assert(NtReadVirtualMemory(GetCurrentProcess(), pages, pages+host_page_size, 16, &got) == STATUS_ACCESS_VIOLATION && got == 0);
        assert(!thread_data.jmp_buf);
    }
    /* Explicit SIGBUS also clears __TRY before the next protected operation. */
    __TRY { raise(SIGBUS); abort(); } __EXCEPT { assert(!thread_data.jmp_buf); } __ENDTRY
    heap_size = 8;
    assert(!detach_probe_read(tls, out, sizeof(out), &got) && got == 8);
    heap_size = 2048;
    assert(!detach_probe_read(pages, out, sizeof(out), &got) && got == sizeof(out));
    heap_size = ~(SIZE_T)0;
    assert(detach_probe_read(tls, out, sizeof(out), &got) == STATUS_INVALID_PARAMETER && got == 0);
    struct test_context ctx = {.sp = 1}; EXCEPTION_RECORD rec = {.ExceptionCode = 0xc0000005u};
    assert(handle_syscall_fault(&ctx, &rec) && ctx.r[0] == rec.ExceptionCode && ctx.r[18] == 0x1234);
    assert(ctx.pc == (uintptr_t)__wine_syscall_dispatcher_return);
    ctx.sp = 0;
    assert(!handle_syscall_fault(&ctx, &rec));
    const uint16_t image[] = {'C',':','/','H','.','e','x','e'};
    const uint16_t same[] = {'c',':','\\','h','.','E','X','E'};
    const uint16_t other[] = {'D',':','/','H','.','e','x','e'};
    uint32_t status = 123;
    watch_path(image, 8);
    assert(!wine_watched_process_exit_status(&status));
    wine_process_did_exit(other, 8, 1);
    assert(!wine_watched_process_exit_status(&status));
    wine_process_did_exit(same, 8, (int)0x80000101u);
    assert(wine_watched_process_exit_status(&status) && status == 0x80000101u);
    wine_process_did_exit(same, 8, 0);
    assert(wine_watched_process_exit_status(&status) && status == 0x80000101u);
    watch_path(image, 8);
    wine_process_did_exit(same, 8, 0);
    assert(wine_watched_process_exit_status(&status) && status == 0);
    wine_watch_process_exit(NULL, 0);
    wine_process_did_exit(same, 8, 1);
    assert(!wine_watched_process_exit_status(NULL));
    uint16_t huge[1025] = {1};
    watch_path(huge, 1025);
    assert(!wine_watched_process_exit_status(NULL));
    const uint16_t unicode[] = {0x4e2d, 0x6587, 0xd83d};
    watch_path(unicode, 3);
    pthread_t worker; assert(!pthread_create(&worker, NULL, exit_worker, (void*)unicode));
    for (unsigned i=0; i<10000; i++) wine_watched_process_exit_status(&status);
    pthread_join(worker, NULL);
    assert(wine_watched_process_exit_status(&status) && status == 0x80000101u);
    munmap(pages, host_page_size*2);
    puts("PASS: guard-page reads recover repeatedly, TLS reads stay bounded, and watched exits survive worker-thread termination");
    return 0;
}
'''
    source = work/'recovery.c'
    source.write_text(headers+set_jump+macros+recovery+write_check+server_stubs+read+probe+watch+checks, encoding='utf-8')
    binary = work/'recovery'
    subprocess.run([cc, '-std=gnu11', '-O1', '-g', '-Wall', '-Werror=implicit-function-declaration',
                    '-fsanitize=undefined', '-fno-sanitize-recover=undefined', '-pthread', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=30)
