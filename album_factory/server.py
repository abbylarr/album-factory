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
from . import shoots, order_stages
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .faces import FaceEngine
from .production_v3 import process_batch as process_v3_batch

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("ALBUM_DATA_DIR", ROOT / "data"))
MAX_BYTES = 30 * 1024 * 1024
MAX_PIXELS = 50_000_000
MAX_PHOTOS = 3000
executor = ThreadPoolExecutor(max_workers=1)
image_executor = ThreadPoolExecutor(max_workers=4)
worker_lock = threading.Lock()
upload_lock = threading.Lock()
engine = None
vision = None
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
        from .layout_workspace import init as init_layout_workspace
        init_layout_workspace(con)
        from .mvp import init as init_mvp
        init_mvp(con)
        from .school_catalog import init as init_school_catalog
        init_school_catalog(con)
        # Backfill fingerprints for portraits selected before upload history existed.
        for teacher in con.execute("""SELECT id,school_id,portrait_path FROM teachers WHERE portrait_path!=''
                AND id NOT IN (SELECT id FROM teacher_uploads)""").fetchall():
            original = (DATA / teacher["portrait_path"]).with_suffix('.original')
            if original.is_file():
                con.execute("INSERT OR IGNORE INTO teacher_uploads VALUES (?,?,?)",
                            (teacher["school_id"], hashlib.sha256(original.read_bytes()).hexdigest(), teacher["id"]))
        from .master_templates import init as init_masters
        init_masters(con)
        from .general_photos import init as init_general
        init_general(con)
        order_stages.migrate(con)
        if "master_template_id" not in {r[1] for r in con.execute("PRAGMA table_info(orders)")}:
            con.execute("ALTER TABLE orders ADD COLUMN master_template_id TEXT")
        if "graduation_year" not in {r[1] for r in con.execute("PRAGMA table_info(orders)")}:
            con.execute("ALTER TABLE orders ADD COLUMN graduation_year INTEGER")
        for row in con.execute("SELECT id, created_at FROM orders WHERE graduation_year IS NULL").fetchall():
            date = datetime.fromisoformat(row["created_at"])
            con.execute("UPDATE orders SET graduation_year=? WHERE id=?", (graduation_year_for(date), row["id"]))
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
    from . import mvp
    studio = mvp.studio_ctx.get()
    if studio is not None and con.execute(
            "SELECT 1 FROM order_membership WHERE order_id=? AND studio_id=?", (order_id, studio)).fetchone() is None:
        raise HTTPException(404, "Заказ не найден")
    return row


def general_vision():
    global vision
    if vision is None:
        from .vision import GeneralVision
        vision = GeneralVision(ROOT / "models")
    return vision


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
                for row in rows:
                    row['path'] = str(DATA / 'photos' / (row['id'] + '.jpg'))
                    row['thumbnail'] = str(DATA / 'photos' / (row['id'] + '.thumb.jpg'))
                    row['original'] = str(DATA / 'photos' / (row['id'] + '.original'))
                con.executemany("UPDATE photos SET status='processing' WHERE id=?", [(r['id'],) for r in rows])
            if shoot and shoot['kind'] == 'general':
                try:
                    from .general_photos import process_batch as process_general_batch
                    process_general_batch(_sys.modules[__name__], rows, general_vision())
                except Exception:
                    log.exception("General batch failed")
                    with db() as con:
                        con.executemany("UPDATE photos SET status='error',error='Не удалось проанализировать снимок. Повторите обработку.' WHERE id=? AND status='processing'", [(r['id'],) for r in rows])
                continue
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
    from .school_catalog import group_pending
    executor.submit(group_pending, _sys.modules[__name__])
    yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])


@app.middleware("http")
async def local_session(request: Request, call_next):
    # A page-generated local session plus same-origin checks protect mutations.
    from . import mvp
    path = request.url.path
    token = request.cookies.get("album_session")
    studio = None
    open_api = path in {"/api/login", "/api/register"}
    if (path.startswith("/api/") or path.startswith("/media/")) and not open_api:
        with db() as con:
            studio = mvp.studio_for_cookie(con, token, getattr(app.state, "token", None))
        if studio is None:
            return JSONResponse({"detail": "Откройте главную страницу приложения"}, status_code=401)
    ctx = mvp.studio_ctx.set(studio)
    try:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin", "")
            if origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Недопустимый источник запроса"}, status_code=403)
        response = await call_next(request)
    finally:
        mvp.studio_ctx.reset(ctx)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    # Thumbnails are immutable by photo id; allow browser cache to avoid UI flicker.
    if request.url.path.startswith("/media/"):
        response.headers["Cache-Control"] = "private, max-age=86400, immutable"
    else:
        response.headers["Cache-Control"] = "no-store"
    if path in {"/", "/v2", "/v2/"}:
        with db() as con:
            page_studio = mvp.studio_for_cookie(con, token, getattr(app.state, "token", None))
        if page_studio is None or token == getattr(app.state, "token", None):
            response.set_cookie("album_session", app.state.token, httponly=True, samesite="strict", path="/")
    return response


