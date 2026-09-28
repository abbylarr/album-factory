"""Model-free rules that turn raw detections of general photos into layout metadata.

Raw detections come from ``vision.GeneralVision``; everything here is pure and
deterministic so thresholds can be tested and calibrated without the models.
Coordinates are normalised to the photo: boxes are [x, y, w, h] in 0..1.
"""
from __future__ import annotations

from datetime import datetime
import math

import numpy as np

# Starting values calibrated on examples/real-photos; see docs/general-photos.md §11.
CONFIG = {
    'version': 'ga-1',
    'identify_min_px': 40,        # shorter face side for identification
    'match_auto': 0.5,            # SFace cosine for an automatic link (as the portrait sorter)
    'match_margin': 0.08,         # lead over the next person
    'match_uncertain': 0.42,      # shown for review, not used by layout
    'cluster': 0.55,              # unknown faces of one person across the shoot
    'mesh_presence': 2.0,         # face mesh logit; below it the face is doubtful
    'blink_closed': 0.6,          # mean blendshape blink of both eyes
    'blink_each': 0.45,
    'look_down': -0.25,           # head pitch below this reads as looking down, not blinking
    'face_sharp': 120.0,          # Laplacian variance of the face at 64 px (focus missed below)
    'series_similarity': 0.92,
    'duplicate_similarity': 0.965,
    'series_seconds': 10,
    'event_gap_minutes': 20,
    'class_share': 0.7,
    'wide_height': 0.4,           # largest person below this share of the frame
    'keypoint': 0.3,
}

BUCKETS = ('none', 'solo', 'pair', 'small_group', 'group', 'class')
SCALES = ('detail', 'close', 'medium', 'full', 'wide')
# COCO keypoint pairs from the body model, top to bottom.
KEYPOINTS = {'shoulder': (5, 6), 'hip': (11, 12), 'knee': (13, 14), 'ankle': (15, 16)}


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    return [x0, y0, x1 - x0, y1 - y0]


def clamp_box(box):
    x0, y0 = max(0.0, box[0]), max(0.0, box[1])
    x1, y1 = min(1.0, box[0] + box[2]), min(1.0, box[1] + box[3])
    return [x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)]


def expand(box, left, top, right, bottom):
    return clamp_box([box[0] - box[2] * left, box[1] - box[3] * top,
                      box[2] * (1 + left + right), box[3] * (1 + top + bottom)])


def _inside(point, box):
    return box[0] <= point[0] <= box[0] + box[2] and box[1] <= point[1] <= box[1] + box[3]


def people(raw, cfg=CONFIG):
    """Merge faces and bodies into persons. A face belongs to the body whose head points hold it."""
    faces = raw.get('faces', [])
    bodies = raw.get('bodies', [])
    for face in faces:
        # The face mesh rejects blurred background faces; a body with a head there confirms them.
        face['doubtful'] = face.get('ignored') or face.get('presence', 99) < 0 and not any(
            sum(_inside(p, expand(face['box'], .25, .25, .25, .25)) for p in (b.get('keypoints') or [])[:5] if p[2] >= cfg['keypoint']) >= 2
            for b in bodies)
    persons, used = [], {i for i, f in enumerate(faces) if f['doubtful']}
    claimed = {}
    for body in sorted(bodies, key=lambda b: -b.get('score', 0)):
        kp = body.get('keypoints') or []
        head = [p for p in kp[:5] if p[2] >= cfg['keypoint']]
        face_index = None
        best = None
        heads = {i for i, f in enumerate(faces) if not f.get('doubtful') and sum(_inside(p, expand(f['box'], .25, .25, .25, .25)) for p in head) >= 2}
        box = body['box']
        if heads and all(i in claimed and _intersection(box, claimed[i]) / min(box[2] * box[3], claimed[i][2] * claimed[i][3] or 1) >= .5 for i in heads):
            continue  # a repeated detection of somebody already counted
        for index, face in enumerate(faces):
            if index in used:
                continue
            fb = face['box']
            hits = sum(_inside(p, expand(fb, .25, .25, .25, .25)) for p in head)
            centre = (fb[0] + fb[2] / 2, fb[1] + fb[3] / 2)
            if hits >= 2 or (not head and _inside(centre, body['box'])):
                score = hits - abs(centre[0] - (body['box'][0] + body['box'][2] / 2))
                if best is None or score > best:
                    best, face_index = score, index
        if face_index is not None:
            used.add(face_index); claimed[face_index] = body['box']
        persons.append({'body': body['box'], 'face': faces[face_index]['box'] if face_index is not None else None,
                        'face_index': face_index, 'kp': _keypoint_levels(kp, cfg)})
    for index, face in enumerate(faces):
        if index not in used:
            persons.append({'body': None, 'face': face['box'], 'face_index': index, 'kp': {}})
    for person in persons:
        person['box'] = union([person['body'], person['face']])
    return persons, faces


