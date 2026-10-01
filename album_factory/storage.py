"""Photo files on the local data directory and how long they are kept.

Every photo is one full-size upright JPEG ``photos/{id}.jpg`` plus a small
``photos/{id}.thumb.jpg``. Once a student has a chosen portrait, the other
frames of that student keep only the thumbnail.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


def shrink_unchosen(con, person_id) -> list:
    """Ids of the student's other portrait frames whose full-size file may go.

    Frames still placed in the saved or published layout are kept until the
    layout stops using them.
    """
    from .mvp import publication_photo_ids
    chosen = con.execute('SELECT photo_id FROM client_selections WHERE person_id=?', (person_id,)).fetchone()
    if chosen is None:
        return []
    rows = con.execute('''SELECT f.id, f.order_id FROM photos f LEFT JOIN shoots s ON s.id=f.shoot_id
        WHERE f.person_id=? AND f.id!=? AND COALESCE(s.kind,'portrait')='portrait' ''', (person_id, chosen['photo_id'])).fetchall()
    if not rows:
        return []
    placed = set()
    for table in ('order_layouts', 'publications'):
        for doc in con.execute(f'SELECT document FROM {table} WHERE order_id=?', (rows[0]['order_id'],)):
            placed |= publication_photo_ids(json.loads(doc['document']))
    return [r['id'] for r in rows if r['id'] not in placed]


def drop_full_files(data_dir, photo_ids) -> None:
    for photo_id in photo_ids:
        (Path(data_dir) / 'photos' / f'{photo_id}.jpg').unlink(missing_ok=True)


def _created(created_iso):
    moment = datetime.fromisoformat(created_iso)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def retention_deadline(created_iso, days=90) -> str:
    return (_created(created_iso) + timedelta(days=days)).date().isoformat()


def warn_days(created_iso):
    delete_on = retention_deadline(created_iso)
    remaining = (datetime.fromisoformat(delete_on).date() - datetime.now(timezone.utc).date()).days
    return {"delete_on": delete_on, "warn": remaining <= 14}
