import stat
import unittest

from hidrive_hidden_items_v1916 import (
    decorate_text,
    decorate_values,
    hidden_info,
    list_remote_all,
)


class Attr:
    def __init__(self, filename, mode, size=0, mtime=0, extra=None, file_attributes=None):
        self.filename = filename
        self.st_mode = mode
        self.st_size = size
        self.st_mtime = mtime
        self.attr = extra or {}
        if file_attributes is not None:
            self.file_attributes = file_attributes


class FakeSftp:
    def __init__(self, rows):
        self.rows = list(rows)

    def listdir_attr(self, _path):
        return list(self.rows)


class HiddenHiDriveTests(unittest.TestCase):
    def test_dot_folder_is_hidden(self):
        hidden, reason = hidden_info(Attr('.cache', stat.S_IFDIR | 0o755), '.cache')
        self.assertTrue(hidden)
        self.assertIn('Punktname', reason)

    def test_normal_folder_is_not_hidden(self):
        hidden, reason = hidden_info(Attr('Fotos', stat.S_IFDIR | 0o755), 'Fotos')
        self.assertFalse(hidden)
        self.assertEqual('', reason)

    def test_dos_hidden_bit_is_honoured_when_server_exposes_it(self):
        hidden, reason = hidden_info(
            Attr('Archiv', stat.S_IFDIR | 0o755, file_attributes=0x02),
            'Archiv',
        )
        self.assertTrue(hidden)
        self.assertIn('Attribut', reason)

    def test_list_remote_keeps_hidden_and_visible_entries(self):
        sftp = FakeSftp([
            Attr('.ssh', stat.S_IFDIR | 0o700),
            Attr('Dokumente', stat.S_IFDIR | 0o755),
            Attr('.hinweis', stat.S_IFREG | 0o644, size=12),
        ])
        rows = list_remote_all(sftp, '/users/test')
        self.assertEqual(['.ssh', 'Dokumente', '.hinweis'], [r['name'] for r in rows])
        self.assertTrue(rows[0]['hidden'])
        self.assertFalse(rows[1]['hidden'])
        self.assertTrue(rows[2]['hidden'])

    def test_hidden_tree_label_keeps_arrow_and_adds_badge(self):
        row = {'name': '.ssh', 'hidden': True, 'is_dir': True}
        text = decorate_text('▶ 📁 .ssh', row)
        self.assertTrue(text.startswith('▶ '))
        self.assertIn('[VERSTECKT]', text)
        self.assertIn('.ssh', text)

    def test_protected_vault_is_marked_hidden_and_protected(self):
        row = {'name': '.pc-backup-vault', 'hidden': True, 'is_dir': True}
        text = decorate_text('▼ 📂 .pc-backup-vault', row)
        values = decorate_values(('Ordner', '–', '09.09.2026', '/users/u/.pc-backup-vault'), row)
        self.assertIn('VERSTECKT · GESCHÜTZT', text)
        self.assertEqual('Geschützt · versteckter Ordner', values[0])


if __name__ == '__main__':
    unittest.main()