def _intersection(a, b):
    return max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


def _keypoint_levels(kp, cfg):
    levels = {}
    for name, (a, b) in KEYPOINTS.items():
        points = [kp[i] for i in (a, b) if i < len(kp) and kp[i][2] >= cfg['keypoint'] and 0 <= kp[i][0] <= 1 and 0 <= kp[i][1] <= 1]
        if points:
            levels[name] = [sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)]
    return levels


def person_scale(person, crop=(0, 0, 1, 1), cfg=CONFIG):
    """Shot scale of one person inside a crop (normalised to the photo)."""
    cx, cy, cw, ch = crop
    visible = {k: v for k, v in person['kp'].items() if cx <= v[0] <= cx + cw and cy <= v[1] <= cy + ch}
    box = person['box']
    top = max(box[1], cy); bottom = min(box[1] + box[3], cy + ch)
    height = max(0.0, bottom - top) / ch if ch else 0
    if person['body'] and visible:
        if height < cfg['wide_height'] and 'ankle' in visible:
            return 'wide'
        if 'ankle' in visible:
            return 'full'
        if 'knee' in visible or 'hip' in visible:
            return 'medium'
        return 'close'
    face = person['face']
    if not face:
        return 'wide' if height < cfg['wide_height'] else 'medium'
    ratio = face[3] / ch if ch else 0
    return 'close' if ratio >= .18 else 'medium' if ratio >= .07 else 'full' if ratio >= .035 else 'wide'


def main_persons(persons):
    """People that carry the picture: at least half as tall as the tallest one."""
    if not persons:
        return []
    tallest = max(p['box'][3] for p in persons)
    return [p for p in persons if p['box'][3] >= tallest * .5]


def photo_scale(persons, crop=(0, 0, 1, 1), cfg=CONFIG):
    shown = [p for p in persons if _overlap(p['box'], crop) > .5]
    if not shown:
        return 'detail'
    main = max(shown, key=lambda p: p['box'][3] * p['box'][2])
    return person_scale(main, crop, cfg)


def _overlap(box, crop):
    x0, y0 = max(box[0], crop[0]), max(box[1], crop[1])
    x1, y1 = min(box[0] + box[2], crop[0] + crop[2]), min(box[1] + box[3], crop[1] + crop[3])
    area = box[2] * box[3]
    return max(0, x1 - x0) * max(0, y1 - y0) / area if area else 0


def bucket(count, identified, class_size, cfg=CONFIG):
    if count == 0:
        return 'none'
    if class_size and count >= 7 and identified >= class_size * cfg['class_share']:
        return 'class'
    if class_size and count >= max(7, class_size * cfg['class_share']):
        return 'class'
    return 'solo' if count == 1 else 'pair' if count == 2 else 'small_group' if count <= 6 else 'group'


def boxes(persons):
    """Subject box (main people) and safe box (their heads with room) the crop must keep."""
    main = main_persons(persons)
    subject = union([p['box'] for p in main])
    heads = [expand(p['face'], .45, .6, .45, .5) if p['face'] else _head_from_body(p) for p in main]
    safe = union([h for h in heads if h]) or (expand(subject, 0, 0, 0, -.6) if subject else None)
    return subject, safe


def _head_from_body(person):
    body = person['body']
    if not body:
        return None
    shoulder = person['kp'].get('shoulder')
    bottom = shoulder[1] if shoulder else body[1] + body[3] * .2
    return clamp_box([body[0], body[1], body[2], max(.01, bottom - body[1])])


def main_faces(faces):
    """Indices of faces that carry the picture: at least 60 % of the largest face."""
    shown = [(i, f) for i, f in enumerate(faces) if not f.get('doubtful')]
    if not shown:
        return []
    largest = max(f.get('px', 0) for _, f in shown)
    return [i for i, f in shown if f.get('px', 0) >= largest * .6]


