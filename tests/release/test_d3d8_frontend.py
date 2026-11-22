# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md
"""Guard the D3D8 package against the unusable WineD3D/OpenGL route."""
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('d3d8_build', ROOT / 'build/d3d8to9/build.py')
d3d8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d3d8)


class D3D8FrontendChecks(unittest.TestCase):
    def test_bad_download_never_becomes_a_build_input(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(d3d8.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong source')):
            with self.assertRaisesRegex(ValueError, 'source checksum mismatch'):
                d3d8.fetch(Path(tmp))
            self.assertFalse((Path(tmp) / d3d8.SOURCE).exists())

    def test_cached_source_is_rehashed_before_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / d3d8.SOURCE
            archive.write_bytes(b'changed cache')
            data = b'verified source fixture'
            with mock.patch.object(d3d8, 'SHA256', hashlib.sha256(data).hexdigest()), \
                    mock.patch.object(d3d8.urllib.request, 'urlopen', return_value=io.BytesIO(data)):
                self.assertEqual(d3d8.fetch(Path(tmp)).read_bytes(), data)

    def test_binary_guard_rejects_gl_frontend_wrong_arch_and_dynamic_cpp_runtime(self):
        data = bytearray(128)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 0x3c, 64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<H', data, 68, 0x14c)
        exports = '\n'.join(('Direct3DCreate8', 'DebugSetMute', 'ValidatePixelShader',
                              'ValidateVertexShader', 'D3D8GetSWInfo'))
        with tempfile.TemporaryDirectory() as tmp:
            dll = Path(tmp) / 'd3d8.dll'
            dll.write_bytes(data)
            for extra in ('wined3d.dll', 'opengl32.dll', 'libc++.dll', 'libwinpthread-1.dll'):
                with self.subTest(import_name=extra), mock.patch.object(
                        d3d8.subprocess, 'check_output',
                        return_value='DLL Name: d3d9.dll\nDLL Name: ' + extra + '\n' + exports):
                    with self.assertRaises(ValueError):
                        d3d8.check_dll(dll, 'objdump')
            with mock.patch.object(d3d8.subprocess, 'check_output',
                                   return_value='DLL Name: d3d9.dll\n' + exports):
                self.assertEqual(d3d8.check_dll(dll, 'objdump'), ['d3d9.dll'])
                struct.pack_into('<H', data, 68, 0x8664)
                dll.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'wrong PE machine'):
                    d3d8.check_dll(dll, 'objdump')

    def test_frontend_is_staged_after_farm_cache_restore_and_before_recording(self):
        workflow = (ROOT / '.github/workflows/build-ipa.yml').read_text(encoding='utf-8')
        step = workflow.split('      - name: Build shared D3D8 to D3D9 frontend\n')[1]
        step = step.split('      - name:', 1)[0]
        self.assertNotIn('if:', step)
        self.assertIn('python3 -B build/d3d8to9/build.py', step)
        self.assertLess(workflow.index('name: Save Windows runtime'),
                        workflow.index('name: Build shared D3D8 to D3D9 frontend'))
        self.assertLess(workflow.index('name: Build shared D3D8 to D3D9 frontend'),
                        workflow.index('name: Verify and record synchronized runtime inputs'))
        self.assertIn('--d3d8to9-sources build/d3d8to9/work/sources', workflow)


if __name__ == '__main__':
    unittest.main()
