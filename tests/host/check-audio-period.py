#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Compile the real period negotiation, mixer and polling timer against host stubs.

Check hardware-frame rounding, short and long I/O quanta, invalid session data,
and the diagnostics for a polling client feeding 480 frames per 1024-frame pass.
No Wine or Apple frameworks are required.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
src = (ROOT / "build/ntdll-unix/audio_null_ios.c").read_text(encoding="utf-8")
bridge = (ROOT / "app/Madeira/WineProcessBridge.m").read_text(encoding="utf-8")


def cut(text, start, end):
    a = text.index(start)
    return text[a:text.index(end, a)]


session_period = cut(bridge, "uint64_t madeira_audio_output_period_100ns(void)", "/* ---- ml581")
session_period = session_period.replace(
    "AVAudioSession *session = [AVAudioSession sharedInstance];", ""
).replace("session.IOBufferDuration", "test_duration").replace("session.sampleRate", "test_rate")

harness = r"""
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <math.h>
typedef uint32_t UINT32, UInt32;
typedef uint8_t BYTE;
typedef void *HANDLE;
typedef uint64_t stream_handle;
typedef int64_t REFERENCE_TIME;
typedef int NTSTATUS;
#define S_OK 0
#define STATUS_SUCCESS 0
#define IOS_AUDIO_SAMPLE_RATE 48000
#define LOG_FN_CALL(a, b) ((void)0)
struct get_device_period_params {
    const char *device; int flow; int result;
    REFERENCE_TIME *def_period, *min_period;
};
struct timer_loop_params { stream_handle stream; };
static double test_duration, test_rate;
""" + session_period + cut(src, "struct ios_stream {", "/* ml739: one stream object per client") + r"""
static struct ios_stream stream;
static struct { _Atomic uint64_t clamped; } g_dev;
static uint64_t now_ns, next_pass;
static int events, rt_calls, legacy_sleeps;
static BYTE ring[4800 * 8];
static struct ios_stream *stream_from_handle(stream_handle h) { (void)h; return &stream; }
static int ios_stream_is_live(const struct ios_stream *s) { return s->mixable; }
static UINT32 ios_audio_lead_ms(void) { return 60; }
static void ios_audio_timer_thread_rt(void) { rt_calls++; }
static void NtSetEvent(HANDLE h, void *p) { (void)h; (void)p; events++; }
static uint64_t mach_absolute_time(void) { return now_ns; }
static uint64_t mach_to_ns(uint64_t t) { return t; }
static uint64_t ns_to_mach(uint64_t t) { return t; }
static void tick(uint64_t deadline);
static void mach_wait_until(uint64_t deadline) { tick(deadline); }
static void usleep(unsigned t) { legacy_sleeps++; tick(now_ns + (uint64_t)t * 1000); }
""" + cut(src, "static void ios_mix_stream(", "/* Core Audio real-time thread. See ios_mix_stream") + r"""
static void tick(uint64_t deadline) {
    now_ns = deadline;
    while (next_pass <= now_ns) {
        float output[1024 * 2] = {0};
        atomic_fetch_add(&stream.write_pos, 480);
        ios_mix_stream(&stream, output, 1024, 2, 48000);
        next_pass += 21333333;
    }
    if (now_ns >= 10040000000ull) stream.valid = 0;
}
""" + cut(src, "static NTSTATUS ios_timer_loop(", "static NTSTATUS ios_get_render_buffer(") + cut(
    src, "static REFERENCE_TIME ios_audio_device_period(", "static NTSTATUS ios_get_buffer_size("
) + r"""
#define CHECK(c) do { if (!(c)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #c); return 1; } } while (0)
int main(void) {
    REFERENCE_TIME def, min;
    struct get_device_period_params p = {0};
    struct timer_loop_params timer = {0};
    p.def_period = &def; p.min_period = &min;
    const unsigned rates[] = {44100, 48000, 96000};
    for (unsigned r = 0; r < 3; r++) {
        for (unsigned frames = 256; frames <= 4096; frames *= 2) {
            test_rate = rates[r]; test_duration = (double)frames / test_rate;
            CHECK(ios_get_device_period(&p) == STATUS_SUCCESS && p.result == S_OK);
            uint64_t ticks = madeira_audio_output_period_100ns();
            CHECK(ticks * rates[r] / 10000000 == frames);
            CHECK(def >= min && min >= 50000 && def >= 100000);
            CHECK((uint64_t)min >= ticks);
        }
    }
    test_rate = 48000; test_duration = 1024.0 / 48000;
    ios_get_device_period(&p);
    CHECK(def == 213334 && min == 213334);
    CHECK((uint64_t)def * 48000 / 10000000 == 1024);
    /* 10 ms devices keep the historical default; 2.7 ms devices keep a 5 ms minimum. */
    test_duration = 0.01; ios_get_device_period(&p);
    CHECK(def == 100000 && min == 100000);
    test_duration = 128.0 / 48000; ios_get_device_period(&p);
    CHECK(def == 100000 && min == 50000);
    const double invalid[] = {0.0, -1.0, 2.0, NAN, INFINITY};
    for (unsigned i = 0; i < sizeof(invalid) / sizeof(invalid[0]); i++) {
        test_duration = invalid[i]; ios_get_device_period(&p);
        CHECK(def == 100000 && min == 50000);
    }
    test_duration = 0.02; test_rate = NAN;
    CHECK(madeira_audio_output_period_100ns() == 0);
    test_rate = 0; CHECK(madeira_audio_output_period_100ns() == 0);
    p.def_period = p.min_period = NULL; ios_get_device_period(&p);

    /* No event handle: this must still report the 53% shortfall, without
     * inventing client audio or calling Wine from the render callback. */
    stream.valid = stream.started = stream.mixable = 1;
    stream.sample_rate = 48000; stream.channels = 2; stream.frame_bytes = 8;
    stream.sample_bits = 32; stream.is_float = 1;
    stream.buffer_frames = 4800; stream.ring = ring;
    next_pass = 21333333;
    CHECK(ios_timer_loop(&timer) == STATUS_SUCCESS);
    CHECK(!events && rt_calls == 1 && !legacy_sleeps);
    CHECK(atomic_load(&stream.st_cb_max) == 1024);
    CHECK(atomic_load(&stream.st_short_cbs) > 460);
    puts("ok");
    return 0;
}
"""

compiler = os.environ.get("CC") or shutil.which("cc") or shutil.which("clang")
if not compiler:
    raise SystemExit("A C11 compiler (CC, cc or clang) is required")
with tempfile.TemporaryDirectory() as tmp:
    c = Path(tmp) / "audio-period.c"
    exe = Path(tmp) / ("audio-period.exe" if sys.platform == "win32" else "audio-period")
    c.write_text(harness, encoding="utf-8")
    flags = ["-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function"]
    if sys.platform != "win32":
        flags += ["-fsanitize=address,undefined"]
    subprocess.run([compiler, *flags, str(c), "-o", str(exe), "-lm"], check=True)
    result = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "ok", result.stdout
    assert "mode=poll" in result.stderr, result.stderr
    assert re.search(r"\(46\.[89]%\).*device short 53\d\d\.\d ms", result.stderr), result.stderr
    assert "largest pass 1024 frames" in result.stderr, result.stderr
print("PASS: WASAPI periods cover the active I/O quantum and preserve hardware frames")
print("PASS: polling streams report the 480/1024 shortfall and callback size without events")