def defects(raw, persons, faces, cfg=CONFIG):
    """Photo defects. ``reject`` hides the photo from automatic layout, others lower the score.

    The blendshape model confuses closed eyes with a downward look, so a tilted
    head is never a defect and closed eyes reject only posed frames.
    """
    found = []
    main = main_faces(faces)
    sharp = [faces[i]['sharp'] for i in main if faces[i].get('sharp') is not None]
    if sharp and max(sharp) < cfg['face_sharp']:
        found.append({'code': 'blur', 'level': 'reject'})
    posed = (raw.get('clip') or {}).get('posed', 0) >= .6
    for index, face in enumerate(faces):
        blink = face.get('blink')
        if not blink or face.get('doubtful') or face.get('presence', 99) < cfg['mesh_presence'] or face.get('pitch', 0) < cfg['look_down']:
            continue
        if (blink[0] + blink[1]) / 2 >= cfg['blink_closed'] and min(blink) >= cfg['blink_each']:
            level = 'reject' if index in main and posed else 'minor'
            found.append({'code': 'eyes_closed', 'level': level, 'face': index})
    exposure = raw.get('exposure') or {}
    if exposure.get('high', 0) > .2 or exposure.get('mean', .5) < .12:
        found.append({'code': 'exposure', 'level': 'warn'})
    for index in main:
        b = faces[index]['box']
        if b[0] <= .002 or b[1] <= .002 or b[0] + b[2] >= .998 or b[1] + b[3] >= .998:
            found.append({'code': 'face_cut', 'level': 'minor'}); break
    return found


def quality(raw, persons, faces, found, cfg=CONFIG):
    clip = raw.get('clip') or {}
    aesthetic = clip.get('aesthetic', .5)
    main = [faces[i] for i in main_faces(faces)]
    sharp = [min(1.0, f['sharp'] / (cfg['face_sharp'] * 4)) for f in main if f.get('sharp') is not None]
    smiles = [f['smile'] for f in main if f.get('smile') is not None]
    score = .45 * aesthetic + .25 * (sum(sharp) / len(sharp) if sharp else .6) + .2 * (sum(smiles) / len(smiles) if smiles else .4) + .1
    for level in {(d['code'], d['level']) for d in found}:
        score -= {'reject': .5, 'warn': .15, 'minor': .08}[level[1]]
    return round(max(0.0, min(1.0, score)), 3)


def derive(raw, subjects, class_size, cfg=CONFIG):
    """Layout metadata of one photo. ``subjects`` maps face index to a subject id or None."""
    persons, faces = people(raw, cfg)
    for person in persons:
        index = person['face_index']
        person['subject'] = subjects.get(index) if index is not None else None
    identified = len({p['subject'] for p in persons if p['subject']})
    found = defects(raw, persons, faces, cfg)
    subject, safe = boxes(persons)
    width, height = raw['size']
    clip = raw.get('clip') or {}
    tags = [t for t, p in sorted((clip.get('tags') or {}).items(), key=lambda kv: -kv[1]) if p >= .25][:3]
    smiles = [faces[p['face_index']].get('smile') for p in persons if p['face_index'] is not None]
    smiles = [s for s in smiles if s is not None]
    return {
        'size': [width, height], 'orientation': 'landscape' if width > height * 1.05 else 'portrait' if height > width * 1.05 else 'square',
        'taken_at': raw.get('taken_at'),
        'people': {'count': len(persons), 'identified': identified,
                   'bucket': bucket(len(persons), identified, class_size, cfg),
                   'subjects': sorted({p['subject'] for p in persons if p['subject']})},
        'scale': photo_scale(persons, cfg=cfg),
        'persons': [{'box': _r(p['box']), 'face': _r(p['face']), 'subject': p['subject'],
                     'kp': {k: _r(v) for k, v in p['kp'].items()}} for p in persons],
        'subject_box': _r(subject), 'safe_box': _r(safe),
        'defects': found, 'defect': 'reject' if any(d['level'] == 'reject' for d in found) else None,
        'quality': quality(raw, persons, faces, found, cfg),
        'smile': round(sum(smiles) / len(smiles), 3) if smiles else None,
        'aesthetic': clip.get('aesthetic'), 'tags': tags,
        'style': None if not clip else 'posed' if clip.get('posed', .5) >= .6 else 'candid' if clip.get('posed', .5) <= .4 else None,
        'indoor': None if not clip or clip.get('indoor') is None else clip['indoor'] >= .5,
    }


def _r(value):
    if value is None:
        return None
    return [round(float(v), 4) for v in value]


# --- identity -----------------------------------------------------------------

