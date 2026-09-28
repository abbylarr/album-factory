"""General shoots: analysis queue, identities from portraits, review API and layout snapshot.

Persons come only from portraits. Faces on general photos are linked to them
automatically or by the photographer; manual decisions survive re-analysis and
identity refreshes. Metadata rules live in ``general_meta``.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal

from . import general_meta as gm
from .vision import TAGS, unpack

SCALE_LABELS = {'detail': 'Детали', 'close': 'Крупный', 'medium': 'Средний', 'full': 'В рост', 'wide': 'Общий'}
BUCKET_LABELS = {'none': 'Без людей', 'solo': 'Один', 'pair': 'Пара', 'small_group': 'Небольшая группа', 'group': 'Группа', 'class': 'Весь класс'}
DEFECT_LABELS = {'blur': 'Нерезко', 'eyes_closed': 'Закрыты глаза', 'exposure': 'Экспозиция', 'face_cut': 'Лицо у края'}


def init(con):
    con.executescript('''
      CREATE TABLE IF NOT EXISTS photo_meta (
        photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
        version TEXT NOT NULL, raw TEXT NOT NULL, meta TEXT, clip TEXT, thumb TEXT, taken_at TEXT,
        analyzed_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS photo_faces (
        id TEXT PRIMARY KEY, photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL, embedding TEXT, px REAL NOT NULL, doubtful INTEGER NOT NULL DEFAULT 0,
        subject TEXT, source TEXT NOT NULL DEFAULT 'auto', score REAL, level TEXT, cluster INTEGER);
      CREATE INDEX IF NOT EXISTS photo_faces_photo ON photo_faces(photo_id);
      CREATE TABLE IF NOT EXISTS photo_flags (
        photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
        excluded INTEGER NOT NULL DEFAULT 0, must_use INTEGER NOT NULL DEFAULT 0,
        hero INTEGER NOT NULL DEFAULT 0, best INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS general_state (order_id TEXT PRIMARY KEY, gallery TEXT NOT NULL);
    ''')
    # General photos uploaded before the analysis existed are queued once.
    con.execute('''UPDATE photos SET status='pending' WHERE status='ready' AND id NOT IN (SELECT photo_id FROM photo_meta)
        AND shoot_id IN (SELECT id FROM shoots WHERE kind='general')''')


# --- analysis ------------------------------------------------------------------

def process_batch(server, rows, vision):
    """Analyse queued general photos of one shoot, then refresh the order."""
    for row in rows:
        try:
            with server.db() as con:
                current = con.execute('SELECT status FROM photos WHERE id=?', (row['id'],)).fetchone()
                if current is None or current['status'] != 'processing':
                    continue
            raw = vision.analyze(row['path'], row.get('original'))
            with server.db() as con:
                con.execute('BEGIN IMMEDIATE')
                if (con.execute('SELECT status FROM photos WHERE id=?', (row['id'],)).fetchone() or {'status': None})['status'] != 'processing':
                    continue
                store(con, row['id'], raw, server.now())
                con.execute("UPDATE photos SET status='ready',uncertain=0,error='' WHERE id=?", (row['id'],))
        except Exception:
            server.log.exception('General analysis failed: %s', row['id'])
            with server.db() as con:
                con.execute("UPDATE photos SET status='error',error=? WHERE id=? AND status='processing'",
                            ('Не удалось проанализировать снимок. Повторите обработку.', row['id']))
    if rows:
        with server.db() as con:
            refresh(con, rows[0]['order_id'], force=True)


def store(con, photo_id, raw, now):
    """Save raw detections; manual face decisions follow the face with the same place."""
    old = {r['idx']: dict(r) for r in con.execute("SELECT * FROM photo_faces WHERE photo_id=? AND source!='auto'", (photo_id,))}
    previous = con.execute('SELECT raw FROM photo_meta WHERE photo_id=?', (photo_id,)).fetchone()
    old_boxes = {i: f['box'] for i, f in enumerate(json.loads(previous['raw'])['faces'])} if previous else {}
    clip = raw.get('clip') or {}
    con.execute('INSERT OR REPLACE INTO photo_meta (photo_id,version,raw,meta,clip,thumb,taken_at,analyzed_at) VALUES (?,?,?,?,?,?,?,?)',
                (photo_id, gm.CONFIG['version'], json.dumps(raw), None, clip.get('embedding'), raw.get('thumb'), raw.get('taken_at'), now))
    con.execute('DELETE FROM photo_faces WHERE photo_id=?', (photo_id,))
    for index, face in enumerate(raw.get('faces', [])):
        manual = next((m for i, m in old.items() if i in old_boxes and _iou(old_boxes[i], face['box']) > .5), None)
        con.execute('INSERT INTO photo_faces (id,photo_id,idx,embedding,px,doubtful,subject,source) VALUES (?,?,?,?,?,?,?,?)',
                    (f'{photo_id}-{index}', photo_id, index, face.get('embedding'), face.get('px', 0), int(bool(face.get('doubtful'))),
                     manual['subject'] if manual else None, manual['source'] if manual else 'auto'))


def _iou(a, b):
    inter = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    total = a[2] * a[3] + b[2] * b[3] - inter
    return inter / total if total else 0


def gallery(con, order_id):
    samples = {}
    for row in con.execute('''SELECT p.person_id,p.embedding FROM photos p JOIN shoots s ON s.id=p.shoot_id
            WHERE p.order_id=? AND s.kind='portrait' AND p.person_id IS NOT NULL AND p.embedding IS NOT NULL
            ORDER BY p.person_id,p.id''', (order_id,)):
        samples.setdefault(row['person_id'], []).append(json.loads(row['embedding']))
    return {k: np.array(v, dtype=np.float32) for k, v in samples.items()}


def _signature(con, order_id):
    rows = con.execute('''SELECT p.id,p.person_id FROM photos p JOIN shoots s ON s.id=p.shoot_id
        WHERE p.order_id=? AND s.kind='portrait' AND p.embedding IS NOT NULL ORDER BY p.id''', (order_id,)).fetchall()
    return hashlib.sha256((gm.CONFIG['version'] + ''.join(f'{r[0]}:{r[1]};' for r in rows)).encode()).hexdigest()


def refresh(con, order_id, force=False, only=None):
    """Re-link faces to the current portrait persons and rebuild derived metadata when anything changed.

    ``only`` limits matching and metadata to the given photos (a manual face
    decision); unknown faces are always re-clustered across the order.
    """
    signature = _signature(con, order_id)
    state = con.execute('SELECT gallery FROM general_state WHERE order_id=?', (order_id,)).fetchone()
    stale = con.execute('''SELECT 1 FROM photo_meta m JOIN photos p ON p.id=m.photo_id WHERE p.order_id=? AND (m.meta IS NULL OR m.version!=?) LIMIT 1''',
                        (order_id, gm.CONFIG['version'])).fetchone()
    if only is None and not force and state and state['gallery'] == signature and not stale:
        return False
    if only is not None and (not state or state['gallery'] != signature or stale):
        only = None  # the whole order is out of date anyway
    samples = gallery(con, order_id)
    persons = {r['id'] for r in con.execute('SELECT id FROM persons WHERE order_id=?', (order_id,))}
    faces = {}
    for row in con.execute('''SELECT f.* FROM photo_faces f JOIN photos p ON p.id=f.photo_id WHERE p.order_id=? ORDER BY f.photo_id,f.idx''', (order_id,)):
        if only is None or row['photo_id'] in only:
            faces.setdefault(row['photo_id'], []).append(dict(row))
    minimum = gm.CONFIG['identify_min_px']
    for photo_id, rows in faces.items():
        manual = {r['subject'] for r in rows if r['source'] == 'manual' and r['subject']}
        for r in rows:
            if r['source'] == 'manual' and r['subject'] not in persons:
                r['source'], r['subject'] = 'auto', None  # the person was merged or deleted
        pool = {k: v for k, v in samples.items() if k not in manual}
        vectors = [unpack(r['embedding']) if r['source'] == 'auto' and not r['doubtful'] and r['px'] >= minimum and r['embedding'] else None for r in rows]
        for r, (subject, score, level) in zip(rows, gm.match_faces(vectors, pool)):
            if r['source'] != 'auto':
                continue
            # Uncertain links keep their candidate in ``subject`` for review; layout uses level ``auto`` only.
            r['subject'], r['score'], r['level'] = subject, score, level
            con.execute('UPDATE photo_faces SET subject=?,score=?,level=?,source=? WHERE id=?', (subject, score, level, 'auto', r['id']))
    unknown = [(r['id'], unpack(r['embedding']), r['photo_id']) for r in con.execute('''SELECT f.id,f.embedding,f.photo_id FROM photo_faces f
        JOIN photos p ON p.id=f.photo_id WHERE p.order_id=? AND f.source='auto' AND (f.level IS NULL OR f.level!='auto')
        AND f.doubtful=0 AND f.px>=? AND f.embedding IS NOT NULL ORDER BY f.photo_id,f.idx''', (order_id, minimum))]
    labels = gm.cluster(unknown)
    con.execute('UPDATE photo_faces SET cluster=NULL WHERE photo_id IN (SELECT id FROM photos WHERE order_id=?)', (order_id,))
    con.executemany('UPDATE photo_faces SET cluster=? WHERE id=?', [(n, k) for k, n in labels.items()])
    class_size = len(persons)
    for photo_id, raw_text, old in con.execute('''SELECT m.photo_id,m.raw,m.meta FROM photo_meta m JOIN photos p ON p.id=m.photo_id WHERE p.order_id=?''', (order_id,)).fetchall():
        if only is not None and photo_id not in only:
            continue
        rows = faces.get(photo_id, [])
        subjects = {r['idx']: r['subject'] for r in rows if r['subject'] and (r['source'] == 'manual' or r['source'] == 'auto' and r['level'] == 'auto')}
        raw = json.loads(raw_text)
        for r in rows:
            if r['source'] == 'not_face' and r['idx'] < len(raw['faces']):
                raw['faces'][r['idx']]['ignored'] = True
        meta = gm.derive(raw, subjects, class_size)
        previous = json.loads(old) if old else {}
        meta.update({k: previous.get(k) for k in ('series', 'event', 'sequence')})
        con.execute('UPDATE photo_meta SET meta=?,version=? WHERE photo_id=?', (json.dumps(meta), gm.CONFIG['version'], photo_id))
    if only is None:
        for shoot in con.execute("SELECT id FROM shoots WHERE order_id=? AND kind='general'", (order_id,)).fetchall():
            shoot_pass(con, shoot['id'])
        con.execute('INSERT OR REPLACE INTO general_state VALUES (?,?)', (order_id, signature))
    return True


def shoot_pass(con, shoot_id):
    """Series of near-identical frames and time events across one general shoot."""
    rows = con.execute('''SELECT p.id,p.filename,p.created_at,m.clip,m.thumb,m.taken_at,m.meta FROM photos p JOIN photo_meta m ON m.photo_id=p.id
        WHERE p.shoot_id=? AND p.status='ready' ''', (shoot_id,)).fetchall()
    from .sorting_v3 import ordered
    order = {r['id']: i for i, r in enumerate(ordered([dict(r) for r in rows]))}
    photos = [{'id': r['id'], 'order': order[r['id']], 'taken_at': r['taken_at'], 'clip': unpack(r['clip']),
               'thumb': unpack(r['thumb'])} for r in rows]
    groups = gm.series(photos)
    moments = gm.events(photos)
    for r in rows:
        meta = json.loads(r['meta']) if r['meta'] else None
        if meta is None:
            continue
        meta['series'] = groups.get(r['id'])
        meta['event'] = moments.get(r['id'])
        meta['sequence'] = order[r['id']]
        con.execute('UPDATE photo_meta SET meta=? WHERE photo_id=?', (json.dumps(meta), r['id']))


# --- read models ---------------------------------------------------------------

def _photos(con, order_id, shoot_id=None):
    rows = con.execute('''SELECT p.id,p.filename,p.status,p.shoot_id,p.error,m.meta,
            COALESCE(f.excluded,0) AS excluded,COALESCE(f.must_use,0) AS must_use,COALESCE(f.hero,0) AS hero,COALESCE(f.best,0) AS best
        FROM photos p JOIN shoots s ON s.id=p.shoot_id LEFT JOIN photo_meta m ON m.photo_id=p.id LEFT JOIN photo_flags f ON f.photo_id=p.id
        WHERE p.order_id=? AND s.kind='general' AND (? IS NULL OR p.shoot_id=?) ORDER BY p.created_at,p.id''', (order_id, shoot_id, shoot_id)).fetchall()
    photos = []
    for r in rows:
        item = dict(r)
        item['meta'] = json.loads(r['meta']) if r['meta'] else None
        photos.append(item)
    _mark_best(photos)
    return photos


def _mark_best(photos):
    """Best frame per series: the photographer's choice, else the highest usable score."""
    series = {}
    for p in photos:
        key = (p['meta'] or {}).get('series')
        p['alternate'] = False
        if key:
            series.setdefault(key, []).append(p)
    for items in series.values():
        chosen = next((p for p in items if p['best']), None) or max(
            items, key=lambda p: (not p['excluded'], (p['meta'] or {}).get('defect') != 'reject', (p['meta'] or {}).get('quality', 0), p['id']))
        for p in items:
            p['alternate'] = p is not chosen


