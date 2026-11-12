"""Régressions : protection des fichiers, lectures bornées et arrêt des fils de fond."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'jarvis'))
import config
import registry
import sandbox
import server
from hub import Hub
import myfiles


class ReleaseQuality(unittest.TestCase):
    def test_sandbox_fail_closed_and_authorized_roots(self):
        with patch.object(sandbox, 'available', return_value=False):
            with self.assertRaises(RuntimeError):
                sandbox.wrap(['true'], Path.home(), {}, True, False)
            self.assertEqual(sandbox.wrap(['true'], Path.home(), {'sandbox': False}, True, False), (['true'], False))
        cfg = {'workspace': '/tmp/work', 'project_dirs': ['/tmp/allowed']}
        self.assertTrue(sandbox.eligible_cwd(Path('/tmp/allowed/src'), cfg))
        self.assertFalse(sandbox.eligible_cwd(Path.home() / 'Documents/private', cfg))
        with patch.object(sandbox, 'available', return_value=True):
            argv, _ = sandbox.wrap(['true'], Path.home() / 'Documents/private', cfg, True, False)
            self.assertNotIn(str(Path.home() / 'Documents/private'), argv[2])

    def test_undo_conflict_recovery_and_reopen(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'BACKUP_DIR', Path(tmp) / 'backups'):
            f = Path(tmp) / 'document.txt'; f.write_text('original')
            backups = registry.Backups('task')
            registry.Ctx.backups = backups
            try:
                with registry.path_lock(f):
                    registry.backup(f); f.write_text('jarvis')
                f.write_text('user edit')
                self.assertIn('Conflit', registry.Backups.undo(backups.dir))
                self.assertEqual(f.read_text(), 'user edit')
                f.write_text('jarvis')
                registry.Ctx.backups = None
                reopened = registry.Backups('task')
                self.assertIn('restauré', registry.Backups.undo(reopened.dir))
                self.assertEqual(f.read_text(), 'original')
                self.assertEqual(next(reopened.dir.glob('recovery-*/*')).read_text(), 'jarvis')
                self.assertEqual(registry.Backups.undo(reopened.dir), 'Rien à annuler.')
                self.assertIsNone(registry.Backups.for_task('task'))
            finally:
                registry.Ctx.backups = None

    def test_new_file_recoverable_undo(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(config, 'BACKUP_DIR', Path(tmp) / 'backups'):
            f = Path(tmp) / 'created.txt'
            backups = registry.Backups('new')
            registry.Ctx.backups = backups
            try:
                with registry.path_lock(f):
                    registry.backup(f); f.write_text('created')
                registry.Backups.undo(backups.dir)
                self.assertFalse(f.exists())
                self.assertEqual(next(backups.dir.glob('recovery-*/*')).read_text(), 'created')
            finally:
                registry.Ctx.backups = None

    def test_legacy_backup_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); f = d / 'file'; f.write_text('new work')
            (d / 'old').write_text('old work')
            (d / 'manifest.json').write_text(json.dumps([{'path': str(f), 'backup': str(d / 'old')}]))
            self.assertIn('Conflit', registry.Backups.undo(d))
            self.assertEqual(f.read_text(), 'new work')

    def test_sniff_reads_only_bounded_prefix(self):
        class Limited(io.BytesIO):
            def read(self, size=-1):
                self_size = 20000
                if size < 0 or size > self_size:
                    raise AssertionError('unbounded read')
                return super().read(size)
        with patch.object(Path, 'open', return_value=Limited(b'plain text')):
            self.assertEqual(server.sniff_ext(Path('large')), '.txt')
        for content, extension in [(b'\x89PNG' + b'x'*100, '.png'), (b'\xff\xd8\xff', '.jpg'), (b'\x80', '')]:
            with patch.object(Path, 'open', return_value=Limited(content)):
                self.assertEqual(server.sniff_ext(Path('large')), extension)

    def test_power_watcher_and_index_watcher_stop(self):
        hub = Hub.__new__(Hub); hub.stopped = threading.Event(); hub.loop = None; hub.sessions = {}
        hub.power_thread = threading.Thread(target=hub._watch_power)
        hub.power_thread.start(); hub.stop()
        self.assertFalse(hub.power_thread.is_alive())
        stopped = threading.Event()
        thread = threading.Thread(target=myfiles.watch, args=(lambda: {}, stopped))
        thread.start(); stopped.set(); thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_closed_loop_broadcast(self):
        hub = Hub.__new__(Hub); hub.stopped = threading.Event(); hub.sessions = {'test': object()}
        hub.loop = asyncio.new_event_loop(); hub.loop.close()
        hub.broadcast({'type': 'test'})

if __name__ == '__main__':
    unittest.main()
