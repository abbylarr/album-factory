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

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .faces import FaceEngine, choose_person

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("ALBUM_DATA_DIR", ROOT / "data"))
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000
STAGES = {"planned", "scheduled", "upload", "layout"}
executor = ThreadPoolExecutor(max_workers=1)
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
        con.execute("UPDATE photos SET status='pending' WHERE status='processing'")


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


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
                row = con.execute("SELECT * FROM photos WHERE status='pending' ORDER BY created_at,id LIMIT 1").fetchone()
                if row is None:
                    return
                con.execute("UPDATE photos SET status='processing' WHERE id=?", (row["id"],))
            try:
                if engine is None:
                    engine = FaceEngine()
                with Image.open(DATA / "photos" / (row["id"] + ".jpg")) as image:
                    pixels = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR)
                status, vector = engine.extract(pixels)
                with db() as con:
                    # Serialize assignment with manual moves and merges.
                    con.execute("BEGIN IMMEDIATE")
                    if vector is not None:
                        groups = {}
                        for existing in con.execute("SELECT person_id,embedding FROM photos WHERE order_id=? AND person_id IS NOT NULL AND embedding IS NOT NULL", (row["order_id"],)):
                            groups.setdefault(existing["person_id"], []).append(json.loads(existing["embedding"]))
                        person_id, uncertain = choose_person(vector, groups)
                        if person_id is None:
                            person_id = uid()
                            con.execute("INSERT INTO persons VALUES (?,?,?,?)", (person_id, row["order_id"], "", now()))
                        con.execute("UPDATE photos SET status=?,person_id=?,embedding=?,uncertain=?,error='' WHERE id=?",
                                    (status, person_id, json.dumps(vector), int(uncertain), row["id"]))
                    else:
                        con.execute("UPDATE photos SET status=?,error='' WHERE id=?", (status, row["id"]))
            except Exception:
                log.exception("Photo processing failed: %s", row["id"])
                with db() as con:
                    con.execute("UPDATE photos SET status='error',error=? WHERE id=?",
                                ("Не удалось обработать снимок. Проверьте модели и повторите.", row["id"]))


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
    if request.url.path == "/":
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
    return {"models_ready": all((ROOT / "models" / f).is_file() for f in ["yunet.onnx", "sface.onnx"]), "local": True}


@app.get("/api/orders")
def list_orders():
    with db() as con:
        rows = con.execute("""SELECT o.*,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id) AS photo_count,
          (SELECT COUNT(*) FROM persons p WHERE p.order_id=o.id) AS person_count,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status IN ('pending','processing')) AS pending
          FROM orders o ORDER BY created_at DESC""").fetchall()
        return [dict(row) for row in rows]


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
        order["photos"] = [dict(row) for row in con.execute("SELECT id,filename,status,person_id,uncertain,error FROM photos WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        order["persons"] = [dict(row) for row in con.execute("SELECT id,name FROM persons WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        return order


@app.post("/api/orders/{order_id}/photos", status_code=201)
async def upload_photo(order_id: str, request: Request, filename: str):
    if len(filename) > 240 or not filename.strip():
        raise HTTPException(422, "Некорректное имя файла")
    with db() as con:
        require_order(con, order_id)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise HTTPException(413, "Файл больше 30 МБ")
    sha = hashlib.sha256(body).hexdigest()
    try:
        with Image.open(BytesIO(body)) as image:
            # .jpg/.jpeg → JPEG; many camera JPGs (Sony etc.) are reported as MPO.
            if image.format not in {"JPEG", "PNG", "MPO"}:
                raise HTTPException(415, "Поддерживаются JPG, JPEG и PNG")
            if image.width * image.height > MAX_PIXELS:
                raise HTTPException(413, "Изображение больше 50 мегапикселей")
            original = ImageOps.exif_transpose(image).convert("RGB")
            original.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(415, "Не удалось прочитать изображение")
    photo_id = uid()
    with upload_lock:
        with db() as con:
            existing = con.execute("SELECT id FROM photos WHERE order_id=? AND sha=?", (order_id, sha)).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            count = con.execute("SELECT COUNT(*) FROM photos WHERE order_id=?", (order_id,)).fetchone()[0]
            if count >= 1000:
                raise HTTPException(409, "Лимит заказа — 1000 фотографий")
            # Keep uploaded originals byte-for-byte; normalized JPEGs are derivatives.
            paths = [DATA / "photos" / (photo_id + suffix) for suffix in [".original", ".jpg", ".thumb.jpg"]]
            try:
                paths[0].write_bytes(body)
                original.save(paths[1], "JPEG", quality=95)
                original.thumbnail((480, 640))
                original.save(paths[2], "JPEG", quality=85)
                con.execute("INSERT INTO photos (id,order_id,filename,sha,status,created_at) VALUES (?,?,?,?,?,?)", (photo_id, order_id, Path(filename).name, sha, "pending", now()))
                con.execute("UPDATE orders SET stage='upload' WHERE id=?", (order_id,))
            except Exception:
                for path in paths:
                    path.unlink(missing_ok=True)
                raise
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
    photo_ids: list[str] = Field(min_length=1, max_length=1000)
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
        person_id = payload.person_id
        if person_id:
            if not con.execute("SELECT 1 FROM persons WHERE id=? AND order_id=?", (person_id, order_id)).fetchone():
                raise HTTPException(404, "Персона не найдена в заказе")
        else:
            person_id = uid()
            con.execute("INSERT INTO persons VALUES (?,?,?,?)", (person_id, order_id, "", now()))
        con.execute(f"UPDATE photos SET person_id=?,status='ready',uncertain=0,error='' WHERE order_id=? AND id IN ({placeholders})", [person_id, order_id, *ids])
        con.execute("DELETE FROM persons WHERE order_id=? AND id NOT IN (SELECT person_id FROM photos WHERE person_id IS NOT NULL)", (order_id,))
    return {"person_id": person_id}


@app.post("/api/orders/{order_id}/retry")
def retry(order_id: str):
    with db() as con:
        require_order(con, order_id)
        con.execute("UPDATE photos SET status='pending',error='' WHERE order_id=? AND status='error'", (order_id,))
    executor.submit(process_pending)
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(ROOT / "web/index.html")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")