def graduation_year_for(date):
    return date.year + (1 if date.month >= 9 else 0)


# School and class are left out once the order is printed; the customer can still be corrected then.
class OrderEditInput(BaseModel):
    school: str = Field(default="", max_length=300)
    school_city: str = Field(default="", max_length=100)
    school_id: str | None = None
    class_name: str | None = Field(default=None, min_length=1, max_length=30)
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    confirm_school_change: bool = False
    customer_name: str | None = Field(default=None, max_length=100)
    customer_contact: str | None = Field(default=None, max_length=40)
    copies: int | None = Field(default=None, ge=1, le=1000)


class OrderInput(BaseModel):
    master_template_id: str | None = None
    graduation_year: int | None = Field(default=None, ge=2000, le=2100)
    school: str = Field(default="", max_length=300)
    school_city: str = Field(default="", max_length=100)
    class_name: str = Field(min_length=1, max_length=30)
    copies: int = Field(ge=1, le=1000)
    price: int = Field(default=0, ge=0, le=1_000_000)
    shoot_date: str = ""
    customer_name: str = Field(default="", max_length=100)
    customer_contact: str = Field(default="", max_length=40)
    offer_id: str | None = None
    school_id: str | None = None
    student_count: int | None = Field(default=None, ge=1, le=1000)


@app.get("/api/status")
def system_status():
    from .general_meta import CONFIG
    return {"models_ready": all((ROOT / "models" / f).is_file() for f in ["yunet.onnx", "sface.onnx"]), "local": True, "analysis_version": "v3",
            "general_analysis": {"version": CONFIG["version"], "features": general_vision().features}}


# The client approved the layout that is currently published.
APPROVED = """EXISTS (SELECT 1 FROM approvals a JOIN publications pub ON pub.order_id=a.order_id
          WHERE a.order_id=o.id AND a.approved_at>=pub.published_at)"""


@app.get("/api/orders")
def list_orders():
    with db() as con:
        from . import mvp
        studio = mvp.studio_ctx.get()
        where, args = "", ()
        if studio is not None:
            where = "WHERE EXISTS (SELECT 1 FROM order_membership m WHERE m.order_id=o.id AND m.studio_id=?)"
            args = (studio,)
        rows = con.execute(f"""SELECT o.*,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id) AS photo_count,
          (SELECT COUNT(*) FROM persons p WHERE p.order_id=o.id) AS person_count,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status IN ('pending','processing')) AS pending,
          (SELECT COUNT(*) FROM photos p WHERE p.order_id=o.id AND p.status NOT IN ('pending','processing') AND NOT EXISTS (SELECT 1 FROM shoots s WHERE s.id=p.shoot_id AND s.kind='general') AND (p.status!='ready' OR p.uncertain=1 OR p.person_id IS NULL)) AS review_count,
          COALESCE((SELECT photo_id FROM order_covers WHERE order_id=o.id), (SELECT id FROM photos p WHERE p.order_id=o.id ORDER BY created_at,id LIMIT 1)) AS cover_id,
          (SELECT json_extract(l.document, '$.revision') FROM order_layouts l WHERE l.order_id=o.id) AS layout_revision,
          COALESCE((SELECT customer_name FROM order_terms WHERE order_id=o.id), '') AS customer_name,
          COALESCE((SELECT customer_contact FROM order_terms WHERE order_id=o.id), '') AS customer_contact,
          (SELECT school_id FROM order_terms WHERE order_id=o.id) AS school_id,
          {APPROVED} AS approved
          FROM orders o {where} ORDER BY created_at DESC""".replace("{APPROVED}", APPROVED), args).fetchall()
        from .client_portal import progress_by_order
        progress = progress_by_order(con)
        from .client_portal import open_counts
        fixes = open_counts(con)
        result = []
        for row in rows:
            result.append(dict(row, preview_photo_ids=order_preview_photos(con, row["id"], row["cover_id"]),
                               client_progress=progress[row["id"]], corrections_open=fixes.get(row["id"], 0)))
        return result


