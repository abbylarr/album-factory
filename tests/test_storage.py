"""Originals stay off the public derivative paths; retention dates are calendar days."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from album_factory.storage import derivative, private_original, purge_photo_files, retention_deadline, warn_days


class StorageTests(unittest.TestCase):
    def test_original_is_private_and_purge_removes_all_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "photos").mkdir()
            photo_id = "p1"
            for path in (
                private_original(root, photo_id),
                derivative(root, photo_id, "jpg"),
                derivative(root, photo_id, "thumb"),
            ):
                path.write_bytes(b"x")
            self.assertEqual(private_original(root, photo_id).name, "p1.original")
            self.assertEqual(derivative(root, photo_id, "thumb").name, "p1.thumb.jpg")
            with self.assertRaises(ValueError):
                derivative(root, photo_id, "original")
            purge_photo_files(root, photo_id)
            self.assertEqual(list((root / "photos").iterdir()), [])

    def test_retention_warns_inside_fourteen_days(self):
        created = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(retention_deadline(created.isoformat()), "2026-04-01")
        now = datetime.now(timezone.utc)
        soon = warn_days((now - timedelta(days=80)).isoformat())
        later = warn_days((now - timedelta(days=70)).isoformat())
        self.assertTrue(soon["warn"])
        self.assertFalse(later["warn"])
        self.assertEqual(soon["delete_on"], retention_deadline((now - timedelta(days=80)).isoformat()))


if __name__ == "__main__":
    unittest.main()
