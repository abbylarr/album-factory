"""Single-user localhost pilot: SQLite, durable uploads, one local recognition worker."""
from __future__ import annotations
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import uuid
import asyncio
import time

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from . import shoots
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .faces import FaceEngine
from .production_v3 import process_batch as process_v3_batch

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("ALBUM_DATA_DIR", ROOT / "data"))
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_PHOTOS = 3000
STAGES = {"planned", "scheduled", "upload", "layout"}
executor = ThreadPoolExecutor(max_workers=1)
image_executor = ThreadPoolExecutor(max_workers=4)
worker_lock = threading.Lock()
upload_lock = threading.Lock()
engine = None
log = logging.getLogger("album-factory")


def db():
    connection = sqlite3.connect(DATA / "album.sqlite", timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "photos").mkdir(exist_ok=True)
    with db() as con:
        con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY, school TEXT NOT NULL, class_name TEXT NOT NULL,
          copies INTEGER NOT NULL, price INTEGER NOT NULL DEFAULT 0,
          shoot_date TEXT NOT NULL DEFAULT '', stage TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS persons (
          id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
          name TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS photos (
          id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
          filename TEXT NOT NULL, sha TEXT NOT NULL, status TEXT NOT NULL,
          person_id TEXT REFERENCES persons(id), embedding TEXT,
          uncertain INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL, UNIQUE(order_id, sha));
        """)
        con.execute("CREATE TABLE IF NOT EXISTS processing_times (photo_id TEXT PRIMARY KEY, seconds REAL NOT NULL, finished_at TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS order_covers (order_id TEXT PRIMARY KEY REFERENCES orders(id), photo_id TEXT NOT NULL REFERENCES photos(id))")
        con.execute("CREATE TABLE IF NOT EXISTS photo_analysis (photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE, algorithm TEXT NOT NULL, source TEXT NOT NULL, anchors TEXT NOT NULL)")
        shoots.init(con)
        from .client_portal import init as init_client_portal
        init_client_portal(con)
        con.execute("UPDATE photos SET status='pending' WHERE status='processing'")


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def prepare_photo_files(body: bytes, photo_id: str) -> None:
    """Validate image bytes and write original + working JPEG + thumbnail.

    Camera JPEGs without EXIF rotation are stored as-is for the working file to
    avoid a full re-encode on every upload.
    """
    paths = [DATA / "photos" / (photo_id + suffix) for suffix in [".original", ".jpg", ".thumb.jpg"]]
    try:
        with Image.open(BytesIO(body)) as image:
            if image.format not in {"JPEG", "PNG", "MPO"}:
                raise HTTPException(415, "Поддерживаются JPG, JPEG и PNG")
            width, height = image.size
            if width * height > MAX_PIXELS:
                raise HTTPException(413, "Изображение больше 50 мегапикселей")
            orientation = (image.getexif() or {}).get(0x0112, 1)
            needs_reencode = image.format not in {"JPEG", "MPO"} or orientation not in (1, None)
            paths[0].write_bytes(body)
            if needs_reencode:
                working = ImageOps.exif_transpose(image).convert("RGB")
                working.load()
                working.save(paths[1], "JPEG", quality=90, optimize=False)
                thumb = working
            else:
                paths[1].write_bytes(body)
                thumb = ImageOps.exif_transpose(image)
            thumb.thumbnail((480, 640), Image.Resampling.BILINEAR)
            if thumb.mode != "RGB":
                thumb = thumb.convert("RGB")
            thumb.save(paths[2], "JPEG", quality=80, optimize=False)
    except HTTPException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        for path in paths:
            path.unlink(missing_ok=True)
        raise HTTPException(415, "Не удалось прочитать изображение") from exc


def require_order(con, order_id):
    row = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Заказ не найден")
    return row


def process_pending():
    global engine
    with worker_lock:
        while True:
            with db() as con:
                con.execute("BEGIN IMMEDIATE")
                first = con.execute("SELECT order_id,shoot_id FROM photos WHERE status='pending' ORDER BY created_at,id LIMIT 1").fetchone()
                if first is None:
                    return
                rows = [dict(r) for r in con.execute("SELECT * FROM photos WHERE order_id=? AND shoot_id IS ? AND status='pending' ORDER BY created_at,id", (first['order_id'], first['shoot_id']))]
                shoot = con.execute('SELECT kind FROM shoots WHERE id=?', (first['shoot_id'],)).fetchone()
                if shoot and shoot['kind'] == 'general':
                    con.executemany("UPDATE photos SET status='ready',uncertain=0,error='' WHERE id=?", [(r['id'],) for r in rows])
                    continue
                for row in rows:
                    row['path'] = str(DATA / 'photos' / (row['id'] + '.jpg'))
                    row['thumbnail'] = str(DATA / 'photos' / (row['id'] + '.thumb.jpg'))
                con.executemany("UPDATE photos SET status='processing' WHERE id=?", [(r['id'],) for r in rows])
            try:
                if engine is None:
                    engine = FaceEngine()
                process_v3_batch(_sys.modules[__name__], rows, engine)
            except Exception:
                log.exception("V3 batch failed")
                with db() as con:
                    con.executemany("UPDATE photos SET status='error',error='Не удалось обработать снимок. Повторите обработку.' WHERE id=? AND status='processing'", [(r['id'],) for r in rows])


@asynccontextmanager
async def lifespan(app):
    init_db()
    app.state.token = secrets.token_urlsafe(32)
    executor.submit(process_pending)
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def local_session(request: Request, call_next):
    # A page-generated local session plus same-origin checks protect mutations.
    if request.url.path.startswith("/api/") or request.url.path.startswith("/media/"):
        if request.cookies.get("album_session") != getattr(app.state, "token", None):
            return JSONResponse({"detail": "Откройте главную страницу приложения"}, status_code=401)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "")
        if origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    # Thumbnails are immutable by photo id; allow browser cache to avoid UI flicker.
    if request.url.path.startswith("/media/"):
        response.headers["Cache-Control"] = "private, max-age=86400, immutable"
    else:
        response.headers["Cache-Control"] = "no-store"
    if request.url.path in {"/", "/v2", "/v2/", "/sorting-lab"}:
        response.set_cookie("album_session", app.state.token, httponly=True, samesite="strict")
    return response


class OrderInput(BaseModel):
    school: str = Field(min_length=1, max_length=100)
    class_name: str = Field(min_length=1, max_length=30)
    copies: int = Field(ge=1, le=1000)
    price: int = Field(default=0, ge=0, le=1_000_000)
    shoot_date: str = ""


@app.get("/api/status")
def system_status():
    return {"models_ready": all((ROOT / "models" / f).is_file() for f in ["yunet.onnx", "sface.onnx"]), "local": True, "analysis_version": "v3"}


@app.get("/api/orders")
def list_orders():
    with db() as con:
        rows = con.execute("""SELECT o.*,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id) AS photo_count,
          (SELECT COUNT(*) FROM persons p WHERE p.order_id=o.id) AS person_count,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status IN ('pending','processing')) AS pending,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status NOT IN ('pending','processing') AND NOT EXISTS (SELECT 1 FROM shoots s WHERE s.id=p.shoot_id AND s.kind='general') AND (p.status!='ready' OR p.uncertain=1 OR p.person_id IS NULL)) AS review_count,
          COALESCE((SELECT photo_id FROM order_covers WHERE order_id=o.id), (SELECT id FROM photos p WHERE p.order_id=o.id ORDER BY created_at,id LIMIT 1)) AS cover_id
          FROM orders o ORDER BY created_at DESC""").fetchall()
        from .client_portal import progress_by_order
        progress = progress_by_order(con)
        return [dict(row, client_progress=progress[row["id"]]) for row in rows]


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderInput):
    values = payload.model_dump()
    values["school"], values["class_name"] = values["school"].strip(), values["class_name"].strip()
    if not values["school"] or not values["class_name"]:
        raise HTTPException(422, "Укажите школу и класс")
    if values["shoot_date"]:
        try:
            datetime.strptime(values["shoot_date"], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, "Некорректная дата съёмки")
    order_id = uid()
    with db() as con:
        con.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)", (order_id, values["school"], values["class_name"], values["copies"], values["price"], values["shoot_date"], "scheduled" if values["shoot_date"] else "planned", now()))
    return {"id": order_id}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    with db() as con:
        order = dict(require_order(con, order_id))
        order["photos"] = [dict(row) for row in con.execute("SELECT p.id,p.shoot_id,s.kind AS shoot_type,p.filename,p.status,p.person_id,p.uncertain,p.error,a.algorithm AS analysis_version,a.source AS assignment_source FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id LEFT JOIN photo_analysis a ON a.photo_id=p.id WHERE p.order_id=? ORDER BY p.created_at,p.id", (order_id,))]
        order["shoots"] = [dict(r) for r in con.execute("SELECT id,title,kind FROM shoots WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        order["persons"] = [dict(row) for row in con.execute("SELECT id,name FROM persons WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        from .client_portal import progress_by_order
        order["client_progress"] = progress_by_order(con, order_id)[order_id]
        order["max_photos"] = MAX_PHOTOS
        order["cover_id"] = next((r[0] for r in con.execute("SELECT photo_id FROM order_covers WHERE order_id=?", (order_id,))), None)
        durations = [r[0] for r in con.execute("SELECT seconds FROM processing_times ORDER BY finished_at DESC LIMIT 40")]
        pending = con.execute("SELECT COUNT(*) FROM photos WHERE order_id=? AND status IN ('pending','processing')", (order_id,)).fetchone()[0]
        # One shared worker: include queued work ahead of the last photo in this order.
        last = con.execute("SELECT created_at,id FROM photos WHERE order_id=? AND status IN ('pending','processing') ORDER BY created_at DESC,id DESC LIMIT 1", (order_id,)).fetchone()
        queue = con.execute("SELECT COUNT(*) FROM photos WHERE status IN ('pending','processing') AND (created_at,id)<=(?,?)", tuple(last)).fetchone()[0] if last else 0
        order["processing"] = {"algorithm": "v3", "remaining": pending, "eta_seconds": round(sum(durations)/len(durations)*queue) if len(durations)>=3 and pending else None}
        return order


class ShootInput(BaseModel):
    kind: Literal['portrait', 'general']
    title: str = Field(min_length=1, max_length=100)


@app.post('/api/orders/{order_id}/shoots', status_code=201)
def create_shoot(order_id: str, payload: ShootInput):
    title = payload.title.strip()
    if not title:
        raise HTTPException(422, 'Укажите название съёмки')
    with db() as con:
        require_order(con, order_id)
        shoot_id = shoots.create(con, order_id, payload.kind, title)
    return {'id': shoot_id, 'title': title, 'kind': payload.kind}


@app.post("/api/orders/{order_id}/photos", status_code=201)
async def upload_photo(order_id: str, request: Request, filename: str, shoot_id: str | None = None):
    if len(filename) > 240 or not filename.strip():
        raise HTTPException(422, "Некорректное имя файла")
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_order(con, order_id)
        if shoot_id is None:
            shoot_id = shoots.default_portrait(con, order_id)
        shoot = con.execute('SELECT * FROM shoots WHERE id=? AND order_id=?', (shoot_id, order_id)).fetchone()
        if not shoot:
            raise HTTPException(404, "Съёмка не найдена в заказе")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "Файл больше 30 МБ")
    payload = bytes(body)
    sha = hashlib.sha256(payload).hexdigest()
    with upload_lock:
        with db() as con:
            existing = con.execute("SELECT id,shoot_id FROM photos WHERE order_id=? AND sha=?", (order_id, sha)).fetchone()
            if existing:
                if existing['shoot_id'] != shoot_id:
                    raise HTTPException(409, "Эта фотография уже загружена в другую съёмку заказа")
                return {"id": existing["id"], "duplicate": True}
            count = con.execute("SELECT COUNT(*) FROM photos WHERE order_id=?", (order_id,)).fetchone()[0]
            if count >= MAX_PHOTOS:
                raise HTTPException(409, f"Лимит заказа — {MAX_PHOTOS} фотографий")
    photo_id = uid()
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(image_executor, prepare_photo_files, payload, photo_id)
    except HTTPException:
        raise
    with upload_lock:
        with db() as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
                for suffix in [".original", ".jpg", ".thumb.jpg"]:
                    (DATA / "photos" / (photo_id + suffix)).unlink(missing_ok=True)
                raise HTTPException(404, "Заказ удалён")
            existing = con.execute("SELECT id,shoot_id FROM photos WHERE order_id=? AND sha=?", (order_id, sha)).fetchone()
            if existing:
                for path in [DATA / "photos" / (photo_id + suffix) for suffix in [".original", ".jpg", ".thumb.jpg"]]:
                    path.unlink(missing_ok=True)
                if existing['shoot_id'] != shoot_id:
                    raise HTTPException(409, "Эта фотография уже загружена в другую съёмку заказа")
                return {"id": existing["id"], "duplicate": True}
            count = con.execute("SELECT COUNT(*) FROM photos WHERE order_id=?", (order_id,)).fetchone()[0]
            if count >= MAX_PHOTOS:
                for path in [DATA / "photos" / (photo_id + suffix) for suffix in [".original", ".jpg", ".thumb.jpg"]]:
                    path.unlink(missing_ok=True)
                raise HTTPException(409, f"Лимит заказа — {MAX_PHOTOS} фотографий")
            con.execute(
                "INSERT INTO photos (id,order_id,filename,sha,status,created_at,shoot_id) VALUES (?,?,?,?,?,?,?)",
                (photo_id, order_id, Path(filename).name, sha, "pending" if shoot["kind"] == "portrait" else "ready", now(), shoot_id),
            )
            con.execute("UPDATE orders SET stage='upload' WHERE id=?", (order_id,))
    executor.submit(process_pending)
    return {"id": photo_id, "duplicate": False}


@app.get("/media/{photo_id}/{variant}")
def media(photo_id: str, variant: str):
    if variant not in {"thumb", "full"}:
        raise HTTPException(404)
    with db() as con:
        if not con.execute("SELECT 1 FROM photos WHERE id=?", (photo_id,)).fetchone():
            raise HTTPException(404)
    path = DATA / "photos" / (photo_id + (".thumb.jpg" if variant == "thumb" else ".jpg"))
    return FileResponse(path, media_type="image/jpeg")


class PersonInput(BaseModel):
    name: str = Field(max_length=100)


@app.patch("/api/orders/{order_id}/persons/{person_id}")
def rename_person(order_id: str, person_id: str, payload: PersonInput):
    with db() as con:
        result = con.execute("UPDATE persons SET name=? WHERE id=? AND order_id=?", (payload.name.strip(), person_id, order_id))
        if result.rowcount != 1:
            raise HTTPException(404, "Персона не найдена")
    return {"ok": True}


class MoveInput(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=3000)
    person_id: str | None = None


@app.post("/api/orders/{order_id}/move")
def move_photos(order_id: str, payload: MoveInput):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_order(con, order_id)
        ids = list(set(payload.photo_ids))
        placeholders = ",".join("?" for _ in ids)
        rows = con.execute(f"SELECT id,status FROM photos WHERE order_id=? AND id IN ({placeholders})", [order_id, *ids]).fetchall()
        if len(rows) != len(ids):
            raise HTTPException(404, "Фотографии не найдены в заказе")
        if any(row["status"] in {"pending", "processing"} for row in rows):
            raise HTTPException(409, "Дождитесь завершения обработки")
        if con.execute(f"SELECT 1 FROM photos p JOIN shoots s ON s.id=p.shoot_id WHERE p.id IN ({placeholders}) AND s.kind='general'", ids).fetchone():
            raise HTTPException(409, "Общие съёмки не распределяются по персонам")
        person_id = payload.person_id
        if person_id:
            if not con.execute("SELECT 1 FROM persons WHERE id=? AND order_id=?", (person_id, order_id)).fetchone():
                raise HTTPException(404, "Персона не найдена в заказе")
        else:
            person_id = uid()
            con.execute("INSERT INTO persons VALUES (?,?,?,?)", (person_id, order_id, "", now()))
        con.execute(f"UPDATE photos SET person_id=?,status='ready',uncertain=0,error='' WHERE order_id=? AND id IN ({placeholders})", [person_id, order_id, *ids])
        con.execute(f"UPDATE photo_analysis SET source='manual',anchors='[]' WHERE photo_id IN ({placeholders})", ids)
        con.execute("DELETE FROM persons WHERE order_id=? AND id NOT IN (SELECT person_id FROM photos WHERE person_id IS NOT NULL)", (order_id,))
    return {"person_id": person_id}


@app.post("/api/orders/{order_id}/retry")
def retry(order_id: str, shoot_id: str | None = None):
    with db() as con:
        require_order(con, order_id)
        if shoot_id and not con.execute('SELECT 1 FROM shoots WHERE id=? AND order_id=?', (shoot_id, order_id)).fetchone():
            raise HTTPException(404, 'Съёмка не найдена в заказе')
        con.execute("UPDATE photos SET status='pending',error='' WHERE order_id=? AND status='error' AND (? IS NULL OR shoot_id=?)", (order_id, shoot_id, shoot_id))
    executor.submit(process_pending)
    return {"ok": True}



class PhotoIds(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=3000)



@app.post("/api/orders/{order_id}/person-suggestions")
def person_suggestions(order_id: str, payload: PhotoIds):
    from .person_suggestions import suggestions
    with db() as con:
        require_order(con, order_id)
        rows = [dict(r) for r in con.execute("SELECT id,shoot_id,filename,status,person_id,embedding,uncertain FROM photos WHERE order_id=?", (order_id,))]
    ids = set(payload.photo_ids)
    if not ids.issubset({p['id'] for p in rows}):
        raise HTTPException(404, "Фотографии не найдены в заказе")
    if any(p['status'] in {'pending','processing'} for p in rows if p['id'] in ids):
        raise HTTPException(409, "Дождитесь завершения обработки")
    return {"photos": suggestions(rows, ids), "score_kind": "cosine_similarity",
            "note": "Сходство и порядок кадров — подсказки, а не подтверждение личности."}


def remove_photo_rows(con, order_id, ids):
    placeholders = ",".join("?" for _ in ids)
    con.execute(f"DELETE FROM order_covers WHERE photo_id IN ({placeholders})", ids)
    con.execute(f"DELETE FROM processing_times WHERE photo_id IN ({placeholders})", ids)
    con.execute(f"DELETE FROM photos WHERE order_id=? AND id IN ({placeholders})", [order_id, *ids])
    con.execute("DELETE FROM persons WHERE order_id=? AND id NOT IN (SELECT person_id FROM photos WHERE person_id IS NOT NULL)", (order_id,))


def remove_photo_files(ids):
    for photo_id in ids:
        for suffix in [".original", ".jpg", ".thumb.jpg"]:
            (DATA / "photos" / (photo_id + suffix)).unlink(missing_ok=True)


@app.post("/api/orders/{order_id}/delete-photos")
def delete_photos(order_id: str, payload: PhotoIds):
    ids = list(set(payload.photo_ids))
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_order(con, order_id)
        marks = ",".join("?" for _ in ids)
        found = con.execute(f"SELECT id FROM photos WHERE order_id=? AND id IN ({marks})", [order_id, *ids]).fetchall()
        if len(found) != len(ids):
            raise HTTPException(404, "Фотографии не найдены в заказе")
        remove_photo_rows(con, order_id, ids)
    remove_photo_files(ids)
    return {"deleted": len(ids)}


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str):
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_order(con, order_id)
        ids = [r[0] for r in con.execute("SELECT id FROM photos WHERE order_id=?", (order_id,))]
        if ids:
            remove_photo_rows(con, order_id, ids)
        con.execute("DELETE FROM persons WHERE order_id=?", (order_id,))
        con.execute("DELETE FROM order_covers WHERE order_id=?", (order_id,))
        con.execute("DELETE FROM shoots WHERE order_id=?", (order_id,))
        con.execute("DELETE FROM orders WHERE id=?", (order_id,))
    remove_photo_files(ids)
    return {"ok": True}


@app.put("/api/orders/{order_id}/cover")
def set_cover(order_id: str, payload: PhotoIds):
    photo_id = payload.photo_ids[0]
    with db() as con:
        require_order(con, order_id)
        if not con.execute("SELECT 1 FROM photos WHERE id=? AND order_id=?", (photo_id, order_id)).fetchone():
            raise HTTPException(404, "Фотография не найдена в заказе")
        con.execute("INSERT OR REPLACE INTO order_covers VALUES (?,?)", (order_id, photo_id))
    return {"ok": True}


class ConfirmPhotos(PhotoIds):
    expected_persons: dict[str, str] | None = None


@app.post("/api/orders/{order_id}/confirm-photos")
def confirm_photos(order_id: str, payload: ConfirmPhotos):
    ids = list(set(payload.photo_ids))
    marks = ",".join("?" for _ in ids)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_order(con, order_id)
        rows = con.execute(f"SELECT id,status,person_id FROM photos WHERE order_id=? AND id IN ({marks})", [order_id, *ids]).fetchall()
        if len(rows) != len(ids) or any(r["status"] != "ready" or not r["person_id"] for r in rows):
            raise HTTPException(409, "Сначала обработайте фотографии и назначьте им персону")
        expected = getattr(payload, 'expected_persons', None)
        if expected is not None and (set(expected) != set(ids) or any(expected.get(r['id']) != r['person_id'] for r in rows)):
            raise HTTPException(409, "Назначения изменились. Обновите фотографии и проверьте персоны ещё раз")
        con.execute(f"UPDATE photos SET uncertain=0 WHERE order_id=? AND id IN ({marks})", [order_id, *ids])
    return {"ok": True}


@app.get("/v2")
@app.get("/v2/")
def home_v2():
    return FileResponse(ROOT / "web/v2.html")

@app.get("/")
def home():
    return FileResponse(ROOT / "web/index.html")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


# Experimental runs have separate outputs and never update production groups.
import sys as _sys
from .sorting_lab import install as _install_sorting_lab
_install_sorting_lab(app, _sys.modules[__name__])

from .client_portal import install as _install_client_portal
_install_client_portal(app, _sys.modules[__name__])