def order_preview_photos(con, order_id: str, cover_id: str | None) -> list[str]:
    """Choose a cover and then one ready portrait from each different person."""
    selected = []
    people = set()
    if cover_id:
        cover = con.execute(
            "SELECT id,person_id FROM photos WHERE id=? AND order_id=? AND status!='error'",
            (cover_id, order_id),
        ).fetchone()
        if cover:
            selected.append(cover["id"])
            if cover["person_id"]:
                people.add(cover["person_id"])

    distinct = con.execute("""SELECT id,person_id FROM (
          SELECT id,person_id,created_at,
                 ROW_NUMBER() OVER (PARTITION BY person_id ORDER BY created_at,id) AS person_rank
          FROM photos WHERE order_id=? AND person_id IS NOT NULL AND status='ready'
        ) WHERE person_rank=1 ORDER BY created_at,id LIMIT 3""", (order_id,))
    for photo in distinct:
        if photo["person_id"] not in people and photo["id"] not in selected:
            selected.append(photo["id"])
            people.add(photo["person_id"])
        if len(selected) == 3:
            return selected

    missing = 3 - len(selected)
    placeholders = ",".join("?" for _ in selected)
    extra = f" AND id NOT IN ({placeholders})" if selected else ""
    fallback = con.execute(
        f"SELECT id FROM photos WHERE order_id=? AND status!='error'{extra} ORDER BY created_at,id LIMIT ?",
        (order_id, *selected, missing),
    )
    return selected + [photo["id"] for photo in fallback]


