#!/usr/bin/env python3
"""Compile the production snapshot transport and win32u query on a POSIX host.

No Wine, game, controller, SDK or credentials are needed. Run with python3.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
driver = (root / 'build/win32u-unix/driver_ios.c').read_text()
query = driver[driver.index('/* ml1920: same-task controller snapshots'):]
# The foreground fix (#149) calls into win32u's windows; this check has none of it.
foreground = query.index('/* There is no window manager on iOS')
foreground_end = query.index('\n}\n', query.index('static void ios_foreground_check(void)')) + 3
query = query[:foreground] + 'static void ios_foreground_check(void) { foreground_check_calls++; }\n' + query[foreground_end:]
types = r'''
#include <stdint.h>
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
typedef uint8_t BYTE;
typedef uint16_t WORD;
typedef int16_t SHORT;
typedef uint32_t DWORD;
typedef unsigned int UINT;
typedef uintptr_t ULONG_PTR;
typedef uintptr_t HWND;
#define C_ASSERT(x) _Static_assert(x, #x)
static HWND foreground_hwnd;
static DWORD foreground_pid, foreground_thread;
static unsigned foreground_reads, foreground_check_calls;
static HWND NtUserGetForegroundWindow(void) { foreground_reads++; return foreground_hwnd; }
static DWORD get_window_thread(HWND hwnd, DWORD *pid)
{
    assert(hwnd == foreground_hwnd);
    if (pid) *pid = foreground_pid;
    return foreground_thread;
}
static DWORD GetCurrentProcessId(void) { return 42; }
'''
tests = r'''
static atomic_int finished;
static int notified;
static void count_notify(void) { notified++; }
static struct winios_gamepad patterns[2];
static void *writer(void *arg) {
    uintptr_t which = (uintptr_t)arg;
    for (int i = 0; i < 100000; ++i)
        winios_gamepad_set_state(0, &patterns[which]);
    atomic_fetch_add(&finished, 1);
    return NULL;
}
int main(int argc, char **argv) {
    struct winios_gamepad state = {0}, result;
    struct ios_xinput_state output;
    struct ios_xinput_caps caps;
    DWORD flags = 0xdeadbeef, rule;
    assert(argc == 2);
    rule = (DWORD)atoi(argv[1]);
    assert(sizeof(state) == 20);
    assert(!winios_gamepad_get_state(-1, &result) && !result.connected);
    assert(!winios_gamepad_get_state(4, &result));
    /* Op 3 has a DWORD payload and queries the window owner even without a pad.
     * Invalid parameters must not read the window state or touch the buffer. */
    assert(!ios_gamepad_query(0, 3, NULL));
    assert(!ios_gamepad_query(4, 3, &flags) && flags == 0xdeadbeef);
    assert(!ios_gamepad_query(~0u, 3, &flags) && flags == 0xdeadbeef);
    assert(!foreground_reads && !foreground_check_calls);
    foreground_hwnd = 1; foreground_pid = 42; foreground_thread = 7;
    assert(ios_gamepad_query(0, 3, &flags) == rule && flags == (rule | 0x2));
    assert(ios_gamepad_query(3, 3, &flags) == rule && flags == (rule | 0x2));
    foreground_pid = 43;
    assert(!ios_gamepad_query(0, 3, &flags) && flags == rule);
    foreground_pid = 42; foreground_thread = 0;
    assert(!ios_gamepad_query(0, 3, &flags) && flags == rule);
    foreground_thread = 7; foreground_hwnd = 0;
    assert(!ios_gamepad_query(0, 3, &flags) && flags == rule);
    assert(foreground_reads == 5 && !foreground_check_calls);
    assert(!ios_gamepad_query(0, 0, &output));
    state.connected = 1; state.buttons = 0x1011;
    state.lx = -32768; state.ly = 32767;
    state.rx = -1234; state.ry = 5678;
    state.left_trigger = 255; state.right_trigger = 17;
    state.packet = 99;
    winios_gamepad_set_state(0, &state);
    assert(winios_gamepad_get_state(0, &result) && result.packet == 1);
    state.packet = 999;
    winios_gamepad_set_state(0, &state);
    assert(winios_gamepad_get_state(0, &result) && result.packet == 1);
    assert(ios_gamepad_query(0, 0, &output));
    assert(output.packet_number == 1 && output.gamepad.buttons == 0x1011);
    assert(output.gamepad.thumb_lx == -32768 && output.gamepad.thumb_ly == 32767);
    assert(output.gamepad.thumb_rx == -1234 && output.gamepad.thumb_ry == 5678);
    assert(output.gamepad.left_trigger == 255 && output.gamepad.right_trigger == 17);
    assert(ios_gamepad_query(0, 1, &caps));
    assert(caps.type == 1 && caps.sub_type == 1 && caps.flags == 0);
    assert(caps.left_motor_speed == 0 && caps.right_motor_speed == 0);
    /* ml2106: motors are advertised only while the app plays them. */
    winios_gamepad_set_rumble_caps(1);
    assert(ios_gamepad_query(0, 1, &caps) && caps.flags == 0);
    assert(caps.left_motor_speed == 0xff && caps.right_motor_speed == 0xff);
    winios_gamepad_set_rumble_caps(0);
    /* ml2106: op 2 (NtUserGamepadOp_SetVibration) takes XINPUT_VIBRATION in; each change notifies once. */
    {
        WORD motors[2] = { 0xffff, 0x1234 };
        struct winios_gamepad_vibration v;
        notified = 0;
        winios_pad_output_set_notify(count_notify);
        assert(!winios_gamepad_get_vibration(0, &v) && !v.left && !v.right);
        assert(ios_gamepad_query(0, 2, motors));
        assert(winios_gamepad_get_vibration(0, &v) == 1 && v.left == 0xffff && v.right == 0x1234);
        assert(notified == 1);
        assert(ios_gamepad_query(0, 2, motors));          /* same values: no new serial, no notify */
        assert(winios_gamepad_get_vibration(0, &v) == 1 && notified == 1);
        motors[0] = 0; motors[1] = 0;
        assert(ios_gamepad_query(0, 2, motors));
        assert(winios_gamepad_get_vibration(0, &v) == 2 && !v.left && !v.right && notified == 2);
        assert(!ios_gamepad_query(1, 2, motors));         /* no pad in slot 1: nothing stored */
        assert(!winios_gamepad_get_vibration(1, &v));
        assert(!winios_gamepad_get_vibration(4, &v) && !winios_gamepad_get_vibration(-1, &v));
        winios_gamepad_set_vibration(9, 1, 1);             /* out of range: ignored */
        winios_pad_output_set_notify(NULL);
        winios_gamepad_set_vibration(0, 5, 5);
        assert(notified == 2 && winios_gamepad_get_vibration(0, &v) == 3);
    }
    flags = 0xdeadbeef;
    assert(!ios_gamepad_query(0, 4, &flags) && flags == 0xdeadbeef);
    assert(!ios_gamepad_query(4, 0, &output));
    assert(!ios_gamepad_query(0, 0, NULL));
    for (int i = 1; i < 4; ++i) {
        state.buttons = (uint16_t)(1 << i);
        winios_gamepad_set_state(i, &state);
        assert(winios_gamepad_get_state(i, &result) && result.buttons == (1 << i));
    }
    winios_gamepad_set_state(0, NULL);
    memset(&result, 0xff, sizeof(result));
    assert(!winios_gamepad_get_state(0, &result));
    struct winios_gamepad zero = {0};
    assert(!memcmp(&result, &zero, sizeof(result)));
    winios_gamepad_set_state(0, &state);
    assert(winios_gamepad_get_state(0, &result) && result.packet == 3);
    patterns[0] = state; patterns[1] = state;
    patterns[0].buttons = 0x1000; patterns[0].lx = -100; patterns[0].right_trigger = 0;
    patterns[1].buttons = 0x8000; patterns[1].lx = 100; patterns[1].right_trigger = 255;
    winios_gamepad_set_state(0, &patterns[0]);
    pthread_t threads[2];
    for (uintptr_t i = 0; i < 2; ++i) assert(!pthread_create(&threads[i], NULL, writer, (void *)i));
    do {
        assert(winios_gamepad_get_state(0, &result));
        unsigned i = result.buttons == 0x1000 ? 0 : 1;
        result.packet = patterns[i].packet;
        assert(!memcmp(&result, &patterns[i], sizeof(result)));
    } while (atomic_load(&finished) != 2);
    for (int i = 0; i < 2; ++i) assert(!pthread_join(threads[i], NULL));
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='madeira-gamepad-') as tmp:
    source = Path(tmp) / 'check.c'
    binary = Path(tmp) / 'check'
    source.write_text(types + query + tests)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-O2', '-pthread', '-I', str(root / 'build/win32u-unix'), str(source),
                    str(root / 'app/Madeira/Winios/WiniosGamepad.c'), '-o', str(binary)], check=True)
    for rule, value in ((1, None), (1, ''), (0, '0'), (1, '1')):
        environment = os.environ.copy()
        if value is None:
            environment.pop('MADEIRA_XINPUT_ENABLE_FOREGROUND', None)
        else:
            environment['MADEIRA_XINPUT_ENABLE_FOREGROUND'] = value
        subprocess.run([str(binary), str(rule)], env=environment, check=True)
print('PASS: packet changes, ranges, four slots, disconnect/reconnect, query ABI, concurrent snapshots, '
      'rumble caps, XInput vibration op (ml2106), foreground owner/rule op (ml2115)')
