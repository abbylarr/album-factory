"""Production V3 sorting: numeric sequence rules and bounded image prefetch."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import time

import cv2
import numpy as np
from PIL import Image


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


class PreparedImages:
    """At most three resized images in flight; inference remains on one thread.

    Timed work is CPU stage time, which overlaps inference, not wall-clock time.
    Failed speculative reads are raised only when the image is actually requested.
    """
    def __init__(self, items, workers=2, window=3):
        self.items = iter(items)
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='jpeg-prefetch')
        self.window = window
        self.futures = {}
        self.sequence = deque()
        self.decode_seconds = 0.
        self.resize_seconds = 0.
        self.wait_seconds = 0.
        self.prepared = 0
        self._fill()

    @staticmethod
    def prepare(path):
        start = time.perf_counter()
        pixels = decode(path, True)
        decoded = time.perf_counter() - start
        start = time.perf_counter()
        h, w = pixels.shape[:2]
        scale = min(1., 1600 / max(h, w))
        if scale < 1:
            pixels = cv2.resize(pixels, (round(w * scale), round(h * scale)))
        return pixels, decoded, time.perf_counter() - start

    def _fill(self):
        while len(self.futures) < self.window:
            item = next(self.items, None)
            if item is None:
                break
            key = str(item['path'])
            self.futures[key] = self.pool.submit(self.prepare, item['path'])
            self.sequence.append(key)

    def __call__(self, path, fast=False):
        if not fast:
            return decode(path, False)
        key = str(path)
        # The worker asks for endpoints first, then the middle. Filling three slots allows
        # that lookahead without changing the order used to create face groups.
        if key not in self.futures:
            # Drop completed/skipped earlier frames, keeping memory bounded.
            while key not in self.futures and self.sequence:
                old = self.sequence.popleft()
                future = self.futures.pop(old)
                self._collect(future, discard=True)
                self._fill()
        future = self.futures.pop(key, None)
        if future is None:
            raise RuntimeError('Unexpected prefetch request order')
        self.sequence.remove(key)
        start = time.perf_counter()
        try:
            return self._collect(future)
        finally:
            self.wait_seconds += time.perf_counter() - start
            self._fill()

    def _collect(self, future, discard=False):
        try:
            pixels, decoded, resized = future.result()
            self.decode_seconds += decoded
            self.resize_seconds += resized
            self.prepared += 1
            return pixels
        except Exception:
            if not discard:
                raise

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
        for future in self.futures.values():
            if not future.cancelled():
                self._collect(future, discard=True)
        self.futures.clear()
        self.sequence.clear()
