"""Isolated sorting experiment. Never writes photos, people or production assignments."""
from collections import Counter
from pathlib import Path
import re
import time

import cv2
import numpy as np
from PIL import Image

from .faces import choose_person


def sequence_key(item):
    stem = Path(item['filename']).stem
    match = re.fullmatch(r'(.*?)(\d+)', stem)
    return (match[1].casefold(), int(match[2])) if match else None


def ordered(items):
    return sorted(items, key=lambda p: (sequence_key(p) is None, sequence_key(p) or ('', 0), p['filename'], p['id']))


def decode(path, fast=False):
    if not fast:
        with Image.open(path) as im:
            return cv2.cvtColor(np.asarray(im.convert('RGB')), cv2.COLOR_RGB2BGR)
    # Working files have already had EXIF rotation baked in by the uploader.
    with Image.open(path) as im:
        longest = max(im.size)
        factor = 8 if longest >= 12800 else 4 if longest >= 6400 else 2 if longest >= 3200 else 1
    flags = {1: cv2.IMREAD_COLOR, 2: cv2.IMREAD_REDUCED_COLOR_2,
             4: cv2.IMREAD_REDUCED_COLOR_4, 8: cv2.IMREAD_REDUCED_COLOR_8}
    pixels = cv2.imread(str(path), flags[factor] | cv2.IMREAD_IGNORE_ORIENTATION)
    if pixels is None:
        raise ValueError('Cannot decode image')
    return pixels


def preview(item):
    path = item.get('thumbnail') or item['path']
    with Image.open(path) as im:
        aspect = im.width / im.height
        im.draft('RGB', (64, 64))
        pixels = np.asarray(im.convert('RGB').resize((32, 32)), dtype=np.float32) / 255
    return aspect, pixels


def bridge_allowed(left, middle, right, previews):
    keys = [sequence_key(p) for p in (left, middle, right)]
    if any(k is None for k in keys) or len({k[0] for k in keys}) != 1:
        return False
    # Only a single existing frame, bounded numeric gaps, no duplicate counters.
    if not all(0 < b[1] - a[1] <= 3 for a, b in zip(keys, keys[1:])):
        return False
    values = [previews[p['id']] for p in (left, middle, right)]
    if max(v[0] for v in values) - min(v[0] for v in values) > .02:
        return False
    return all(float(np.sqrt(np.mean((values[1][1] - v[1]) ** 2))) < .065 for v in (values[0], values[2]))


def run(items, engine, mode='v1', progress=lambda *args: None, *, decoder=None):
    if mode not in {'v1', 'v2', 'v2_series'}:
        raise ValueError('Unknown sorting mode')
    decoder = decoder or decode
    start = time.perf_counter()
    timings = dict(decode=0., recognition=0., matching=0., previews=0.)
    groups, results = {}, {}
    fast = mode != 'v1'
    rows = ordered(items) if mode == 'v2_series' else list(items)
    previews = {}
    if mode == 'v2_series':
        t = time.perf_counter()
        for p in rows:
            try:
                previews[p['id']] = preview(p)
            except (OSError, ValueError):
                pass  # Decode errors are recorded by the full path below.
        timings['previews'] = time.perf_counter() - t

    def recognize(p):
        if p['id'] in results:
            return results[p['id']]
        result = dict(id=p['id'], filename=p['filename'], person_id=None, uncertain=False, source='face')
        try:
            t = time.perf_counter()
            pixels = decoder(p['path'], fast)
            timings['decode'] += time.perf_counter() - t
            t = time.perf_counter()
            status, vector = engine.extract(pixels)
            # Retry rejected fast decodes with original pixels; preserve small/multiple-face handling.
            if fast and vector is None:
                timings['recognition'] += time.perf_counter() - t
                t = time.perf_counter()
                pixels = decoder(p['path'])
                timings['decode'] += time.perf_counter() - t
                t = time.perf_counter()
                status, vector = engine.extract(pixels)
            timings['recognition'] += time.perf_counter() - t
            result['status'] = status
            if vector is not None:
                t = time.perf_counter()
                person, uncertain = choose_person(vector, groups)
                if person is None:
                    person = f'p{len(groups) + 1}'
                    groups[person] = []
                groups[person].append(vector)
                result.update(person_id=person, uncertain=uncertain)
                timings['matching'] += time.perf_counter() - t
        except Exception as exc:
            result.update(status='error', source='error', error=type(exc).__name__)
        results[p['id']] = result
        progress(mode, len(results), len(rows))
        return result

    if mode != 'v2_series':
        for p in rows:
            recognize(p)
    else:
        # Only recognized endpoints can support one skipped frame. Inferred frames
        # never become anchors or face samples. A returning person is matched globally.
        for index in range(0, len(rows), 2):
            left = rows[index]
            a = recognize(left)
            if index + 1 >= len(rows):
                break
            middle = rows[index + 1]
            if index + 2 >= len(rows):
                recognize(middle)
                break
            right = rows[index + 2]
            b = recognize(right)
            if (a['status'] == b['status'] == 'ready' and a['person_id'] == b['person_id']
                    and not a['uncertain'] and not b['uncertain']
                    and all(p['id'] in previews for p in (left, middle, right))
                    and bridge_allowed(left, middle, right, previews)):
                results[middle['id']] = dict(id=middle['id'], filename=middle['filename'],
                    status='ready', person_id=a['person_id'], uncertain=True, source='sequence',
                    anchors=[left['id'], right['id']])
                progress(mode, len(results), len(rows))
            else:
                recognize(middle)
    elapsed = time.perf_counter() - start
    photos = [results[p['id']] for p in items]
    return dict(mode=mode, seconds=elapsed, photos_per_minute=60 * len(items) / elapsed if elapsed else 0,
                timings=timings, persons=len(groups), inferred=sum(p['source'] == 'sequence' for p in photos),
                errors=sum(p['status'] == 'error' for p in photos), photos=photos)


def compare(baseline, candidate):
    """Label-invariant partition comparison. Baseline is NOT ground truth."""
    a = {p['id']: p for p in baseline['photos']}
    b = {p['id']: p for p in candidate['photos']}
    common = a.keys() & b.keys()
    def label(p):
        return p['person_id'] or ('unassigned', p['id'])
    ac = Counter(label(a[i]) for i in common)
    bc = Counter(label(b[i]) for i in common)
    both = Counter((label(a[i]), label(b[i])) for i in common)
    pairs = lambda counts: sum(n * (n - 1) // 2 for n in counts.values())
    shared = pairs(both)
    changed = [i for i in common if a[i]['status'] != b[i]['status']
               or ac[label(a[i])] != both[label(a[i]), label(b[i])]
               or bc[label(b[i])] != both[label(a[i]), label(b[i])]]
    return dict(speedup=baseline['seconds'] / candidate['seconds'],
                split_pairs=pairs(ac) - shared, merged_pairs=pairs(bc) - shared,
                changed_ids=sorted(changed), changed_photos=len(changed))
