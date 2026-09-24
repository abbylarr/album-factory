"""Read-only trials exposed separately from the production sorting worker."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal
import json
import re
import threading
import uuid

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .faces import FaceEngine
from .sorting_v2 import compare, ordered, run
from .sorting_v3 import run as run_v3
from .sorting_v4 import run as run_cascade


class TrialInput(BaseModel):
    limit: int = Field(default=120, ge=1, le=3000)
    offset: int = Field(default=0, ge=0, le=3000)
    mode: Literal['compare', 'compare_v3', 'compare_v4_v5', 'v1', 'v2', 'v2_series', 'v3', 'v4', 'v5'] = 'compare'
    detection_size: Literal[960, 1120] = 960
    decode_workers: Literal[1, 2] = 1
    opencv_threads: Literal[1, 2, 4] = 2
    max_step: Literal[3, 4] = 4


def snapshot(con, data, order_id, limit=120, offset=0):
    rows = [dict(r) for r in con.execute(
        'SELECT id,filename FROM photos WHERE order_id=? ORDER BY created_at,id', (order_id,))]
    selected = {p['id'] for p in ordered(rows)[offset:offset + limit]}
    return [dict(p, path=str(data / 'photos' / (p['id'] + '.jpg')),
                 thumbnail=str(data / 'photos' / (p['id'] + '.thumb.jpg'))) for p in rows if p['id'] in selected]


def experiment(items, mode='compare', progress=lambda *args: None, settings=None):
    engine = FaceEngine()
    # Warm up model loading outside measured runs equally for all variants.
    import numpy as np
    engine.extract(np.zeros((320, 320, 3), dtype=np.uint8))
    modes = ['v1', 'v2', 'v2_series', 'v3', 'v4', 'v5'] if mode == 'compare' else ['v2_series', 'v3'] if mode == 'compare_v3' else ['v3', 'v4', 'v5'] if mode == 'compare_v4_v5' else [mode]
    variants = {m: run_cascade(items, m, progress, **(settings or {})) if m in {'v4', 'v5'} else run_v3(items, engine, progress) if m == 'v3' else run(items, engine, m, progress) for m in modes}
    relative = {}
    for candidate, baseline in [('v3', 'v2_series'), ('v4', 'v3'), ('v5', 'v4')]:
        if candidate in variants and baseline in variants:
            relative[candidate] = dict(compare(variants[baseline], variants[candidate]), baseline=baseline)
    comparisons = {m: compare(variants['v1'], variants[m]) for m in modes if m != 'v1'} if 'v1' in variants else {}
    versus_v2_series = compare(variants['v2_series'], variants['v3']) if 'v2_series' in variants and 'v3' in variants else None
    return dict(variants=variants, comparisons=comparisons, versus_v2_series=versus_v2_series, relative=relative,
                note='V1 — автоматическая база сравнения, не ручная разметка. Время без загрузки, подготовки превью и записи рабочих групп. Повторные проходы могут использовать файловый кеш ОС.')


def install(app, server):
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='sorting-trial')
    lock = threading.Lock()
    jobs = {}

    def report_path(trial_id):
        return server.DATA / 'sorting_trials' / (trial_id + '.json')

    def work(trial_id, items, mode, settings):
        def progress(variant, done, total):
            with lock:
                jobs[trial_id].update(status='running', mode=variant, done=done, total=total)
        try:
            # No simultaneous experimental and production inference on this process.
            with server.worker_lock:
                progress(mode, 0, len(items))
                result = experiment(items, mode, progress, settings)
            with lock:
                report = dict(jobs[trial_id], status='complete', result=result)
            path = report_path(trial_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
            with lock:
                jobs[trial_id] = report
        except Exception:
            server.log.exception('Sorting trial failed')
            with lock:
                jobs[trial_id].update(status='error', error='Проба прервана. Рабочие группы не изменены; проверьте доступность файлов и моделей.')

    @app.get('/sorting-lab')
    def page():
        return FileResponse(server.ROOT / 'web/sorting-lab.html')

    @app.post('/api/orders/{order_id}/sorting-trials', status_code=202)
    def start_trial(order_id: str, payload: TrialInput):
        with server.db() as con:
            order = dict(server.require_order(con, order_id))
            if con.execute("SELECT 1 FROM photos WHERE status IN ('pending','processing') LIMIT 1").fetchone():
                raise HTTPException(409, 'Дождитесь завершения текущей обработки, затем запустите пробу')
            items = snapshot(con, server.DATA, order_id, payload.limit, payload.offset)
        if not items:
            raise HTTPException(422, 'В выбранном диапазоне нет фотографий')
        with lock:
            if any(j['status'] in {'queued', 'running'} for j in jobs.values()):
                raise HTTPException(409, 'Уже выполняется проба. Дождитесь её завершения')
            trial_id = uuid.uuid4().hex
            jobs[trial_id] = dict(id=trial_id, order_id=order_id, order_name=order['school'] + ' / ' + order['class_name'],
                                 created_at=server.now(), status='queued', total=len(items), done=0,
                                 mode=payload.mode, offset=payload.offset)
        settings = payload.model_dump(include={'detection_size', 'decode_workers', 'opencv_threads', 'max_step'})
        pool.submit(work, trial_id, items, payload.mode, settings)
        return {'id': trial_id}

    @app.get('/api/sorting-trials/{trial_id}')
    def get_trial(trial_id: str):
        if not re.fullmatch('[a-f0-9]{32}', trial_id):
            raise HTTPException(404, 'Проба не найдена')
        with lock:
            if trial_id in jobs:
                return dict(jobs[trial_id])
        path = report_path(trial_id)
        if path.is_file():
            return json.loads(path.read_text(encoding='utf-8'))
        raise HTTPException(404, 'Проба не найдена или сервер был перезапущен до её завершения')
