#!/usr/bin/env python3
"""Compile the production input queue/drain with concurrent Wine-thread stubs.

Checks FIFO mouse down/up and key delivery, enqueueing during a paused dispatch,
nonblocking competing consumers, and recursive event polls. Needs a POSIX C
compiler with pthreads; --source-only checks extraction/wiring without one.
Also removes drain serialization in a temporary negative control, which must
reproduce an up delivered before its down.
"""
from pathlib import Path
import argparse
import os
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
source = (root / 'app/Madeira/Winios/Winios.m').read_text(encoding='utf-8')
queue = source.split('#define WINIOS_RING_SIZE', 1)[1].split(
    'static void winios_game_cursor_touch', 1)[0]
queue = '#define WINIOS_RING_SIZE' + queue
start = source.index('BOOL winios_pProcessEvents(DWORD mask) {')
drain = source[start:source.index('\n}\n', start) + 3]
assert 'pthread_mutex_trylock(&g_input_drain_lock)' in drain
assert drain.index('pthread_mutex_trylock(&g_input_drain_lock)') < drain.index('static unsigned int cnt;')
assert drain.index('pthread_mutex_unlock(&g_input_drain_lock)') > drain.index('winios_drv_post_mouse(')
assert 'pthread_mutex_unlock(&g_input_q.lock);\n\n        const char *session' in drain
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-only', action='store_true')
args = parser.parse_args()
if args.source_only:
    print('PASS: production queue/drain extraction and separate nonblocking drain ownership')
    raise SystemExit(0)

harness = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef int BOOL;
typedef unsigned int DWORD;
typedef void *HWND;
#define TRUE 1
#define FALSE 0
#define MOUSEEVENTF_LEFTDOWN 2
#define MOUSEEVENTF_LEFTUP 4
static _Atomic(uintptr_t) g_restore_foreground;
static int winios_drv_foreground_if_owner(HWND hwnd) { (void)hwnd; return 0; }
static double CACurrentMediaTime(void) { return 0; }
static void winios_dump_window_tree(void) {}
BOOL winios_pProcessEvents(DWORD mask);

struct delivery { unsigned int type, flags; int sequence; };
static struct delivery delivered[1024];
static int delivered_count;
static pthread_mutex_t test_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t test_condition = PTHREAD_COND_INITIALIZER;
static int pause_first, first_waiting, release_first, recursive_poll;

static void record(unsigned int type, int sequence, unsigned int flags)
{
    pthread_mutex_lock(&test_lock);
    assert(delivered_count < 1024);
    delivered[delivered_count++] = (struct delivery){type, flags, sequence};
    pthread_mutex_unlock(&test_lock);
}

static void winios_drv_post_mouse(int x, int y, unsigned int flags,
                                  unsigned int mouse_data, HWND hwnd)
{
    (void)y; (void)mouse_data; (void)hwnd;
    if (recursive_poll) {
        recursive_poll = 0;
        assert(!winios_pProcessEvents(0));
    }
    pthread_mutex_lock(&test_lock);
    if (pause_first && x == 1) {
        first_waiting = 1;
        pthread_cond_signal(&test_condition);
        while (!release_first) pthread_cond_wait(&test_condition, &test_lock);
    }
    pthread_mutex_unlock(&test_lock);
    record(0, x, flags);
}

static void winios_drv_post_key(unsigned short vk, unsigned int flags)
{
    record(1, vk, flags);
}
''' + queue + drain + r'''

static void *poll(void *unused)
{
    (void)unused;
    winios_pProcessEvents(0);
    return NULL;
}

static void verify(int count)
{
    assert(delivered_count == count);
    for (int i = 0; i < count; i++) {
        const struct delivery *event = &delivered[i];
        assert(event->sequence == i + 1);
        if ((i + 1) % 3 == 0) {
            assert(event->type == WINIOS_EV_KEY && event->flags == 0);
        } else {
            assert(event->type == WINIOS_EV_MOUSE);
            assert(event->flags == ((i + 1) % 3 == 1 ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP));
        }
    }
}

