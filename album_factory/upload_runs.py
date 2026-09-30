"""Browser uploads the order can see: how many files a run promised and how many reached the server.

The browser sends the files one by one, so a closed tab or a lost connection leaves the run short.
The row outlives the tab; the order shows it as interrupted once no file has arrived for a while,
and the photographer picks the files again (duplicates are skipped by the upload itself).
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

STALL_SECONDS = 90


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS upload_runs (
      order_id TEXT PRIMARY KEY, shoot_id TEXT NOT NULL, total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
      started_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")


def _now():
    return datetime.now(timezone.utc).isoformat()


def arrived(con, order_id):
    """One file of the running upload reached the server (a new photo or a skipped duplicate)."""
    con.execute('UPDATE upload_runs SET done=MIN(total,done+1), updated_at=? WHERE order_id=?', (_now(), order_id))


def _view(row):
    quiet = (datetime.now(timezone.utc) - datetime.fromisoformat(row['updated_at'])).total_seconds()
    return {'shoot_id': row['shoot_id'], 'total': row['total'], 'done': row['done'], 'stalled': quiet > STALL_SECONDS}


def state(con, order_id):
    row = con.execute('SELECT * FROM upload_runs WHERE order_id=?', (order_id,)).fetchone()
    return _view(row) if row else None


def by_order(con):
    return {r['order_id']: _view(r) for r in con.execute('SELECT * FROM upload_runs')}


def forget(con, order_id):
    con.execute('DELETE FROM upload_runs WHERE order_id=?', (order_id,))


class RunInput(BaseModel):
    shoot_id: str = Field(min_length=1, max_length=100)
    files: int = Field(ge=1, le=10000)


def install(app, s):
    @app.post('/api/orders/{order_id}/uploads')
    def start_run(order_id: str, payload: RunInput):
        """A new batch of files: adds to a run that is still going, otherwise starts afresh
        (picking the files again after an interruption begins a new count)."""
        with s.db() as con:
            s.require_order(con, order_id)
            now, run = _now(), state(con, order_id)
            if run and not run['stalled'] and run['done'] < run['total']:
                con.execute('UPDATE upload_runs SET total=total+?, shoot_id=?, updated_at=? WHERE order_id=?',
                            (payload.files, payload.shoot_id, now, order_id))
            else:
                con.execute("""INSERT INTO upload_runs (order_id,shoot_id,total,done,started_at,updated_at) VALUES (?,?,?,0,?,?)
                    ON CONFLICT(order_id) DO UPDATE SET shoot_id=excluded.shoot_id, total=excluded.total, done=0,
                    started_at=excluded.started_at, updated_at=excluded.updated_at""",
                            (order_id, payload.shoot_id, payload.files, now, now))
            return state(con, order_id)

    @app.delete('/api/orders/{order_id}/uploads')
    def finish_run(order_id: str):
        """The browser went through its whole queue, or the photographer dismissed an interrupted run."""
        with s.db() as con:
            s.require_order(con, order_id)
            forget(con, order_id)
        return {'ok': True}
