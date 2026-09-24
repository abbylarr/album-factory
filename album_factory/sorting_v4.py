"""Experimental V4 detector cascade and V5 adaptive series; isolated lab only."""
import time

import cv2
import numpy as np

from .faces import FaceEngine, choose_person
from .sorting_v2 import ordered, preview, sequence_key
from .sorting_v3 import PreparedImages


class CascadeEngine(FaceEngine):
    def __init__(self, detection_size=960):
        super().__init__()
        self.detection_size = detection_size
        self.fallbacks = 0

    def full(self, image):
        self.fallbacks += 1
        return super().extract(image)

    def quick(self, image):
        h, w = image.shape[:2]
        scale = min(1., self.detection_size / max(h, w))
        small = cv2.resize(image, (round(w * scale), round(h * scale))) if scale < 1 else image
        self.detector.setInputSize((small.shape[1], small.shape[0]))
        _, faces = self.detector.detect(small)
        if faces is None or len(faces) != 1 or min(faces[0][2:4]) < 40 or faces[0][-1] < .95:
            status, vector = self.full(image)
            return status, vector, True
        face = faces[0].copy()
        # Bounding box and five landmarks are rescaled independently, accounting
        # for rounded detector dimensions. Keep the confidence score unchanged.
        face[[0, 2, 4, 6, 8, 10, 12]] *= w / small.shape[1]
        face[[1, 3, 5, 7, 9, 11, 13]] *= h / small.shape[0]
        aligned = self.recognizer.alignCrop(image, face)
        vector = self.recognizer.feature(aligned).flatten().astype(float)
        norm = np.linalg.norm(vector)
        if not np.isfinite(norm) or norm == 0:
            status, vector = self.full(image)
            return status, vector, True
        return 'ready', (vector / norm).tolist(), False


def consistent_interval(rows, previews):
    keys = [sequence_key(p) for p in rows]
    if any(k is None for k in keys) or len({k[0] for k in keys}) != 1:
        return False
    if not all(0 < b[1] - a[1] <= 3 for a, b in zip(keys, keys[1:])):
        return False
    if not all(p['id'] in previews for p in rows):
        return False
    values = [previews[p['id']] for p in rows]
    if max(v[0] for v in values) - min(v[0] for v in values) > .02:
        return False
    # Every intermediate frame must agree with BOTH recognized endpoints.
    # This remains a heuristic, never proof of identity or absence of a group shot.
    return all(float(np.sqrt(np.mean((middle[1] - edge[1]) ** 2))) < .065
               for middle in values[1:-1] for edge in (values[0], values[-1]))


def run(items, mode='v4', progress=lambda *args: None, detection_size=960,
        decode_workers=1, opencv_threads=2, max_step=4):
    if mode not in {'v4', 'v5'}:
        raise ValueError('Unknown cascade mode')
    previous_threads = cv2.getNumThreads()
    prepared = None
    try:
        # The lab holds the shared worker lock. Restore this process-wide setting
        # before returning to the production worker or any older lab variant.
        cv2.setNumThreads(opencv_threads)
        engine = CascadeEngine(detection_size)
        engine.extract(np.zeros((320, 320, 3), np.uint8))
        start = time.perf_counter()
        rows = ordered(items)
        window = max_step + 1 if mode == 'v5' else 3
        prepared = PreparedImages(rows, workers=decode_workers, window=window)
        timings = dict(decode=0., recognition=0., matching=0., previews=0.)
        groups, results, previews = {}, {}, {}
        t = time.perf_counter()
        for p in rows:
            try:
                previews[p['id']] = preview(p)
            except (OSError, ValueError):
                pass
        timings['previews'] = time.perf_counter() - t
        steps = {str(i): 0 for i in range(2, max_step + 1)}

        def recognize(p):
            if p['id'] in results:
                return results[p['id']]
            result = dict(id=p['id'], filename=p['filename'], person_id=None,
                          uncertain=False, source='face')
            try:
                t = time.perf_counter()
                pixels = prepared(p['path'], True)
                timings['decode'] += time.perf_counter() - t
                t = time.perf_counter()
                status, vector, full = engine.quick(pixels)
                timings['recognition'] += time.perf_counter() - t
                t = time.perf_counter()
                person, uncertain = choose_person(vector, groups) if vector is not None else (None, False)
                timings['matching'] += time.perf_counter() - t
                # Unknown/ambiguous identity gets the 1600px pass before creating
                # a new group. Never add a provisional low-res sample first.
                if vector is not None and groups and (person is None or uncertain) and not full:
                    t = time.perf_counter()
                    status, vector = engine.full(pixels)
                    timings['recognition'] += time.perf_counter() - t
                    full = True
                if vector is None:
                    t = time.perf_counter()
                    original = prepared(p['path'], False)
                    timings['decode'] += time.perf_counter() - t
                    t = time.perf_counter()
                    status, vector = engine.full(original)
                    timings['recognition'] += time.perf_counter() - t
                    full = True
                result.update(status=status, detection='full' if full else 'small')
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

        index, step, streak = 0, 2, 0
        while index < len(rows):
            left = recognize(rows[index])
            end = min(index + step, len(rows) - 1)
            if end == index:
                break
            right = recognize(rows[end])
            interval = rows[index:end + 1]
            trusted = (left['status'] == right['status'] == 'ready'
                       and left['person_id'] == right['person_id']
                       and not left['uncertain'] and not right['uncertain'])
            bridged = trusted and consistent_interval(interval, previews)
            if end - index >= 2:
                steps[str(end - index)] += 1
            if bridged:
                for p in interval[1:-1]:
                    results[p['id']] = dict(id=p['id'], filename=p['filename'], status='ready',
                        person_id=left['person_id'], uncertain=True, source='sequence',
                        anchors=[rows[index]['id'], rows[end]['id']], step=end-index)
                    progress(mode, len(results), len(rows))
                streak += 1
                if mode == 'v5' and streak >= 2:
                    step = min(max_step, step + 1)
                    streak = 0
            else:
                # Resolve every intervening frame, not merely the midpoint.
                for p in interval[1:-1]:
                    recognize(p)
                step, streak = 2, 0
            index = end
        prepared.close()
        elapsed = time.perf_counter() - start
        photos = [results[p['id']] for p in items]
        return dict(mode=mode, seconds=elapsed, photos_per_minute=60 * len(items) / elapsed if elapsed else 0,
                    timings=timings, persons=len(groups), inferred=sum(p['source']=='sequence' for p in photos),
                    errors=sum(p['status']=='error' for p in photos), photos=photos,
                    settings=dict(detection_size=detection_size, decode_workers=decode_workers,
                                  opencv_threads=opencv_threads, max_step=max_step if mode=='v5' else 2),
                    cascade=dict(full_passes=engine.fallbacks), adaptive_steps=steps,
                    pipeline=dict(workers=decode_workers, window=window, prepared=prepared.prepared,
                        decode_work_seconds=prepared.decode_seconds, resize_work_seconds=prepared.resize_seconds,
                        wait_seconds=prepared.wait_seconds))
    finally:
        if prepared is not None:
            prepared.close()
        cv2.setNumThreads(previous_threads)
