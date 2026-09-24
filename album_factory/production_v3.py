"""Durable V3 queue adapter: shared prefetch/series rules, transactional assignments."""
import json
import time

from .faces import choose_person
from .sorting_v2 import ordered, preview, bridge_allowed
from .sorting_v3 import PreparedImages


def process_batch(server, items, engine):
    rows = ordered(items)
    previews = {}
    last_finished = time.monotonic()
    prepared = PreparedImages(rows, workers=2, window=3)

    def save_metadata(con, photo_id, source, anchors=()):
        nonlocal last_finished
        finished = time.monotonic()
        con.execute('INSERT OR REPLACE INTO processing_times VALUES (?,?,?)',
                    (photo_id, finished - last_finished, server.now()))
        con.execute('INSERT OR REPLACE INTO photo_analysis VALUES (?,?,?,?)',
                    (photo_id, 'v3', source, json.dumps(list(anchors))))
        last_finished = finished

    def recognize(p):
        try:
            with server.db() as con:
                current = con.execute('SELECT status FROM photos WHERE id=?', (p['id'],)).fetchone()
                if current is None or current['status'] != 'processing':
                    return
            pixels = prepared(p['path'], True)
            status, vector = engine.extract(pixels)
            if vector is None:
                status, vector = engine.extract(prepared(p['path'], False))
            with server.db() as con:
                con.execute('BEGIN IMMEDIATE')
                current = con.execute('SELECT status FROM photos WHERE id=?', (p['id'],)).fetchone()
                if current is None or current['status'] != 'processing':
                    return
                person, uncertain = None, False
                if vector is not None:
                    # Read the CURRENT assignments, including concurrent manual moves.
                    # Inferred frames have no embedding and cannot become samples.
                    groups = {}
                    for sample in con.execute('SELECT person_id,embedding FROM photos WHERE order_id=? AND person_id IS NOT NULL AND embedding IS NOT NULL', (p['order_id'],)):
                        groups.setdefault(sample['person_id'], []).append(json.loads(sample['embedding']))
                    person, uncertain = choose_person(vector, groups, strong_match_threshold=0.93)
                    if person is None:
                        person = server.uid()
                        con.execute('INSERT INTO persons VALUES (?,?,?,?)', (person, p['order_id'], '', server.now()))
                con.execute("UPDATE photos SET status=?,person_id=?,embedding=?,uncertain=?,error='' WHERE id=?",
                            (status, person, json.dumps(vector) if vector is not None else None, int(uncertain), p['id']))
                save_metadata(con, p['id'], 'face')
        except Exception:
            server.log.exception('V3 processing failed: %s', p['id'])
            with server.db() as con:
                con.execute("UPDATE photos SET status='error',error=? WHERE id=? AND status='processing'",
                            ('Не удалось обработать снимок. Повторите обработку.', p['id']))

    def infer(left, middle, right):
        for p in (left, middle, right):
            if p['id'] not in previews:
                try:
                    previews[p['id']] = preview(p)
                except (OSError, ValueError):
                    return False
        if not bridge_allowed(left, middle, right, previews):
            return False
        with server.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current = {r['id']: dict(r) for r in con.execute('SELECT id,filename,status,person_id,embedding,uncertain FROM photos WHERE order_id=? AND shoot_id IS ?', (middle['order_id'], middle.get('shoot_id')))}
            if any(p['id'] not in current for p in (left, middle, right)):
                return False
            a, m, b = [current[p['id']] for p in (left, middle, right)]
            if not (m['status'] == 'processing' and a['status'] == b['status'] == 'ready'
                    and a['person_id'] and a['person_id'] == b['person_id']
                    and a['embedding'] and b['embedding'] and not a['uncertain'] and not b['uncertain']):
                return False
            # Uploads may finish out of order. Never bridge across another known
            # photo that wasn't in this pending batch (including earlier results).
            sequence = [p['id'] for p in ordered(current.values())]
            i = sequence.index(left['id'])
            if sequence[i:i+3] != [left['id'], middle['id'], right['id']]:
                return False
            con.execute("UPDATE photos SET status='ready',person_id=?,embedding=NULL,uncertain=1,error='' WHERE id=?",
                        (a['person_id'], middle['id']))
            save_metadata(con, middle['id'], 'sequence', (left['id'], right['id']))
            return True

    try:
        # The same endpoint-first triples as the laboratory's V3. Each recognized
        # result is durable immediately; restart recovers only unfinished photos.
        for index in range(0, len(rows), 2):
            recognize(rows[index])
            if index + 1 >= len(rows):
                break
            if index + 2 >= len(rows):
                recognize(rows[index + 1])
                break
            recognize(rows[index + 2])
            if not infer(*rows[index:index+3]):
                recognize(rows[index + 1])
    finally:
        prepared.close()
