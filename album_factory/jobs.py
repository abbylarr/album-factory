"""Durable single-worker jobs. One idempotency key is one row, retried in place."""
import json
import sqlite3
import uuid

_COLUMNS = (
    "id", "idempotency_key", "kind", "payload", "status",
    "attempts", "error", "result", "created_at", "finished_at",
)


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        idempotency_key TEXT UNIQUE NOT NULL,
        kind TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        finished_at TEXT NOT NULL DEFAULT ''
    )""")
    con.commit()


def _job(row):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return {name: row[name] for name in _COLUMNS}
    return dict(zip(_COLUMNS, row))


def _fetch(con, job_id):
    return _job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def enqueue(con, kind, payload: dict, key: str, now):
    con.execute(
        """INSERT INTO jobs
           (id, idempotency_key, kind, payload, status, created_at)
           VALUES (?,?,?,?, 'pending', ?)
           ON CONFLICT(idempotency_key) DO NOTHING""",
        (uuid.uuid4().hex, key, kind, json.dumps(payload, ensure_ascii=False), now),
    )
    con.commit()
    return _job(con.execute("SELECT * FROM jobs WHERE idempotency_key=?", (key,)).fetchone())


def claim_pending(con, now):
    del now  # reserved so a worker can stamp the claim without a schema change
    row = con.execute(
        "SELECT id FROM jobs WHERE status='pending' ORDER BY created_at, id LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    job_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
    updated = con.execute(
        "UPDATE jobs SET status='running' WHERE id=? AND status='pending'",
        (job_id,),
    )
    con.commit()
    if updated.rowcount != 1:
        return None
    return _fetch(con, job_id)


def complete(con, job_id, result_dict, now):
    con.execute(
        "UPDATE jobs SET status='completed', result=?, error='', finished_at=? WHERE id=?",
        (json.dumps(result_dict, ensure_ascii=False), now, job_id),
    )
    con.commit()
    return _fetch(con, job_id)


def fail(con, job_id, error, now):
    row = con.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    attempts = (row["attempts"] if isinstance(row, sqlite3.Row) else row[0]) + 1
    if attempts < 3:
        con.execute(
            "UPDATE jobs SET status='pending', attempts=?, error=?, finished_at='' WHERE id=?",
            (attempts, error, job_id),
        )
    else:
        con.execute(
            "UPDATE jobs SET status='error', attempts=?, error=?, finished_at=? WHERE id=?",
            (attempts, error, now, job_id),
        )
    con.commit()
    return _fetch(con, job_id)


def run_once(con, handlers: dict, now):
    job = claim_pending(con, now)
    if job is None:
        return None
    try:
        result = handlers[job["kind"]](json.loads(job["payload"]))
        if result is None:
            result = {}
        if not isinstance(result, dict):
            raise TypeError("Обработчик задачи должен вернуть словарь")
        return complete(con, job["id"], result, now)
    except Exception as exc:
        return fail(con, job["id"], str(exc), now)
