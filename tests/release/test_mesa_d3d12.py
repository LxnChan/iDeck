# SPDX-License-Identifier: GPL-3.0-or-later
# Madeira Converter Exception: see LICENSE-EXCEPTION.md.
"""Exercise the downloaded-source boundary without a GPU or network access."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mesa_build', ROOT / 'build/mesa-d3d12/build.py')
mesa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mesa)


class MesaSourceChecks(unittest.TestCase):
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
                'sources': {name: values[1] for name, values in mesa.SOURCES.items()}}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'pinned checksum'):
                mesa.verify(dist)


if __name__ == '__main__':
    unittest.main()