static void enqueue(int sequence)
{
    if (sequence % 3 == 0)
        winios_q_push_ev(WINIOS_EV_KEY, sequence, 0, 0, 0);
    else
        winios_q_push_ev(WINIOS_EV_MOUSE, sequence, 0,
                         sequence % 3 == 1 ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP, 0);
}

int main(void)
{
    pthread_t first, consumers[8];
    assert(!winios_pProcessEvents(0));

    /* DOWN is popped but its dispatch stalls. Another poll must not send UP
     * first, and the producer must still be able to enqueue a key immediately. */
    enqueue(1); enqueue(2);
    pause_first = 1;
    assert(!pthread_create(&first, NULL, poll, NULL));
    pthread_mutex_lock(&test_lock);
    while (!first_waiting) pthread_cond_wait(&test_condition, &test_lock);
    pthread_mutex_unlock(&test_lock);
    enqueue(3);
    BOOL competing_drained = winios_pProcessEvents(0);
    pthread_mutex_lock(&test_lock);
    int competing_deliveries = delivered_count;
    release_first = 1;
    pthread_cond_signal(&test_condition);
    pthread_mutex_unlock(&test_lock);
    assert(!pthread_join(first, NULL));
    verify(3);
    assert(!competing_drained && competing_deliveries == 0);
    assert(!winios_pProcessEvents(0));

    /* A Wine dispatch may recursively poll. It cannot drain the queued UP
     * before the outer call has finished sending DOWN, or deadlock itself. */
    delivered_count = 0;
    pause_first = 0;
    recursive_poll = 1;
    enqueue(1); enqueue(2); enqueue(3);
    assert(winios_pProcessEvents(0));
    verify(3);

    /* Many polling threads repeatedly see the same shared queue, including
     * wraparound of its producer/consumer cursors, without reordering events. */
    for (int iteration = 0; iteration < 40; iteration++) {
        delivered_count = 0;
        for (int sequence = 1; sequence <= 180; sequence++) enqueue(sequence);
        for (int i = 0; i < 8; i++) assert(!pthread_create(&consumers[i], NULL, poll, NULL));
        for (int i = 0; i < 8; i++) assert(!pthread_join(consumers[i], NULL));
        verify(180);
        assert(!winios_pProcessEvents(0));
    }
    puts("PASS: production input FIFO, concurrent down/up/key delivery, producer independence and recursive nonblocking polls");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='ideck-input-queue-') as temp:
    temp = Path(temp)
    cfile, binary = temp / 'input_queue.c', temp / 'input_queue'
    cfile.write_text(harness, encoding='utf-8')
    compiler = [os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-parameter', '-pthread']
    subprocess.run(compiler + [str(cfile), '-o', str(binary)], check=True)
    env = dict(os.environ, MADEIRA_QUIET='1', MADEIRA_DESKTOP='0')
    result = subprocess.run([str(binary)], check=True, env=env, capture_output=True, text=True, timeout=20)
    print(result.stdout, end='')

    # Keep the same queue, dispatch stubs and paused-DOWN scenario. Removing only
    # drain ownership must fail the actual FIFO assertion, not merely a source
    # check or the busy-poller assertion.
    previous = harness.replace(
        'static pthread_mutex_t g_input_drain_lock = PTHREAD_MUTEX_INITIALIZER;', '').replace(
        'if (pthread_mutex_trylock(&g_input_drain_lock)) return FALSE;', '').replace(
        'pthread_mutex_unlock(&g_input_drain_lock);', '')
    cfile.write_text(previous, encoding='utf-8')
    subprocess.run(compiler + [str(cfile), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and 'event->sequence == i + 1' in result.stderr, (
        'negative control did not reproduce reversed down/up delivery', result.stdout, result.stderr)
    print('PASS: removing drain serialization reproduces UP-before-DOWN delivery')
