"""Resumable upload sessions. Chunks are files and SQLite rows, not HTTP."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from album_factory import uploads


class UploadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row

    def test_two_chunks_resume_reject_bad_offset_and_checksum(self):
        payload = bytes((i * 3) % 256 for i in range(300))
        digest = hashlib.sha256(payload).hexdigest()
        first = uploads.start(self.con, "u1", "order", "shoot", "DSC0300.jpg", len(payload), digest, "t1")
        self.assertEqual(first["received"], 0)
        uploads.write_chunk(self.con, self.data, "u1", 0, payload[:120])

        resumed = uploads.start(self.con, "u1", "order", "shoot", "DSC0300.jpg", len(payload), digest, "t2")
        self.assertEqual(resumed["received"], 120)
        self.assertTrue(str(uploads.partial_path(self.data, "u1")).endswith("u1.partial"))

        with self.assertRaises(ValueError):
            uploads.write_chunk(self.con, self.data, "u1", 0, payload[:120])
        self.assertEqual(self.con.execute("SELECT received FROM upload_parts WHERE id='u1'").fetchone()["received"], 120)

        uploads.write_chunk(self.con, self.data, "u1", resumed["received"], payload[120:])
        self.assertEqual(uploads.finish(self.con, self.data, "u1"), payload)

        uploads.start(self.con, "bad", "order", "shoot", "x.jpg", 4, "0" * 64, "t3")
        uploads.write_chunk(self.con, self.data, "bad", 0, b"abcd")
        with self.assertRaises(ValueError):
            uploads.finish(self.con, self.data, "bad")


if __name__ == "__main__":
    unittest.main()
