"""A deterministic synthetic general shoot for master-editor previews and tests.

Detections are generated geometrically and pass through the same
``general_meta.derive`` rules as real photos, so previews show what the
picker would really do with a shoot of this shape.
"""
from __future__ import annotations

import random

from . import general_meta as gm

# (bucket, share of the shoot, scales, style)
MIX = [
    ('class', .06, ['full', 'wide'], 'posed'),
    ('group', .16, ['medium', 'full', 'wide'], None),
    ('small_group', .26, ['close', 'medium', 'full'], None),
    ('pair', .2, ['close', 'medium', 'full'], None),
    ('solo', .16, ['close', 'medium', 'full'], None),
    ('none', .08, ['detail'], 'candid'),
]
FACE = {'close': .26, 'medium': .12, 'full': .085, 'wide': .035}
HEAD_Y = {'close': .34, 'medium': .24, 'full': .14, 'wide': .5}
TAG_BY_EVENT = [['classroom'], ['hall', 'library'], ['nature'], ['ceremony']]


def _person(cx, hy, face, aspect):
    """Face box, body box and COCO keypoints of a standing person (normalised)."""
    fw = face * .75 / aspect
    points = [(cx, hy + face * .1), (cx + fw * .2, hy - face * .05), (cx - fw * .2, hy - face * .05),
              (cx + fw * .45, hy), (cx - fw * .45, hy)]
    ys = {'shoulder': hy + face * 1.1, 'hip': hy + face * 3.1, 'knee': hy + face * 4.9, 'ankle': hy + face * 6.7}
    width = fw * 1.4
    kp = [[x, y, .95] for x, y in points]
    for name in ('shoulder', 'elbow', 'wrist'):
        y = ys['shoulder'] + (0 if name == 'shoulder' else face * (1.2 if name == 'elbow' else 2.2))
        kp += [[cx + width, y, .9 if y <= 1 else 0], [cx - width, y, .9 if y <= 1 else 0]]
    for name in ('hip', 'knee', 'ankle'):
        y = ys[name]
        kp += [[cx + width * .5, y, .9 if y <= 1 else 0], [cx - width * .5, y, .9 if y <= 1 else 0]]
    top = hy - face * .65
    bottom = min(1.0, ys['ankle'] + face * .3)
    return ({'box': [cx - fw / 2, hy - face / 2, fw, face], 'score': .95, 'presence': 10.0, 'sharp': 600.0,
             'blink': [.1, .1], 'smile': .5, 'pitch': 0.0},
            {'box': gm.clamp_box([cx - width * 1.3, top, width * 2.6, bottom - top]), 'score': .9, 'keypoints': kp})


def synthetic(students, count=None, seed=7):
    """Return (entries, photos): snapshot-style general entries and their sizes."""
    rng = random.Random(seed)
    ids = [s['id'] for s in students] or ['s0']
    total = count or max(48, len(ids) * 4)
    plan = []
    for bucket, share, scales, style in MIX:
        plan += [(bucket, scales, style)] * max(1, round(total * share))
    entries, photos, cursor = [], {}, 0
    for index, (bucket, scales, style) in enumerate(plan):
        landscape = bucket in ('class', 'group') or rng.random() < .55
        width, height = (6000, 4000) if landscape else (4000, 6000)
        aspect = width / height
        scale = scales[index % len(scales)]
        n = {'none': 0, 'solo': 1, 'pair': 2, 'small_group': rng.randint(3, 6), 'group': rng.randint(7, 12),
             'class': max(7, round(len(ids) * .85))}[bucket]
        if bucket == 'class' or n > 8:
            scale = 'wide' if scale == 'wide' else 'full'
        face = FACE.get(scale, .1)
        rows = 2 if n > 8 else 1
        per_row = max(1, -(-n // rows))
        span = min(.84, per_row * face * 1.1 / aspect + .1)
        if n and span / per_row < face * .8 / aspect:
            face = span / per_row * aspect / .8
        faces, bodies = [], []
        for i in range(n):
            row, col = divmod(i, per_row)
            cx = .5 - span / 2 + (col + .5) * span / per_row
            hy = HEAD_Y.get(scale, .3) + row * face * 1.6
            f, b = _person(cx, hy, face, aspect)
            f['px'] = face * height
            faces.append(f); bodies.append(b)
        subjects = {}
        chosen = ids if bucket == 'class' else [ids[(cursor + k) % len(ids)] for k in range(n)]
        cursor += max(1, n)
        for i in range(min(n, len(chosen))):
            subjects[i] = chosen[i]
        event = index * len(TAG_BY_EVENT) // len(plan)
        raw = {'size': [width, height], 'taken_at': f'2026-05-{14 + event:02d}T{9 + index % 8:02d}:{index % 60:02d}:00',
               'faces': faces, 'bodies': bodies, 'exposure': {'mean': .5, 'high': 0, 'low': 0}, 'sharp': 500,
               'clip': {'aesthetic': round(.35 + rng.random() * .6, 2), 'posed': .8 if style == 'posed' else .2 if style == 'candid' else rng.choice([.2, .8]),
                        'indoor': .7, 'tags': {t: .6 for t in TAG_BY_EVENT[event]}}}
        meta = gm.derive(raw, subjects, len(ids))
        photo_id = f'test-{index:03d}'
        photos[photo_id] = {'width': width, 'height': height, 'path': ''}
        entries.append({'id': photo_id, 'taken_at': raw['taken_at'], 'sequence': index, 'series': None, 'alt': False,
                        'event': event, 'quality': meta['quality'], 'defect': None, 'bucket': meta['people']['bucket'],
                        'count': meta['people']['count'], 'subjects': meta['people']['subjects'], 'scale': meta['scale'],
                        'persons': meta['persons'], 'safe_box': meta['safe_box'], 'subject_box': meta['subject_box'],
                        'tags': meta['tags'], 'style': meta['style'], 'smile': meta['smile'], 'flags': {}})
    return entries, photos