def school_name(con, school_id):
    from . import mvp
    row = con.execute("SELECT name FROM schools WHERE id=? AND studio_id=?", (school_id, mvp.studio_ctx.get() or mvp.LOCAL)).fetchone()
    if row is None:
        raise HTTPException(404, "Школа не найдена")
    return row["name"]


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderInput):
    values = payload.model_dump()
    values["school"], values["class_name"] = values["school"].strip(), values["class_name"].strip()
    if not values["class_name"]:
        raise HTTPException(422, "Укажите класс")
    if values["shoot_date"]:
        try:
            datetime.strptime(values["shoot_date"], "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, "Некорректная дата съёмки")
    order_id = uid()
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        from .school_catalog import resolve_order_school
        values["school_id"], values["school"], values["school_city"] = resolve_order_school(
            con, values["school_id"], values["school"], values["school_city"], uid)
        created = now()
        con.execute("INSERT INTO orders (id,school,school_city,class_name,copies,price,shoot_date,stage,created_at,stage_at,graduation_year) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (order_id, values["school"], values["school_city"], values["class_name"], values["copies"], values["price"], values["shoot_date"], "new", created, created, values["graduation_year"] or graduation_year_for(datetime.fromisoformat(created))))
        from . import mvp
        mvp.attach_order(con, order_id, mvp.studio_ctx.get(), values)
        if values["master_template_id"]:
            from .master_templates import select_order_master
            select_order_master(con, order_id, values["master_template_id"])
    return {"id": order_id}


@app.patch("/api/orders/{order_id}")
def edit_order(order_id: str, payload: OrderEditInput):
    from .school_catalog import resolve_order_school, order_school_id, LOCKED_STAGES
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        order = require_order(con, order_id)
        if payload.customer_name is not None or payload.customer_contact is not None:
            con.execute("UPDATE order_terms SET customer_name=COALESCE(?,customer_name),customer_contact=COALESCE(?,customer_contact) WHERE order_id=?",
                        (payload.customer_name and payload.customer_name.strip(), payload.customer_contact and payload.customer_contact.strip(), order_id))
        if payload.copies is not None and payload.copies != order["copies"]:
            if order["stage"] in LOCKED_STAGES:
                raise HTTPException(409, "Заказ уже в печати или архиве. Тираж зафиксирован")
            # A new print run replaces the plan; a custom split that no longer adds up is proposed again from the students.
            con.execute("UPDATE orders SET copies=? WHERE id=?", (payload.copies, order_id))
            con.execute("""UPDATE order_terms SET planned_paid=?, current_paid=?,
                allocations_custom=CASE WHEN (SELECT COALESCE(SUM(paid),0) FROM allocations WHERE order_id=?)=? THEN allocations_custom ELSE 0 END
                WHERE order_id=?""", (payload.copies, payload.copies, order_id, payload.copies, order_id))
        if payload.class_name is None:
            return {"id": order_id}
        if order["stage"] in LOCKED_STAGES:
            raise HTTPException(409, "Заказ уже в печати или архиве. Данные школы и класса зафиксированы")
        old_school = order_school_id(con, order_id)
        school_id, name, city = resolve_order_school(con, payload.school_id if payload.school_id else (old_school if payload.school == order["school"] and (not payload.school_city or payload.school_city == order["school_city"]) else None), payload.school, payload.school_city, uid)
        if old_school and old_school != school_id:
            if not payload.confirm_school_change:
                raise HTTPException(409, "Смена школы сбросит состав учителей. Подтвердите смену школы")
            con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
            con.execute("DELETE FROM order_teacher_state WHERE order_id=?", (order_id,))
            con.execute("UPDATE teacher_photos SET order_id=NULL WHERE order_id=?", (order_id,))
        if not payload.class_name.strip():
            raise HTTPException(422, "Укажите класс")
        con.execute("UPDATE order_terms SET school_id=? WHERE order_id=?", (school_id, order_id))
        con.execute("UPDATE orders SET school=?,school_city=?,class_name=?,graduation_year=? WHERE id=?",
                    (name, city, payload.class_name.strip(), payload.graduation_year or order["graduation_year"], order_id))
    return {"id": order_id}


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    with db() as con:
        order = dict(require_order(con, order_id))
        terms = con.execute("""SELECT t.customer_name, t.customer_contact, t.school_id, s.city AS school_city
            FROM order_terms t LEFT JOIN schools s ON s.id=t.school_id WHERE t.order_id=?""", (order_id,)).fetchone()
        order["school_id"] = terms["school_id"] if terms else None
        order["customer_name"] = terms["customer_name"] if terms else ""
        order["customer_contact"] = terms["customer_contact"] if terms else ""
        order["approved"] = bool(con.execute(f"SELECT {APPROVED} FROM orders o WHERE o.id=?", (order_id,)).fetchone()[0])
        order["published"] = con.execute("SELECT 1 FROM publications WHERE order_id=?", (order_id,)).fetchone() is not None
        order["photos"] = [dict(row) for row in con.execute("SELECT p.id,p.shoot_id,s.kind AS shoot_type,p.filename,p.status,p.person_id,p.uncertain,p.error,a.algorithm AS analysis_version,a.source AS assignment_source FROM photos p LEFT JOIN shoots s ON s.id=p.shoot_id LEFT JOIN photo_analysis a ON a.photo_id=p.id WHERE p.order_id=? ORDER BY p.created_at,p.id", (order_id,))]
        order["shoots"] = [dict(r) for r in con.execute("SELECT id,title,kind,shot_on FROM shoots WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        order["persons"] = [dict(row) for row in con.execute("SELECT id,name FROM persons WHERE order_id=? ORDER BY created_at,id", (order_id,))]
        from .client_portal import progress_by_order
        order["client_progress"] = progress_by_order(con, order_id)[order_id]
        from .client_portal import open_corrections
        order["corrections"] = open_corrections(con, order_id)
        order["corrections_open"] = len(order["corrections"])
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
    shot_on: str = ''


class ShootEdit(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    shot_on: str = ''


def clean_shoot(title, shot_on):
    title = title.strip()
    if not title:
        raise HTTPException(422, 'Укажите название съёмки')
    if shot_on:
        try:
            datetime.strptime(shot_on, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(422, 'Некорректная дата съёмки')
    return title, shot_on


def require_shoot(con, order_id, shoot_id):
    require_order(con, order_id)
    if not con.execute('SELECT 1 FROM shoots WHERE id=? AND order_id=?', (shoot_id, order_id)).fetchone():
        raise HTTPException(404, 'Съёмка не найдена в заказе')


@app.post('/api/orders/{order_id}/shoots', status_code=201)
def create_shoot(order_id: str, payload: ShootInput):
    title, shot_on = clean_shoot(payload.title, payload.shot_on)
    with db() as con:
        require_order(con, order_id)
        shoot_id = shoots.create(con, order_id, payload.kind, title, shot_on)
    return {'id': shoot_id, 'title': title, 'kind': payload.kind, 'shot_on': shot_on}


@app.patch('/api/orders/{order_id}/shoots/{shoot_id}')
def edit_shoot(order_id: str, shoot_id: str, payload: ShootEdit):
    title, shot_on = clean_shoot(payload.title, payload.shot_on)
    with db() as con:
        require_shoot(con, order_id, shoot_id)
        con.execute('UPDATE shoots SET title=?, shot_on=? WHERE id=?', (title, shot_on, shoot_id))
    return {'ok': True}


@app.delete('/api/orders/{order_id}/shoots/{shoot_id}')
def delete_shoot(order_id: str, shoot_id: str):
    """The whole folder: its photos, their files and analysis. Layout frames that used them become empty."""
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_shoot(con, order_id, shoot_id)
        ids = [r[0] for r in con.execute("SELECT id FROM photos WHERE shoot_id=?", (shoot_id,))]
        if con.execute("SELECT 1 FROM photos WHERE shoot_id=? AND status='processing'", (shoot_id,)).fetchone():
            raise HTTPException(409, "Дождитесь завершения обработки")
        if ids:
            remove_photo_rows(con, order_id, ids)
        con.execute("DELETE FROM shoots WHERE id=?", (shoot_id,))
    remove_photo_files(ids)
    return {"deleted": len(ids)}


class ShootPhotos(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=3000)


@app.post('/api/orders/{order_id}/shoots/{shoot_id}/move-photos')
def move_to_shoot(order_id: str, shoot_id: str, payload: ShootPhotos):
    """Frames that are not portraits leave the person groups and are analysed again as general photos."""
    ids = list(set(payload.photo_ids))
    marks = ",".join("?" for _ in ids)
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        require_shoot(con, order_id, shoot_id)
        if con.execute('SELECT kind FROM shoots WHERE id=?', (shoot_id,)).fetchone()['kind'] != 'general':
            raise HTTPException(409, 'Переносить можно только в общую съёмку')
        rows = con.execute(f"SELECT id,status,shoot_id FROM photos WHERE order_id=? AND id IN ({marks})", [order_id, *ids]).fetchall()
        if len(rows) != len(ids):
            raise HTTPException(404, "Фотографии не найдены в заказе")
        if any(r["status"] in {"pending", "processing"} for r in rows):
            raise HTTPException(409, "Дождитесь завершения обработки")
        if any(r["shoot_id"] == shoot_id for r in rows):
            raise HTTPException(409, "Фотографии уже в этой съёмке")
        con.execute(f"UPDATE photos SET shoot_id=?,person_id=NULL,uncertain=0,embedding=NULL,status='pending',error='' WHERE order_id=? AND id IN ({marks})", [shoot_id, order_id, *ids])
        con.execute(f"DELETE FROM photo_analysis WHERE photo_id IN ({marks})", ids)
        con.execute("DELETE FROM persons WHERE order_id=? AND id NOT IN (SELECT person_id FROM photos WHERE person_id IS NOT NULL)", (order_id,))
    executor.submit(process_pending)
    return {"moved": len(ids)}


class StageInput(BaseModel):
    stage: Literal[order_stages.STAGES]


@app.post('/api/orders/{order_id}/stage')
def move_stage(order_id: str, payload: StageInput):
    with db() as con:
        require_order(con, order_id)
        order_stages.move(con, order_id, payload.stage)
    return {'stage': payload.stage}


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
                (photo_id, order_id, Path(filename).name, sha, "pending", now(), shoot_id),
            )
            order_stages.advance(con, order_id, 'photos')
    executor.submit(process_pending)
    return {"id": photo_id, "duplicate": False}


@app.get("/media/{photo_id}/{variant}")
def media(photo_id: str, variant: str):
    if variant not in {"thumb", "full"}:
        raise HTTPException(404)
    with db() as con:
        from . import mvp
        if not mvp.photo_visible(con, photo_id):
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
        for face in (DATA / "photos" / "faces").glob(photo_id + "-*.jpg"):
            face.unlink(missing_ok=True)


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
        from . import mvp
        mvp.forget(con, order_id)
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
    return FileResponse(ROOT / "web/v2.html")


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


import sys as _sys
from .client_portal import install as _install_client_portal
_install_client_portal(app, _sys.modules[__name__])

from .layout_workspace import install as _install_layout_workspace
_install_layout_workspace(app, _sys.modules[__name__])

from .mvp import install as _install_mvp
_install_mvp(app, _sys.modules[__name__])

from .school_catalog import install as _install_school_catalog
_install_school_catalog(app, _sys.modules[__name__])

from .master_templates import install as _install_masters
_install_masters(app, _sys.modules[__name__])

from .general_photos import install as _install_general
_install_general(app, _sys.modules[__name__])

@app.get('/master-editor.html')
def master_editor_entry():
    from fastapi.responses import RedirectResponse
    return RedirectResponse('/static/master-editor.html?new=1')
