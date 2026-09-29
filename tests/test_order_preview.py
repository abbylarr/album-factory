import sqlite3
import unittest

from album_factory.server import order_preview_photos


class OrderPreviewTests(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.con.row_factory = sqlite3.Row
        self.con.execute("""CREATE TABLE photos (
            id TEXT, order_id TEXT, person_id TEXT, status TEXT, created_at TEXT
        )""")

    def tearDown(self):
        self.con.close()

    def add(self, photo_id, person, position):
        self.con.execute("INSERT INTO photos VALUES (?,?,?,?,?)",
                         (photo_id, "order-1", person, "ready", str(position)))

    def test_preserves_cover_and_chooses_other_people(self):
        self.add("a1", "a", 1)
        self.add("a2", "a", 2)
        self.add("b1", "b", 3)
        self.add("b2", "b", 4)
        self.add("c1", "c", 5)
        self.assertEqual(order_preview_photos(self.con, "order-1", "a2"),
                         ["a2", "b1", "c1"])

    def test_fills_remaining_slots_when_only_one_person_exists(self):
        self.add("a1", "a", 1)
        self.add("a2", "a", 2)
        self.add("a3", "a", 3)
        self.assertEqual(order_preview_photos(self.con, "order-1", None),
                         ["a1", "a2", "a3"])


if __name__ == "__main__":
    unittest.main()
