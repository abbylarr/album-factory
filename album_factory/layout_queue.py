"""Queued layout builds: the photographer asks for a layout while photos still upload or process.

The browser uploads the files, so it clears ``uploading`` when its own queue is empty; the
recognition worker calls ``run_ready`` whenever it drains. A failed build keeps its row with the
error so the order shows why the layout did not appear.
"""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, Field

from . import mvp


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS layout_queue (
      order_id TEXT PRIMARY KEY, master_template_id TEXT, uploading INTEGER NOT NULL DEFAULT 0,
      queued_at TEXT NOT NULL, error TEXT NOT NULL DEFAULT '')""")


def pending(con, order_id):
    """Photos of the shoots going into the layout that are not analysed yet."""
    return con.execute("""SELECT COUNT(*) FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id
        WHERE p.order_id=? AND p.status IN ('pending','processing') AND COALESCE(s.in_layout,1)=1""", (order_id,)).fetchone()[0]


def state(con, order_id):
    row = con.execute('SELECT * FROM layout_queue WHERE order_id=?', (order_id,)).fetchone()
    if row is None:
        return None
    return {'master_template_id': row['master_template_id'], 'uploading': bool(row['uploading']),
            'queued_at': row['queued_at'], 'error': row['error'], 'pending': pending(con, order_id)}


def run_ready(s, order_id=None):
    """Builds every queued layout whose photos are uploaded and analysed."""
    from .layout_workspace import build_layout
    with s.db() as con:
        ids = [r['order_id'] for r in con.execute(
            "SELECT order_id FROM layout_queue WHERE error='' AND uploading=0 AND (? IS NULL OR order_id=?)", (order_id, order_id))]
    built = []
    for key in ids:
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            row = con.execute("SELECT * FROM layout_queue WHERE order_id=? AND error='' AND uploading=0", (key,)).fetchone()
            if row is None or pending(con, key):
                continue
            # The recognition worker has no request: act as the studio that owns the order.
            owner = con.execute('SELECT studio_id FROM order_membership WHERE order_id=?', (key,)).fetchone()
            token = mvp.studio_ctx.set(owner['studio_id']) if owner else None
            try:
                build_layout(con, s, key, row['master_template_id'])
            except HTTPException as exc:
                con.execute('UPDATE layout_queue SET error=? WHERE order_id=?', (str(exc.detail), key))
                continue
            except Exception:
                s.log.exception('Queued layout failed: %s', key)
                con.execute('UPDATE layout_queue SET error=? WHERE order_id=?', ('Не удалось собрать макет. Попробуйте ещё раз.', key))
                continue
            finally:
                if token is not None:
                    mvp.studio_ctx.reset(token)
            con.execute('DELETE FROM layout_queue WHERE order_id=?', (key,))
            built.append(key)
    return built


class QueueInput(BaseModel):
    master_template_id: str | None = Field(default=None, max_length=200)
    uploading: bool = False


class QueueUploads(BaseModel):
    uploading: bool


def install(app, s):
    @app.post('/api/orders/{order_id}/layout/queue')
    def queue_layout(order_id: str, payload: QueueInput):
        with s.db() as con:
            order = dict(s.require_order(con, order_id))
            from .production import require_editable
            require_editable(con, order)
            con.execute("""INSERT INTO layout_queue (order_id,master_template_id,uploading,queued_at,error) VALUES (?,?,?,?,'')
                ON CONFLICT(order_id) DO UPDATE SET master_template_id=excluded.master_template_id,
                uploading=excluded.uploading, queued_at=excluded.queued_at, error=''""",
                        (order_id, payload.master_template_id, int(payload.uploading), s.now()))
        built = bool(run_ready(s, order_id))
        with s.db() as con:
            return {'built': built, 'queue': state(con, order_id)}

    @app.patch('/api/orders/{order_id}/layout/queue')
    def queue_uploads(order_id: str, payload: QueueUploads):
        with s.db() as con:
            s.require_order(con, order_id)
            con.execute('UPDATE layout_queue SET uploading=? WHERE order_id=?', (int(payload.uploading), order_id))
        built = bool(run_ready(s, order_id))
        with s.db() as con:
            return {'built': built, 'queue': state(con, order_id)}

    @app.delete('/api/orders/{order_id}/layout/queue')
    def cancel_queue(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            con.execute('DELETE FROM layout_queue WHERE order_id=?', (order_id,))
        return {'ok': True}