def coverage(photos, persons):
    counts = {p['id']: 0 for p in persons}
    for photo in photos:
        meta = photo['meta']
        if not meta or photo['excluded'] or photo['alternate'] or meta.get('defect') == 'reject':
            continue
        for subject in meta['people']['subjects']:
            if subject in counts:
                counts[subject] += 1
    return counts


def review(con, order_id, shoot_id):
    refresh(con, order_id)
    persons = [dict(r) for r in con.execute('SELECT id,name FROM persons WHERE order_id=? ORDER BY created_at,id', (order_id,))]
    portraits = {r['person_id']: r['id'] for r in con.execute('''SELECT p.person_id,p.id FROM photos p JOIN shoots s ON s.id=p.shoot_id
        WHERE p.order_id=? AND s.kind='portrait' AND p.person_id IS NOT NULL AND p.status='ready' ORDER BY p.uncertain,p.created_at DESC,p.id''', (order_id,))}
    for person in persons:
        person['portrait'] = portraits.get(person['id'])
    photos = _photos(con, order_id, shoot_id)
    counts = coverage(_photos(con, order_id), persons)
    faces = [dict(r) for r in con.execute('''SELECT f.id,f.photo_id,f.subject,f.source,f.score,f.level,f.cluster,f.px FROM photo_faces f
        JOIN photos p ON p.id=f.photo_id WHERE p.shoot_id=? AND f.doubtful=0 ORDER BY f.photo_id,f.idx''', (shoot_id,))]
    clusters = {}
    for face in faces:
        if face['cluster'] and face['source'] == 'auto':
            clusters.setdefault(face['cluster'], []).append({'id': face['id'], 'photo_id': face['photo_id']})
    candidates = {}
    for r in con.execute('''SELECT f.id,f.photo_id FROM photo_faces f JOIN photos p ON p.id=f.photo_id WHERE p.shoot_id=? AND f.level='uncertain' AND f.source='auto' ''', (shoot_id,)):
        candidates[r['id']] = r['photo_id']
    uncertain = [{'id': f['id'], 'photo_id': f['photo_id'], 'candidate': _candidate(con, f['id']), 'score': f['score']}
                 for f in faces if f['id'] in candidates]
    return {
        'version': gm.CONFIG['version'],
        'photos': [_summary(p) for p in photos],
        'persons': [{**p, 'count': counts.get(p['id'], 0)} for p in persons],
        'clusters': [{'id': k, 'faces': v} for k, v in sorted(clusters.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        'uncertain': uncertain,
        'labels': {'scale': SCALE_LABELS, 'bucket': BUCKET_LABELS, 'defect': DEFECT_LABELS, 'tags': {k: v[0] for k, v in TAGS.items()}},
    }


def _candidate(con, face_id):
    row = con.execute('SELECT subject FROM photo_faces WHERE id=?', (face_id,)).fetchone()
    return row['subject'] if row else None


def _summary(photo):
    meta = photo['meta'] or {}
    people = meta.get('people') or {}
    return {'id': photo['id'], 'filename': photo['filename'], 'status': photo['status'], 'error': photo['error'],
            'analyzed': bool(meta), 'bucket': people.get('bucket'), 'count': people.get('count'),
            'subjects': people.get('subjects', []), 'scale': meta.get('scale'), 'quality': meta.get('quality'),
            'defect': meta.get('defect'), 'defects': sorted({d['code'] for d in meta.get('defects', [])}),
            'tags': meta.get('tags', []), 'style': meta.get('style'), 'series': meta.get('series'), 'event': meta.get('event'),
            'taken_at': meta.get('taken_at'), 'orientation': meta.get('orientation'), 'alternate': photo['alternate'],
            'flags': {k: bool(photo[k]) for k in ('excluded', 'must_use', 'hero', 'best')}}


def detail(con, order_id, photo_id):
    refresh(con, order_id)
    row = con.execute('''SELECT p.id,p.filename,m.raw,m.meta FROM photos p JOIN photo_meta m ON m.photo_id=p.id WHERE p.id=? AND p.order_id=?''',
                      (photo_id, order_id)).fetchone()
    if row is None:
        raise HTTPException(404, 'Анализ фотографии не найден')
    raw = json.loads(row['raw'])
    faces = {r['idx']: dict(r) for r in con.execute('SELECT id,idx,subject,source,score,level,cluster,doubtful,px FROM photo_faces WHERE photo_id=?', (photo_id,))}
    return {'id': row['id'], 'filename': row['filename'], 'meta': json.loads(row['meta']) if row['meta'] else None,
            'faces': [{**{k: v for k, v in faces.get(i, {}).items() if k != 'idx'}, 'box': f['box'], 'blink': f.get('blink'), 'smile': f.get('smile'),
                       'sharp': f.get('sharp')} for i, f in enumerate(raw.get('faces', [])) if i in faces and not faces[i]['doubtful']]}


# --- layout snapshot --------------------------------------------------------------

def snapshot_entries(con, order_id):
    """Compact metadata of usable general photos for the layout engine (deterministic order)."""
    refresh(con, order_id)
    result = []
    for p in _photos(con, order_id):
        if p['status'] != 'ready' or p['excluded']:
            continue
        meta = p['meta']
        if not meta:
            result.append({'id': p['id'], 'legacy': True})
            continue
        people = meta['people']
        result.append({'id': p['id'], 'taken_at': meta.get('taken_at'), 'sequence': meta.get('sequence', 0),
                       'series': meta.get('series'), 'alt': p['alternate'], 'event': meta.get('event'),
                       'quality': meta['quality'], 'defect': meta.get('defect'), 'bucket': people['bucket'],
                       'count': people['count'], 'subjects': people['subjects'], 'scale': meta['scale'],
                       'persons': meta['persons'], 'safe_box': meta['safe_box'], 'subject_box': meta['subject_box'],
                       'tags': meta.get('tags', []), 'style': meta.get('style'), 'smile': meta.get('smile'),
                       'flags': {'must_use': bool(p['must_use']), 'hero': bool(p['hero'])}})
    return result


# --- API ---------------------------------------------------------------------------

class Flags(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=3000)
    flag: Literal['excluded', 'must_use', 'hero']
    value: bool


class Best(BaseModel):
    photo_id: str


class FaceAction(BaseModel):
    face_ids: list[str] = Field(min_length=1, max_length=5000)
    action: Literal['person', 'stranger', 'not_face', 'auto']
    person_id: str | None = None


def install(app, s):
    def shoot_of(con, order_id, shoot_id):
        row = con.execute("SELECT * FROM shoots WHERE id=? AND order_id=? AND kind='general'", (shoot_id, order_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Общая съёмка не найдена в заказе')
        return row

    @app.get('/api/orders/{order_id}/shoots/{shoot_id}/general')
    def general_review(order_id: str, shoot_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            shoot_of(con, order_id, shoot_id)
            return review(con, order_id, shoot_id)

    @app.get('/api/orders/{order_id}/general/{photo_id}')
    def general_detail(order_id: str, photo_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            return detail(con, order_id, photo_id)

    def general_ids(con, order_id, ids):
        marks = ','.join('?' for _ in ids)
        found = con.execute(f'''SELECT p.id FROM photos p JOIN shoots s ON s.id=p.shoot_id WHERE p.order_id=? AND s.kind='general' AND p.id IN ({marks})''',
                            [order_id, *ids]).fetchall()
        if len(found) != len(ids):
            raise HTTPException(404, 'Фотографии общей съёмки не найдены в заказе')

    @app.put('/api/orders/{order_id}/general/flags')
    def set_flags(order_id: str, payload: Flags):
        ids = list(set(payload.photo_ids))
        with s.db() as con:
            s.require_order(con, order_id)
            general_ids(con, order_id, ids)
            for photo_id in ids:
                con.execute('INSERT OR IGNORE INTO photo_flags (photo_id) VALUES (?)', (photo_id,))
                con.execute(f'UPDATE photo_flags SET {payload.flag}=? WHERE photo_id=?', (int(payload.value), photo_id))
        return {'ok': True}

    @app.put('/api/orders/{order_id}/general/best')
    def set_best(order_id: str, payload: Best):
        with s.db() as con:
            s.require_order(con, order_id)
            general_ids(con, order_id, [payload.photo_id])
            meta = con.execute('SELECT meta FROM photo_meta WHERE photo_id=?', (payload.photo_id,)).fetchone()
            series = (json.loads(meta['meta']) if meta and meta['meta'] else {}).get('series')
            if not series:
                raise HTTPException(409, 'Снимок не входит в серию')
            members = [r['photo_id'] for r in con.execute('''SELECT m.photo_id,m.meta FROM photo_meta m JOIN photos p ON p.id=m.photo_id
                           WHERE p.order_id=? AND m.meta IS NOT NULL''', (order_id,)).fetchall() if json.loads(r['meta']).get('series') == series]
            for photo_id in members:
                con.execute('INSERT OR IGNORE INTO photo_flags (photo_id) VALUES (?)', (photo_id,))
                con.execute('UPDATE photo_flags SET best=? WHERE photo_id=?', (int(photo_id == payload.photo_id), photo_id))
        return {'ok': True}

    @app.put('/api/orders/{order_id}/general/faces')
    def set_faces(order_id: str, payload: FaceAction):
        ids = list(set(payload.face_ids))
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            s.require_order(con, order_id)
            marks = ','.join('?' for _ in ids)
            rows = con.execute(f'SELECT f.id,f.photo_id FROM photo_faces f JOIN photos p ON p.id=f.photo_id WHERE p.order_id=? AND f.id IN ({marks})', [order_id, *ids]).fetchall()
            if len(rows) != len(ids):
                raise HTTPException(404, 'Лица не найдены в заказе')
            photos = []
            if payload.action == 'person':
                if not payload.person_id or not con.execute('SELECT 1 FROM persons WHERE id=? AND order_id=?', (payload.person_id, order_id)).fetchone():
                    raise HTTPException(404, 'Персона не найдена в заказе')
                photos = [r['photo_id'] for r in rows]
                if len(photos) != len(set(photos)):
                    raise HTTPException(409, 'Один человек не может быть на снимке дважды')
                # The same person elsewhere on these photos loses the link.
                con.execute(f"UPDATE photo_faces SET subject=NULL,source='auto' WHERE subject=? AND photo_id IN ({','.join('?' for _ in photos)}) AND id NOT IN ({marks})",
                            [payload.person_id, *photos, *ids])
                con.execute(f"UPDATE photo_faces SET subject=?,source='manual',cluster=NULL WHERE id IN ({marks})", [payload.person_id, *ids])
            elif payload.action == 'auto':
                con.execute(f"UPDATE photo_faces SET subject=NULL,source='auto' WHERE id IN ({marks})", ids)
            else:
                con.execute(f"UPDATE photo_faces SET subject=NULL,source=?,cluster=NULL WHERE id IN ({marks})", [payload.action, *ids])
            refresh(con, order_id, only={r['photo_id'] for r in rows} | set(photos if payload.action == 'person' else []))
        return {'ok': True}

    @app.post('/api/orders/{order_id}/shoots/{shoot_id}/reanalyze')
    def reanalyze(order_id: str, shoot_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            shoot_of(con, order_id, shoot_id)
            changed = con.execute("UPDATE photos SET status='pending',error='' WHERE shoot_id=? AND status IN ('ready','error')", (shoot_id,)).rowcount
        s.executor.submit(s.process_pending)
        return {'queued': changed}

    @app.get('/media/face/{face_id}/crop')
    def face_media(face_id: str):
        with s.db() as con:
            row = con.execute('SELECT f.photo_id,f.idx,m.raw FROM photo_faces f JOIN photo_meta m ON m.photo_id=f.photo_id WHERE f.id=?', (face_id,)).fetchone()
            from . import mvp
            if row is None or not mvp.photo_visible(con, row['photo_id']):
                raise HTTPException(404)
        target = s.DATA / 'photos' / 'faces' / (face_id + '.jpg')
        if not target.is_file():
            from PIL import Image
            box = json.loads(row['raw'])['faces'][row['idx']]['box']
            with Image.open(s.DATA / 'photos' / (row['photo_id'] + '.jpg')) as image:
                w, h = image.size
                x, y, bw, bh = box[0] * w, box[1] * h, box[2] * w, box[3] * h
                side = max(bw, bh) * 1.7
                crop = image.crop((round(x + bw / 2 - side / 2), round(y + bh / 2 - side / 2), round(x + bw / 2 + side / 2), round(y + bh / 2 + side / 2)))
                crop = crop.convert('RGB').resize((160, 160))
                target.parent.mkdir(parents=True, exist_ok=True)
                crop.save(target, 'JPEG', quality=85)
        return FileResponse(target, media_type='image/jpeg')
