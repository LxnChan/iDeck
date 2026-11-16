# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
"""Exercise source integrity, fence fallback and WGL initialization without a GPU."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mesa_build', ROOT / 'build/mesa-d3d12/build.py')
mesa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mesa)


def run_harness(test, name, code):
    compiler = os.environ.get('CXX') or shutil.which('c++') or shutil.which('clang++')
    if not compiler:
        test.skipTest('C++ compiler unavailable')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / (name + '.cpp')
        exe = root / (name + '.exe' if os.name == 'nt' else name)
        source.write_text(code, encoding='utf-8')
        command = [compiler, '-std=c++11', str(source), '-o', str(exe)]
        if os.name == 'nt':
            command.append('-static')
        result = subprocess.run(command, capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class MesaSourceChecks(unittest.TestCase):
    @unittest.skipUnless((mesa.HERE / 'dist/sources/mesa-25.0.7.tar.xz').is_file(),
                         'pinned Mesa source archive unavailable')
    def test_all_patches_apply_to_pristine_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            with tarfile.open(mesa.HERE / 'dist/sources/mesa-25.0.7.tar.xz') as archive:
                for _, relative, before, _ in mesa.PATCHES:
                    data = archive.extractfile('mesa-25.0.7/' + relative).read()
                    self.assertEqual(hashlib.sha256(data).hexdigest(), before, relative)
                    target = source / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            mesa.apply_patches(source)
            mesa.apply_patches(source)
            for _, relative, _, after in mesa.PATCHES:
                self.assertEqual(mesa.sha(source / relative), after, relative)

    def test_source_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'source.tar'
            with tarfile.open(archive, 'w') as output:
                item = tarfile.TarInfo('../escaped.txt')
                item.size = 3
                output.addfile(item, io.BytesIO(b'bad'))
            with self.assertRaisesRegex(ValueError, 'unsafe source'):
                mesa.extract(archive, root / 'extracted')
            self.assertFalse((root / 'escaped.txt').exists())

    def test_source_symlink_cannot_redirect_later_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'source.tar'
            with tarfile.open(archive, 'w') as output:
                item = tarfile.TarInfo('mesa/link')
                item.type = tarfile.SYMTYPE
                item.linkname = '../../outside'
                output.addfile(item)
                item = tarfile.TarInfo('mesa/link/source.c')
                item.size = 2
                output.addfile(item, io.BytesIO(b'ok'))
            mesa.extract(archive, root / 'extracted')
            self.assertFalse((root / 'outside').exists())
            self.assertEqual((root / 'extracted/mesa/link/source.c').read_bytes(), b'ok')

    def test_edited_source_cannot_be_blessed_by_editing_cached_file_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            files = {}
            for name in (*mesa.DLLS, mesa.PROBE, *('sources/' + n for n in mesa.SOURCES)):
                path = dist / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'replaced cache input')
                files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            (dist / mesa.MANIFEST).write_text(json.dumps({
                'recipe': mesa.recipe_key(), 'files': files,
                'patches': mesa.patch_manifest(),
                'sources': {name: values[1] for name, values in mesa.SOURCES.items()}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'pinned checksum'):
                mesa.verify(dist)

    @unittest.skipUnless(shutil.which('git'), 'git is required to apply source patches')
    def test_patch_is_idempotent_and_rejects_unexpected_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            (root / 'patches').mkdir()
            target = source / 'screen.cpp'
            before, after = b'original\n', b'patched\n'
            target.write_bytes(before)
            (root / 'patches/test.patch').write_text(
                '--- a/screen.cpp\n+++ b/screen.cpp\n@@ -1 +1 @@\n-original\n+patched\n',
                encoding='utf-8', newline='\n')
            patches = (('test.patch', 'screen.cpp', hashlib.sha256(before).hexdigest(),
                        hashlib.sha256(after).hexdigest()),)
            with mock.patch.object(mesa, 'HERE', root), mock.patch.object(mesa, 'PATCHES', patches):
                mesa.apply_patches(source)
                mesa.apply_patches(source)
                self.assertEqual(target.read_bytes(), after)
                target.write_bytes(b'local edits\n')
                with self.assertRaisesRegex(ValueError, 'unexpected Mesa patch input'):
                    mesa.apply_patches(source)
                self.assertEqual(target.read_bytes(), b'local edits\n')


class MesaFenceChecks(unittest.TestCase):
    def test_actual_submission_fence_helper(self):
        patch = (mesa.HERE / 'patches' / mesa.PATCHES[0][0]).read_text(encoding='utf-8')
        additions = '\n'.join(line[1:] for line in patch.splitlines()
                              if line.startswith('+') and not line.startswith('+++'))
        helper = re.search(r'static bool\nmadeira_create_submission_fence\b.*?\n}', additions, re.S)
        self.assertIsNotNone(helper)
        harness = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#define _debug_printf(...) fprintf(stderr, __VA_ARGS__)
using HRESULT = int32_t;
constexpr HRESULT S_OK = 0;
constexpr HRESULT E_NOTIMPL = static_cast<HRESULT>(0x80004001u);
constexpr HRESULT DXGI_ERROR_UNSUPPORTED = static_cast<HRESULT>(0x887a0004u);
constexpr HRESULT E_OUTOFMEMORY = static_cast<HRESULT>(0x8007000eu);
constexpr HRESULT E_FAIL = static_cast<HRESULT>(0x80004005u);
constexpr int D3D12_FENCE_FLAG_NONE = 0, D3D12_FENCE_FLAG_SHARED = 1;
#define SUCCEEDED(hr) ((hr) >= 0)
#define FAILED(hr) ((hr) < 0)
#define IID_PPV_ARGS(ptr) ptr
struct Fence {};
struct Device {
   HRESULT shared, local;
   std::vector<int> calls;
   Fence fence;
   HRESULT CreateFence(uint64_t initial, int flags, Fence **out) {
      assert(initial == 0);
      calls.push_back(flags);
      HRESULT hr = flags == D3D12_FENCE_FLAG_SHARED ? shared : local;
      *out = SUCCEEDED(hr) ? &fence : nullptr;
      return hr;
   }
};
struct d3d12_screen { Device *dev; Fence *fence; };
'''
        cases = r'''
static void check(HRESULT shared, HRESULT local, bool expected, bool fallback) {
   Device device{shared, local, {}, {}};
   d3d12_screen screen{&device, nullptr};
   assert(madeira_create_submission_fence(&screen) == expected);
   assert((screen.fence != nullptr) == expected);
   assert(device.calls.size() == (fallback ? 2u : 1u));
   assert(device.calls[0] == D3D12_FENCE_FLAG_SHARED);
   if (fallback) assert(device.calls[1] == D3D12_FENCE_FLAG_NONE);
}
int main() {
   check(S_OK, E_FAIL, true, false);
   check(E_NOTIMPL, S_OK, true, true);
   check(DXGI_ERROR_UNSUPPORTED, S_OK, true, true);
   check(E_OUTOFMEMORY, S_OK, false, false);
   check(E_FAIL, S_OK, false, false);
   check(E_NOTIMPL, E_OUTOFMEMORY, false, true);
   check(DXGI_ERROR_UNSUPPORTED, E_FAIL, false, true);
}
'''
        run_harness(self, 'fence', harness + helper.group() + cases)


class MesaPixelFormatChecks(unittest.TestCase):
    def test_actual_pixel_format_setter(self):
        patch = (mesa.HERE / 'patches/0002-accept-identical-window-pixel-format.patch').read_text(encoding='utf-8')
        patched = '\n'.join(line[1:] for line in patch.splitlines()
                            if line.startswith((' ', '+')) and not line.startswith('+++'))
        setter = re.search(r'BOOL APIENTRY\nDrvSetPixelFormat\b.*?\n}', patched, re.S)
        self.assertIsNotNone(setter, 'patch must include the complete setter for regression testing')
        harness = r'''
#include <cassert>
#include <cstdio>
#include <cstddef>
using BOOL = bool;
using HDC = int;
using LONG = long;
using uint = unsigned int;
#define APIENTRY
#define _debug_printf(...) fprintf(stderr, __VA_ARGS__)
#define debug_printf(...) fprintf(stderr, __VA_ARGS__)
enum Owner { STW_FRAMEBUFFER_WGL_WINDOW, STW_FRAMEBUFFER_PBUFFER, STW_FRAMEBUFFER_EGL_WINDOW };
struct stw_pixelformat_info { int iPixelFormat; };
struct stw_framebuffer { Owner owner; const stw_pixelformat_info *pfi; };
struct Device { int fscreen; } device{7}, *stw_dev = &device;
static stw_pixelformat_info formats[] = {{1}, {2}, {3}};
static stw_framebuffer storage, *existing;
static int locks, creates, gdi_format;
static bool allocation_fails;
static uint stw_pixelformat_get_count(HDC) { return 3; }
static stw_framebuffer *stw_framebuffer_from_hdc_locked(HDC hdc) {
    assert(hdc == 42 && locks == 0);
    if (existing) ++locks;
    return existing;
}
static void stw_framebuffer_unlock(stw_framebuffer *fb) {
    assert(fb == existing && locks == 1);
    --locks;
}
static const stw_pixelformat_info *stw_pixelformat_get_info(int format) {
    assert(format >= 1 && format <= 3);
    return &formats[format - 1];
}
static int WindowFromDC(HDC hdc) { assert(hdc == 42); return 24; }
static stw_framebuffer *stw_framebuffer_create(int window, const stw_pixelformat_info *pfi,
                                             Owner owner, int screen) {
    assert(window == 24 && screen == 7 && locks == 0 && !existing);
    ++creates;
    if (allocation_fails) return nullptr;
    storage = {owner, pfi};
    existing = &storage;
    ++locks;
    return existing;
}
static int GetPixelFormat(HDC) { return gdi_format; }
static BOOL SetPixelFormat(HDC, LONG format, const void *) { gdi_format = format; return true; }
'''
        cases = r'''
static void check_existing(Owner owner, int current, LONG requested, bool expected) {
    storage = {owner, &formats[current - 1]};
    existing = &storage;
    creates = locks = 0;
    gdi_format = current;
    assert(DrvSetPixelFormat(42, requested) == expected);
    assert(creates == 0 && locks == 0 && gdi_format == current);
    assert(existing->owner == owner && existing->pfi->iPixelFormat == current);
}
int main() {
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 2, true);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 2, true);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 1, false);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 3, false);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 0, false);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, -1, false);
    check_existing(STW_FRAMEBUFFER_WGL_WINDOW, 2, 4, false);
    check_existing(STW_FRAMEBUFFER_PBUFFER, 2, 2, true);
    check_existing(STW_FRAMEBUFFER_PBUFFER, 2, 1, true);
    check_existing(STW_FRAMEBUFFER_EGL_WINDOW, 2, 2, false);
    check_existing(STW_FRAMEBUFFER_EGL_WINDOW, 2, 1, false);
    stw_dev = nullptr;
    assert(!DrvSetPixelFormat(42, 2));
    stw_dev = &device;
    existing = nullptr;
    creates = locks = gdi_format = 0;
    assert(DrvSetPixelFormat(42, 2));
    assert(creates == 1 && locks == 0 && gdi_format == 2);
    assert(existing->owner == STW_FRAMEBUFFER_WGL_WINDOW && existing->pfi == &formats[1]);
    assert(DrvSetPixelFormat(42, 2));
    assert(!DrvSetPixelFormat(42, 3));
    assert(creates == 1 && locks == 0 && existing->pfi == &formats[1]);
    existing = nullptr;
    allocation_fails = true;
    assert(!DrvSetPixelFormat(42, 1));
    assert(creates == 2 && locks == 0 && !existing);
}
'''
        run_harness(self, 'pixel_format', harness + setter.group() + cases)


if __name__ == '__main__':
    unittest.main()
