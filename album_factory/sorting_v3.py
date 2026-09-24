"""V3: bounded decode/resize prefetch, with V2-series decisions unchanged."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import time

import cv2

from .sorting_v2 import decode, ordered, run as run_v2


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
        # V2 asks for endpoints first, then the middle. Filling three slots allows
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


def run(items, engine, progress=lambda *args: None):
    start = time.perf_counter()
    prepared = PreparedImages(ordered(items))
    try:
        result = run_v2(items, engine, 'v2_series',
                        lambda _mode, done, total: progress('v3', done, total),
                        decoder=prepared)
    finally:
        prepared.close()
    elapsed = time.perf_counter() - start
    result.update(mode='v3', seconds=elapsed,
                  photos_per_minute=60 * len(items) / elapsed if elapsed else 0)
    result['pipeline'] = dict(workers=2, window=3, prepared=prepared.prepared,
                              decode_work_seconds=prepared.decode_seconds,
                              resize_work_seconds=prepared.resize_seconds,
                              wait_seconds=prepared.wait_seconds)
    # 'decode' in run_v2 measures the main thread's waits plus fallback decodes;
    # worker CPU stage durations are separately reported, never added to wall time.
    return result
