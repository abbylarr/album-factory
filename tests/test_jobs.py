"""Idempotent job queue on a temporary SQLite connection, without the web app."""
import json
import sqlite3
import unittest

from album_factory import jobs


def connect():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    jobs.init(con)
    return con


class JobTests(unittest.TestCase):
    def test_duplicate_enqueue_and_crash_retry_do_not_double_apply(self):
        con = connect()
        applied = []
        crashed = {"done": False}

        def derive(payload):
            if not crashed["done"]:
                crashed["done"] = True
                raise RuntimeError("crash before apply")
            if payload["photo"] in applied:
                raise AssertionError("double apply")
            applied.append(payload["photo"])
            return {"photo": payload["photo"]}

        now = "2026-09-25T00:00:00+00:00"
        first = jobs.enqueue(con, "derive", {"photo": "p1"}, "derive:p1", now)
        second = jobs.enqueue(con, "derive", {"photo": "other"}, "derive:p1", now)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(json.loads(second["payload"]), {"photo": "p1"})
        self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

        crashed_job = jobs.run_once(con, {"derive": derive}, now)
        self.assertEqual(applied, [])
        self.assertEqual(crashed_job["status"], "pending")
        self.assertEqual(crashed_job["attempts"], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

        done = jobs.run_once(con, {"derive": derive}, now)
        self.assertEqual(applied, ["p1"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(json.loads(done["result"]), {"photo": "p1"})

        self.assertIsNone(jobs.run_once(con, {"derive": derive}, now))
        self.assertEqual(applied, ["p1"])
        self.assertEqual(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_three_failures_stop_and_are_not_run_again(self):
        con = connect()
        calls = []

        def boom(payload):
            calls.append(payload["n"])
            raise RuntimeError("nope")

        jobs.enqueue(con, "boom", {"n": 1}, "boom:1", "t")
        for _ in range(3):
            jobs.run_once(con, {"boom": boom}, "t")
        row = con.execute("SELECT status, attempts FROM jobs").fetchone()
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(calls, [1, 1, 1])
        self.assertIsNone(jobs.run_once(con, {"boom": boom}, "t"))
        self.assertEqual(calls, [1, 1, 1])


if __name__ == "__main__":
    unittest.main()