def match_faces(vectors, gallery, cfg=CONFIG):
    """One-to-one links of faces in a photo to gallery subjects.

    ``vectors`` is a list of normalised embeddings or None (face too small);
    ``gallery`` maps subject -> array of normalised samples. Returns
    [(subject, score, level)] with level ``auto``, ``uncertain`` or None.
    """
    result = [(None, None, None)] * len(vectors)
    subjects = sorted(gallery)
    if not subjects:
        return result
    table = []
    for index, vector in enumerate(vectors):
        if vector is None:
            continue
        scores = [float(np.max(gallery[s] @ vector)) for s in subjects]
        order = sorted(range(len(subjects)), key=lambda i: -scores[i])
        best = scores[order[0]]
        runner = scores[order[1]] if len(order) > 1 else -1.0
        for rank, i in enumerate(order[:3]):
            table.append((scores[i], index, subjects[i], (scores[i] - runner) if rank == 0 else 0.0, best))
    taken_faces, taken_subjects = set(), set()
    for score, index, subject, margin, best in sorted(table, key=lambda t: (-t[0], t[1], t[2])):
        if index in taken_faces or subject in taken_subjects or score < cfg['match_uncertain']:
            continue
        level = 'auto' if score >= cfg['match_auto'] and score == best and margin >= cfg['match_margin'] else 'uncertain'
        result[index] = (subject, round(score, 4), level)
        taken_faces.add(index); taken_subjects.add(subject)
    return result


def cluster(items, cfg=CONFIG):
    """Leader clustering of unknown faces: [(key, vector, photo)] -> {key: cluster number}.

    Two faces of one photo are never the same person.
    """
    centres, members, photos, labels = [], [], [], {}
    for key, vector, photo in items:
        best, best_index = cfg['cluster'], None
        for index, centre in enumerate(centres):
            if photo in photos[index]:
                continue
            score = float(centre @ vector) / (np.linalg.norm(centre) or 1)
            if score >= best:
                best, best_index = score, index
        if best_index is None:
            centres.append(np.array(vector, dtype=np.float32)); members.append([key]); photos.append({photo})
        else:
            centres[best_index] = centres[best_index] + vector; members[best_index].append(key); photos[best_index].add(photo)
    order = sorted(range(len(members)), key=lambda i: (-len(members[i]), members[i][0]))
    for number, index in enumerate(order, 1):
        for key in members[index]:
            labels[key] = number
    return labels


# --- shoot ----------------------------------------------------------------------

def parse_time(value):
    if not value:
        return None
    try:
        # Camera wall-clock time: offsets are dropped so frames with and without them compare.
        return datetime.fromisoformat(value).replace(tzinfo=None)
    except ValueError:
        return None


def series(photos, cfg=CONFIG):
    """Group near-identical frames. ``photos``: dicts with id, order, taken_at, clip (vector or None), thumb (array or None)."""
    parent = {p['id']: p['id'] for p in photos}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]; key = parent[key]
        return key
    def join(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    ordered = sorted(photos, key=lambda p: p['order'])
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:i + 8]:
            if similar(a, b, cfg):
                join(a['id'], b['id'])
    with_clip = [p for p in photos if p.get('clip') is not None]
    if len(with_clip) > 1:
        matrix = np.array([p['clip'] for p in with_clip])
        sims = matrix @ matrix.T
        for i in range(len(with_clip)):
            for j in np.nonzero(sims[i, i + 1:] >= cfg['duplicate_similarity'])[0]:
                join(with_clip[i]['id'], with_clip[i + 1 + int(j)]['id'])
    groups = {}
    for p in photos:
        groups.setdefault(find(p['id']), []).append(p['id'])
    return {pid: root for root, ids in groups.items() for pid in ids if len(ids) > 1}


def similar(a, b, cfg=CONFIG):
    ta, tb = parse_time(a.get('taken_at')), parse_time(b.get('taken_at'))
    if ta and tb:
        close = abs((ta - tb).total_seconds()) <= cfg['series_seconds']
    else:
        close = abs(a['order'] - b['order']) <= 2
    if not close:
        return False
    if a.get('clip') is not None and b.get('clip') is not None:
        return float(np.dot(a['clip'], b['clip'])) >= cfg['series_similarity']
    if a.get('thumb') is not None and b.get('thumb') is not None:
        return float(np.sqrt(np.mean((a['thumb'] - b['thumb']) ** 2))) < .07
    return False


def events(photos, cfg=CONFIG):
    """Split the shoot by time gaps. Photos without time get no event."""
    timed = sorted((parse_time(p.get('taken_at')), p['id']) for p in photos if parse_time(p.get('taken_at')))
    result, number, previous = {}, 0, None
    for moment, pid in timed:
        gap = (moment - previous).total_seconds() / 60 if previous else math.inf
        if gap > cfg['event_gap_minutes']:
            number += 1
        result[pid] = number
        previous = moment
    return result
