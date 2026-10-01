"""Photographer notifications: what happened on the class's side, or finished in the background, while nobody watched.

One row per event. A repeated event of the same kind on the same order joins the unread row instead of piling up
(three corrections sent one after another read as «Правки от класса: 3»). Rows go away with their order.
"""
from datetime import datetime, timedelta, timezone
import uuid

from fastapi import HTTPException

KINDS = ('forms_complete', 'approved', 'corrections', 'photos_ready', 'teacher_proposals')
KEEP_DAYS = 30
LIMIT = 50


def _now():
    return datetime.now(timezone.utc).isoformat()


def init(con):
    con.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, read_at TEXT)''')
    con.execute('CREATE INDEX IF NOT EXISTS notifications_order_kind ON notifications(order_id, kind, read_at)')
    con.execute('DELETE FROM notifications WHERE created_at<?',
                ((datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(),))


def emit(con, order_id, kind, count=1):
    assert kind in KINDS, kind
    unread = con.execute('SELECT id FROM notifications WHERE order_id=? AND kind=? AND read_at IS NULL',
                         (order_id, kind)).fetchone()
    if unread:
        con.execute('UPDATE notifications SET count=count+?, created_at=? WHERE id=?', (count, _now(), unread['id']))
    else:
        con.execute('INSERT INTO notifications (id,order_id,kind,count,created_at) VALUES (?,?,?,?,?)',
                    (uuid.uuid4().hex, order_id, kind, count, _now()))


def retract(con, order_id, kind):
    """The class took one back (a withdrawn correction) before the photographer saw it."""
    con.execute('UPDATE notifications SET count=count-1 WHERE order_id=? AND kind=? AND read_at IS NULL', (order_id, kind))
    con.execute('DELETE FROM notifications WHERE order_id=? AND kind=? AND read_at IS NULL AND count<1', (order_id, kind))


def forms_check(con, order_id):
    """«Все заполнили» once per order: the moment the last form of the class is in."""
    from .client_portal import progress_by_order
    if progress_by_order(con, order_id)[order_id]['status'] != 'complete':
        return
    if con.execute("SELECT 1 FROM notifications WHERE order_id=? AND kind='forms_complete'", (order_id,)).fetchone() is None:
        emit(con, order_id, 'forms_complete')


def photos_check(con, order_id):
    """Background processing of an upload has finished for the whole order."""
    busy = con.execute("SELECT 1 FROM photos WHERE order_id=? AND status IN ('pending','processing') LIMIT 1", (order_id,)).fetchone()
    if busy is None:
        emit(con, order_id, 'photos_ready')


def install(app, s):
    def scope():
        from . import mvp
        studio = mvp.studio_ctx.get()
        if studio is None:
            return '', ()
        return 'AND EXISTS (SELECT 1 FROM order_membership m WHERE m.order_id=n.order_id AND m.studio_id=?)', (studio,)

    @app.get('/api/notifications')
    def list_notifications():
        where, args = scope()
        with s.db() as con:
            rows = con.execute(f'''SELECT n.id, n.order_id, n.kind, n.count, n.created_at, n.read_at IS NOT NULL AS read,
                o.school, o.class_name, o.stage,
                (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status NOT IN ('pending','processing')
                   AND NOT EXISTS (SELECT 1 FROM shoots sh WHERE sh.id=p.shoot_id AND sh.kind='general')
                   AND (p.status!='ready' OR p.uncertain=1 OR p.person_id IS NULL)) AS review_count
                FROM notifications n JOIN orders o ON o.id=n.order_id WHERE 1=1 {where}
                ORDER BY n.created_at DESC LIMIT ?''', (*args, LIMIT)).fetchall()
            unread = con.execute(f'SELECT COUNT(*) FROM notifications n WHERE read_at IS NULL {where}', args).fetchone()[0]
        return {'items': [dict(r, read=bool(r['read'])) for r in rows], 'unread': unread}

    @app.post('/api/notifications/read')
    def read_all():
        where, args = scope()
        with s.db() as con:
            con.execute(f'UPDATE notifications SET read_at=? WHERE read_at IS NULL {where.replace("n.order_id", "notifications.order_id")}',
                        (_now(), *args))
        return {'ok': True}

    @app.post('/api/notifications/{notification_id}/read')
    def read_one(notification_id: str):
        where, args = scope()
        with s.db() as con:
            changed = con.execute(f'UPDATE notifications SET read_at=COALESCE(read_at,?) WHERE id=? {where.replace("n.order_id", "notifications.order_id")}',
                                  (_now(), notification_id, *args)).rowcount
        if not changed:
            raise HTTPException(404, 'Уведомление не найдено')
        return {'ok': True}
