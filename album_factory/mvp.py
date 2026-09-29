"""Order terms, studio isolation, pins, allocation and approval for the local MVP."""
from __future__ import annotations

import contextvars
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import jobs, order_stages
from .layout_engine import LayoutError, capacity_matrix, field_limits, validate_edition
from .storage import retention_deadline

LOCAL = "local"
studio_ctx = contextvars.ContextVar("album_studio", default=None)
PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS studios (id TEXT PRIMARY KEY, name TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS photographers (
      id TEXT PRIMARY KEY, studio_id TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
      password_hash TEXT NOT NULL, salt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS auth_sessions (
      token_hash TEXT PRIMARY KEY, studio_id TEXT NOT NULL, photographer_id TEXT NOT NULL,
      expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS profiles (
      studio_id TEXT PRIMARY KEY, teacher_gift INTEGER NOT NULL DEFAULT 1,
      delivery_modes TEXT NOT NULL DEFAULT 'both');
    CREATE TABLE IF NOT EXISTS schools (
      id TEXT PRIMARY KEY, studio_id TEXT NOT NULL, name TEXT NOT NULL, address TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS teachers (
      id TEXT PRIMARY KEY, school_id TEXT NOT NULL, first_name TEXT NOT NULL DEFAULT '',
      last_name TEXT NOT NULL DEFAULT '', defined INTEGER NOT NULL DEFAULT 0,
      portrait_path TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS editions (
      id TEXT PRIMARY KEY, document TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS offers (
      id TEXT PRIMARY KEY, studio_id TEXT NOT NULL, edition_id TEXT NOT NULL,
      title TEXT NOT NULL, price INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS order_membership (order_id TEXT PRIMARY KEY, studio_id TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS order_terms (
      order_id TEXT PRIMARY KEY, customer_name TEXT NOT NULL DEFAULT '',
      customer_contact TEXT NOT NULL DEFAULT '', school_id TEXT, offer_id TEXT,
      offer_title TEXT NOT NULL DEFAULT '', offer_price INTEGER NOT NULL DEFAULT 0,
      edition_id TEXT, edition_json TEXT NOT NULL DEFAULT '', planned_paid INTEGER NOT NULL,
      current_paid INTEGER NOT NULL, gift_copies INTEGER NOT NULL DEFAULT 0,
      delivery_modes TEXT NOT NULL DEFAULT 'both', student_count INTEGER,
      workflow TEXT NOT NULL DEFAULT 'materials', allocations_custom INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS order_pins (
      order_id TEXT PRIMARY KEY, entry_hash TEXT NOT NULL, entry_salt TEXT NOT NULL,
      manage_hash TEXT NOT NULL, manage_salt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS order_codes (
      order_id TEXT PRIMARY KEY, entry_pin TEXT NOT NULL, manage_pin TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS message_templates (
      studio_id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (studio_id, kind));
    CREATE TABLE IF NOT EXISTS pin_attempts (
      order_id TEXT NOT NULL, kind TEXT NOT NULL, fails INTEGER NOT NULL DEFAULT 0,
      locked_until TEXT NOT NULL DEFAULT '', PRIMARY KEY (order_id, kind));
    CREATE TABLE IF NOT EXISTS class_sessions (
      token_hash TEXT PRIMARY KEY, order_id TEXT NOT NULL, level TEXT NOT NULL, expires_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS selection_state (
      person_id TEXT PRIMARY KEY, photo_id TEXT NOT NULL, submitted INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS allocations (
      order_id TEXT NOT NULL, recipient_key TEXT NOT NULL, label TEXT NOT NULL,
      paid INTEGER NOT NULL, gift INTEGER NOT NULL, PRIMARY KEY (order_id, recipient_key));
    CREATE TABLE IF NOT EXISTS deliveries (
      order_id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT '', carrier TEXT NOT NULL DEFAULT '',
      address TEXT NOT NULL DEFAULT '', recipient TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS publications (
      order_id TEXT PRIMARY KEY, revision TEXT NOT NULL, document TEXT NOT NULL, published_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS approvals (
      id TEXT PRIMARY KEY, order_id TEXT NOT NULL, summary_hash TEXT NOT NULL,
      snapshot TEXT NOT NULL, approved_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS authorizations (
      order_id TEXT PRIMARY KEY, revision TEXT NOT NULL, responsibility INTEGER NOT NULL DEFAULT 0,
      authorized_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS photo_frames (
      photo_id TEXT PRIMARY KEY, x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL);
    """)
    con.execute("INSERT OR IGNORE INTO studios VALUES ('local','Локальная студия')")
    con.execute("INSERT OR IGNORE INTO profiles (studio_id) VALUES ('local')")
    con.execute("""INSERT OR IGNORE INTO order_membership (order_id, studio_id)
                   SELECT id, 'local' FROM orders""")
    jobs.init(con)


def digest(salt, value):
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def studio_for_cookie(con, cookie, local_token):
    if cookie and local_token and len(cookie) == len(local_token) and secrets.compare_digest(cookie, local_token):
        return LOCAL
    if not cookie:
        return None
    row = con.execute("SELECT studio_id, expires_at FROM auth_sessions WHERE token_hash=?", (token_hash(cookie),)).fetchone()
    if row is None or row["expires_at"] <= _now():
        return None
    return row["studio_id"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _later(days):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _studio():
    studio = studio_ctx.get()
    if not studio:
        raise HTTPException(401, "Откройте главную страницу приложения")
    return studio


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 50_000).hex()


def profile_of(con, studio):
    row = con.execute("SELECT teacher_gift, delivery_modes FROM profiles WHERE studio_id=?", (studio,)).fetchone()
    if row is None:
        con.execute("INSERT INTO profiles (studio_id) VALUES (?)", (studio,))
        return {"teacher_gift": True, "delivery_modes": "both"}
    return {"teacher_gift": bool(row["teacher_gift"]), "delivery_modes": row["delivery_modes"]}


def attach_order(con, order_id, studio, values):
    studio = studio or LOCAL
    profile = profile_of(con, studio)
    offer_title, offer_price, edition_id, edition_json = "", 0, None, ""
    student_count = values.get("student_count")
    offer_id = values.get("offer_id") or None
    if offer_id:
        offer = con.execute("SELECT * FROM offers WHERE id=? AND studio_id=? AND active=1", (offer_id, studio)).fetchone()
        if offer is None:
            raise HTTPException(404, "Комплектация не найдена")
        edition = con.execute("SELECT * FROM editions WHERE id=?", (offer["edition_id"],)).fetchone()
        if edition is None or not edition["published"]:
            raise HTTPException(422, "Нельзя выбрать неопубликованное издание")
        document = json.loads(edition["document"])
        low, high = document["capacity"]["students"]
        if student_count is not None and not low <= student_count <= high:
            raise HTTPException(422, f"Издание рассчитано на {low}–{high} учеников")
        offer_title, offer_price = offer["title"], offer["price"]
        edition_id, edition_json = edition["id"], edition["document"]
    school_id = values.get("school_id") or None
    if school_id and not con.execute("SELECT 1 FROM schools WHERE id=? AND studio_id=?", (school_id, studio)).fetchone():
        raise HTTPException(404, "Школа не найдена")
    con.execute("INSERT OR REPLACE INTO order_membership VALUES (?,?)", (order_id, studio))
    con.execute("""INSERT INTO order_terms (order_id,customer_name,customer_contact,school_id,offer_id,offer_title,offer_price,
        edition_id,edition_json,planned_paid,current_paid,gift_copies,delivery_modes,student_count,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        order_id, (values.get("customer_name") or "").strip(), (values.get("customer_contact") or "").strip(),
        school_id, offer_id, offer_title, offer_price, edition_id, edition_json,
        values["copies"], values["copies"], 1 if profile["teacher_gift"] else 0, profile["delivery_modes"],
        student_count, _now()))


def photo_visible(con, photo_id):
    row = con.execute("SELECT order_id FROM photos WHERE id=?", (photo_id,)).fetchone()
    if row is None:
        return False
    studio = studio_ctx.get()
    if studio is None:
        return True
    return con.execute("SELECT 1 FROM order_membership WHERE order_id=? AND studio_id=?", (row["order_id"], studio)).fetchone() is not None


def forget(con, order_id):
    for table in ("order_membership", "order_terms", "order_pins", "order_codes", "pin_attempts", "allocations", "deliveries",
                  "publications", "approvals", "authorizations"):
        con.execute(f"DELETE FROM {table} WHERE order_id=?", (order_id,))
    con.execute("DELETE FROM class_sessions WHERE order_id=?", (order_id,))
    from . import client_portal
    client_portal.forget(con, order_id)
    from . import school_catalog
    school_catalog.forget(con, order_id)


def quote_limit(con, order_id):
    row = con.execute("SELECT edition_json FROM order_terms WHERE order_id=?", (order_id,)).fetchone()
    if row and row["edition_json"]:
        document = json.loads(row["edition_json"])
        limits = {} if "master" in document else field_limits(document)
        if "quote" in limits:
            return limits["quote"]
    return 300


def stored_pins(con, order_id):
    """Codes stay visible to the photographer so they can be resent; orders issued before this return None."""
    row = con.execute("SELECT entry_pin, manage_pin FROM order_codes WHERE order_id=?", (order_id,)).fetchone()
    return (row["entry_pin"], row["manage_pin"]) if row else (None, None)


def reset_pins(con, order_id):
    for table in ("order_pins", "order_codes", "pin_attempts", "class_sessions"):
        con.execute(f"DELETE FROM {table} WHERE order_id=?", (order_id,))
    return issue_pins(con, order_id)


def issue_pins(con, order_id):
    row = con.execute("SELECT 1 FROM order_pins WHERE order_id=?", (order_id,)).fetchone()
    if row:
        return stored_pins(con, order_id)
    entry, manage = f"{secrets.randbelow(10000):04d}", f"{secrets.randbelow(10000):04d}"
    while manage == entry:
        manage = f"{secrets.randbelow(10000):04d}"
    entry_salt, manage_salt = secrets.token_hex(8), secrets.token_hex(8)
    con.execute("INSERT INTO order_pins VALUES (?,?,?,?,?)", (
        order_id, digest(entry_salt, entry), entry_salt, digest(manage_salt, manage), manage_salt))
    con.execute("INSERT OR REPLACE INTO order_codes VALUES (?,?,?)", (order_id, entry, manage))
    con.execute("UPDATE order_terms SET workflow='selection' WHERE order_id=? AND workflow='materials'", (order_id,))
    return entry, manage


def _check_pin(con, order_id, kind, pin):
    if not pin or len(pin) != 4 or not pin.isdigit():
        raise HTTPException(422, "Нужен четырёхзначный код")
    attempt = con.execute("SELECT fails, locked_until FROM pin_attempts WHERE order_id=? AND kind=?", (order_id, kind)).fetchone()
    if attempt and attempt["locked_until"] and attempt["locked_until"] > _now():
        raise HTTPException(429, "Слишком много попыток. Подождите и попробуйте снова")
    pins = con.execute("SELECT * FROM order_pins WHERE order_id=?", (order_id,)).fetchone()
    if pins is None:
        raise HTTPException(409, "Код для этого заказа ещё не создан")
    salt, hashed = (pins["entry_salt"], pins["entry_hash"]) if kind == "entry" else (pins["manage_salt"], pins["manage_hash"])
    if not secrets.compare_digest(digest(salt, pin), hashed):
        fails = (attempt["fails"] if attempt else 0) + 1
        locked = "" if fails < 8 else (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        con.execute("""INSERT INTO pin_attempts VALUES (?,?,?,?)
                       ON CONFLICT(order_id, kind) DO UPDATE SET fails=excluded.fails, locked_until=excluded.locked_until""",
                    (order_id, kind, fails, locked))
        raise HTTPException(401, "Неверный код входа" if kind == "entry" else "Неверный код управления")
    con.execute("DELETE FROM pin_attempts WHERE order_id=? AND kind=?", (order_id, kind))


def _open_class(con, order_id, level):
    raw = secrets.token_urlsafe(32)
    con.execute("INSERT INTO class_sessions VALUES (?,?,?,?)", (token_hash(raw), order_id, level, _later(14)))
    return raw


def require_level(con, request, order_id, level):
    cookie = request.cookies.get("album_entry" if level == "entry" else "album_manage")
    if cookie:
        row = con.execute("SELECT order_id, expires_at FROM class_sessions WHERE token_hash=? AND level=?", (token_hash(cookie), level)).fetchone()
        if row and row["order_id"] == order_id and row["expires_at"] > _now():
            return
    if level == "entry":
        raise HTTPException(401, "Нужен код входа")
    raise HTTPException(401, "Нужен код управления")


def has_level(con, request, order_id, level):
    try:
        require_level(con, request, order_id, level)
    except HTTPException:
        return False
    return True


def propose(students, paid):
    rows = []
    if len(students) <= paid:
        for key, label in students:
            rows.append({"key": key, "label": label, "paid": 1, "gift": 0})
        remainder = paid - len(students)
    else:
        for index, (key, label) in enumerate(students):
            rows.append({"key": key, "label": label, "paid": 1 if index < paid else 0, "gift": 0})
        remainder = 0
    return rows, remainder


def _students(con, order_id):
    return [(row["id"], (row["label"] or "Ученик").strip()) for row in con.execute("""
        SELECT p.id, COALESCE(NULLIF(trim(s.first_name||' '||s.last_name),' '), NULLIF(p.name,'')) AS label
        FROM persons p LEFT JOIN client_selections s ON s.person_id=p.id
        WHERE p.order_id=? ORDER BY p.created_at, p.id""", (order_id,))]


def ensure_allocations(con, order_id):
    terms = con.execute("SELECT * FROM order_terms WHERE order_id=?", (order_id,)).fetchone()
    if terms is None:
        return
    if terms["allocations_custom"]:
        return
    rows, _remainder = propose(_students(con, order_id), terms["current_paid"])
    if terms["gift_copies"]:
        rows.append({"key": "gift", "label": "Подарок учителю", "paid": 0, "gift": terms["gift_copies"]})
    con.execute("DELETE FROM allocations WHERE order_id=?", (order_id,))
    con.executemany("INSERT INTO allocations VALUES (?,?,?,?,?)", [
        (order_id, row["key"], row["label"], row["paid"], row["gift"]) for row in rows])


def _allocation_rows(con, order_id):
    ensure_allocations(con, order_id)
    return [dict(row) for row in con.execute(
        "SELECT recipient_key AS key, label, paid, gift FROM allocations WHERE order_id=? ORDER BY recipient_key", (order_id,))]


def _delivery(con, order_id):
    row = con.execute("SELECT mode,carrier,address,recipient,phone FROM deliveries WHERE order_id=?", (order_id,)).fetchone()
    if row is None or not row["mode"]:
        return None
    return dict(row)


def summary_body(con, order, public=True):
    terms = con.execute("SELECT * FROM order_terms WHERE order_id=?", (order["id"],)).fetchone()
    rows = _allocation_rows(con, order["id"])
    paid_assigned = sum(row["paid"] for row in rows)
    current = terms["current_paid"] if terms else order["copies"]
    gift = terms["gift_copies"] if terms else 0
    publication = con.execute("SELECT revision FROM publications WHERE order_id=?", (order["id"],)).fetchone()
    delivery = _delivery(con, order["id"]) or {}
    body = {
        "title": (terms["offer_title"] if terms and terms["offer_title"] else f"{order['school']} {order['class_name']}"),
        "allocations": rows,
        "remainder": current - paid_assigned,
        "gift": gift,
        "total": current + gift,
        "delivery": delivery,
        "delivery_modes": terms["delivery_modes"] if terms else "both",
        "revision": publication["revision"] if publication else "",
        "paid_total": current,
    }
    canonical = {key: body[key] for key in ("title", "allocations", "remainder", "gift", "total", "delivery", "revision", "paid_total")}
    body["hash"] = hashlib.sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if not public and terms:
        body["offer_price"] = terms["offer_price"]
    return body


_PUBLIC_ELEMENT = ("type", "box", "photo", "crop", "mask", "text", "size", "color", "font", "align", "fill", "opacity", "angle", "rotation_center", "radius", "stroke", "strokeWidth", "strokeDash", "strokeAlign", "strokeCap", "strokeJoin", "valign", "svg", "flipX", "flipY")


def publication_photo_ids(document):
    found = set()

    def walk(spreads):
        for spread in (spreads or {}).values():
            for element in spread.get("elements") or []:
                if element.get("photo"):
                    found.add(element["photo"])

    walk(document.get("shared_spreads"))
    walk(document.get("covers"))
    for group in (document.get("variant_spreads") or {}).values():
        walk(group)
    return found


def _public_spread(spread, sizes):
    if not spread:
        return None
    elements = []
    for element in spread.get("elements") or []:
        if element.get("hidden"):
            continue
        item = {key: element[key] for key in _PUBLIC_ELEMENT if key in element}
        size = sizes.get(element.get("photo"))
        if size:
            item["width"], item["height"] = size
        elements.append(item)
    return {"key": spread.get("key"), "section": spread.get("section") or "", "elements": elements}


def client_layout_view(document, sizes=None):
    """Published spreads only. Draft issues, prices and override history stay out."""
    sizes = sizes or {}
    covers = document.get("covers") or {}
    shared = document.get("shared_spreads") or {}
    per_variant = document.get("variant_spreads") or {}
    variants = []
    for variant in document.get("variants") or []:
        owner = variant.get("owner")
        spreads = []
        for key in variant.get("sequence") or []:
            if str(key).startswith("cover["):
                raw = covers.get(owner)
            else:
                raw = shared.get(key) or (per_variant.get(owner) or {}).get(key)
            view = _public_spread(raw, sizes)
            if view:
                spreads.append(view)
        variants.append({
            "owner": owner,
            "name": variant.get("name") or "Общий вариант",
            "spreads": spreads,
        })
    return {
        "revision": document.get("revision") or "",
        "spread_size_mm": document.get("spread_size_mm"),
        "cover_size_mm": document.get("cover_size_mm"),
        "master_template": bool(document.get("master_template")),
        "variants": variants,
    }


def _terms(con, order_id):
    row = con.execute("SELECT * FROM order_terms WHERE order_id=?", (order_id,)).fetchone()
    if row is None:
        raise HTTPException(409, "У заказа ещё нет условий")
    return row


class ProfileInput(BaseModel):
    teacher_gift: bool
    delivery_modes: str


class EditionInput(BaseModel):
    document: dict


class OfferInput(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    price: int = Field(ge=0, le=1_000_000)
    edition_id: str


class AccountInput(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=100)
    studio_name: str = Field(min_length=1, max_length=100)


class LoginInput(BaseModel):
    email: str
    password: str


class PinInput(BaseModel):
    pin: str


class SummaryInput(BaseModel):
    allocations: list[dict]
    paid_total: int = Field(ge=0, le=1000)
    delivery: dict


class ApproveInput(BaseModel):
    hash: str


class ProductionInput(BaseModel):
    responsibility: bool = False


def install(app, s):
    def set_class_cookie(response, name, raw):
        response.set_cookie(name, raw, httponly=True, samesite="strict", path="/")
        return response

    @app.post("/api/register")
    def register(payload: AccountInput):
        email = payload.email.strip().lower()
        studio_id = s.uid()
        salt = secrets.token_hex(8)
        with s.db() as con:
            if con.execute("SELECT 1 FROM photographers WHERE email=?", (email,)).fetchone():
                raise HTTPException(409, "Такая почта уже зарегистрирована")
            con.execute("INSERT INTO studios VALUES (?,?)", (studio_id, payload.studio_name.strip()))
            con.execute("INSERT INTO profiles (studio_id) VALUES (?)", (studio_id,))
            photographer = s.uid()
            con.execute("INSERT INTO photographers VALUES (?,?,?,?,?)", (
                photographer, studio_id, email, password_hash(payload.password, salt), salt))
            raw = secrets.token_urlsafe(32)
            con.execute("INSERT INTO auth_sessions VALUES (?,?,?,?)", (token_hash(raw), studio_id, photographer, _later(30)))
        response = JSONResponse({"studio_id": studio_id})
        response.set_cookie("album_session", raw, httponly=True, samesite="strict", path="/")
        return response

    @app.post("/api/login")
    def login(payload: LoginInput):
        email = payload.email.strip().lower()
        with s.db() as con:
            row = con.execute("SELECT * FROM photographers WHERE email=?", (email,)).fetchone()
            if row is None or not secrets.compare_digest(password_hash(payload.password, row["salt"]), row["password_hash"]):
                raise HTTPException(401, "Неверная почта или пароль")
            raw = secrets.token_urlsafe(32)
            studio_id = row["studio_id"]
            con.execute("INSERT INTO auth_sessions VALUES (?,?,?,?)", (token_hash(raw), studio_id, row["id"], _later(30)))
        response = JSONResponse({"studio_id": studio_id})
        response.set_cookie("album_session", raw, httponly=True, samesite="strict", path="/")
        return response

    @app.get("/api/profile")
    def get_profile():
        with s.db() as con:
            return profile_of(con, _studio())

    @app.put("/api/profile")
    def put_profile(payload: ProfileInput):
        if payload.delivery_modes not in {"personal", "shipping", "both"}:
            raise HTTPException(422, "Неизвестный способ получения")
        with s.db() as con:
            con.execute("INSERT INTO profiles (studio_id, teacher_gift, delivery_modes) VALUES (?,?,?) ON CONFLICT(studio_id) DO UPDATE SET teacher_gift=excluded.teacher_gift, delivery_modes=excluded.delivery_modes",
                        (_studio(), int(payload.teacher_gift), payload.delivery_modes))
        return {"teacher_gift": payload.teacher_gift, "delivery_modes": payload.delivery_modes}

    @app.post("/api/catalog/editions", status_code=201)
    def publish_edition(payload: EditionInput):
        document = payload.document
        if str(document.get("id", "")).startswith("master-"):
            raise HTTPException(422, "Версии мастер-макетов публикуются через редактор")
        try:
            validate_edition(document)
            failures = capacity_matrix(document)
        except (LayoutError, KeyError, TypeError) as exc:
            raise HTTPException(422, f"Издание не готово к публикации: {exc}") from exc
        if failures:
            raise HTTPException(422, "Матрица ёмкости не пройдена")
        edition_id = str(document.get("id") or s.uid())
        with s.db() as con:
            con.execute("INSERT INTO editions VALUES (?,?,1) ON CONFLICT(id) DO UPDATE SET document=excluded.document, published=1",
                        (edition_id, json.dumps(document, ensure_ascii=False)))
        return {"id": edition_id, "published": True}

    @app.get("/api/offers")
    def list_offers():
        with s.db() as con:
            rows = []
            for offer in con.execute("""SELECT o.*, e.document, e.published FROM offers o
                    JOIN editions e ON e.id=o.edition_id WHERE o.studio_id=? ORDER BY o.title""", (_studio(),)):
                document = json.loads(offer["document"])
                rows.append({"id": offer["id"], "title": offer["title"], "price": offer["price"],
                             "edition_id": offer["edition_id"], "active": bool(offer["active"] and offer["published"]),
                             "capacity": document.get("capacity"), "spreads": document.get("spreads")})
            return rows

    @app.post("/api/offers", status_code=201)
    def create_offer(payload: OfferInput):
        with s.db() as con:
            edition = con.execute("SELECT published FROM editions WHERE id=?", (payload.edition_id,)).fetchone()
            if edition is None or not edition["published"]:
                raise HTTPException(422, "Нельзя выбрать неопубликованное издание")
            if payload.edition_id.startswith("master-") and not con.execute("SELECT 1 FROM offers WHERE edition_id=? AND studio_id=?", (payload.edition_id, _studio())).fetchone():
                raise HTTPException(404, "Издание не найдено")
            offer_id = s.uid()
            con.execute("INSERT INTO offers VALUES (?,?,?,?,?,1)", (offer_id, _studio(), payload.edition_id, payload.title.strip(), payload.price))
        return {"id": offer_id}

    @app.get("/api/print-spec")
    def print_spec():
        path = s.ROOT / "examples" / "print" / "first-binding.json"
        return json.loads(path.read_text())

    @app.get("/api/orders/{order_id}/deal")
    def deal(order_id: str):
        with s.db() as con:
            order = dict(s.require_order(con, order_id))
            terms = _terms(con, order_id)
            approval = con.execute("SELECT approved_at, summary_hash FROM approvals WHERE order_id=? ORDER BY approved_at DESC LIMIT 1", (order_id,)).fetchone()
            auth = con.execute("SELECT * FROM authorizations WHERE order_id=?", (order_id,)).fetchone()
            publication = con.execute("SELECT revision FROM publications WHERE order_id=?", (order_id,)).fetchone()
            body = summary_body(con, order, public=False)
            differences = None
            if terms["current_paid"] != terms["planned_paid"]:
                differences = {"paid_copies": {"was": terms["planned_paid"], "now": terms["current_paid"]}}
            return {
                "offer_price": terms["offer_price"],
                "planned_paid": terms["planned_paid"],
                "gift": terms["gift_copies"],
                "allocations": body["allocations"],
                "delivery_modes": terms["delivery_modes"],
                "delivery": body["delivery"] or None,
                "approval": {"at": approval["approved_at"], "hash": approval["summary_hash"]} if approval else None,
                "production": {"authorized": True, "at": auth["authorized_at"], "responsibility": bool(auth["responsibility"])} if auth else None,
                "differences": differences,
                "retention": {"delete_on": retention_deadline(order["created_at"])},
                "pins_set": con.execute("SELECT 1 FROM order_pins WHERE order_id=?", (order_id,)).fetchone() is not None,
                "workflow": terms["workflow"],
                "published": publication is not None,
            }

    @app.post("/api/orders/{order_id}/layout/publish")
    def publish_layout(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            layout = con.execute("SELECT document FROM order_layouts WHERE order_id=?", (order_id,)).fetchone()
            if layout is None:
                raise HTTPException(409, "Сначала создайте макет")
            document = json.loads(layout["document"])
            if any(issue.get("level") == "error" for issue in document.get("issues") or []):
                raise HTTPException(409, "Исправьте ошибки макета перед публикацией")
            revision = str(document.get("revision") or hashlib.sha256(layout["document"].encode()).hexdigest()[:12])
            con.execute("INSERT INTO publications VALUES (?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET revision=excluded.revision, document=excluded.document, published_at=excluded.published_at",
                        (order_id, revision, layout["document"], s.now()))
            if con.execute("SELECT stage FROM orders WHERE id=?", (order_id,)).fetchone()["stage"] in order_stages.STAGES[5:]:
                raise HTTPException(409, "Заказ уже отправлен в печать")
            con.execute("UPDATE order_terms SET workflow='layout' WHERE order_id=?", (order_id,))
            order_stages.set_stage(con, order_id, 'approval')
            # A new revision answers the class's earlier requests.
            con.execute("UPDATE layout_corrections SET status='resolved' WHERE order_id=? AND status='open' AND revision<>?", (order_id, revision))
        return {"revision": revision}

    @app.post("/api/orders/{order_id}/production")
    def authorize(order_id: str, payload: ProductionInput):
        with s.db() as con:
            s.require_order(con, order_id)
            publication = con.execute("SELECT revision FROM publications WHERE order_id=?", (order_id,)).fetchone()
            approval = con.execute("SELECT snapshot FROM approvals WHERE order_id=? ORDER BY approved_at DESC LIMIT 1", (order_id,)).fetchone()
            if publication is None:
                raise HTTPException(409, "Сначала опубликуйте макет")
            approved_revision = json.loads(approval["snapshot"])["revision"] if approval else None
            if approved_revision != publication["revision"] and not payload.responsibility:
                raise HTTPException(409, "Ожидается повторное согласование")
            if approval is None and not payload.responsibility:
                raise HTTPException(409, "Сначала нужно согласование класса")
            existing = con.execute("SELECT revision FROM authorizations WHERE order_id=?", (order_id,)).fetchone()
            if existing and existing["revision"] == publication["revision"]:
                return {"authorized": True}
            con.execute("INSERT INTO authorizations VALUES (?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET revision=excluded.revision, responsibility=excluded.responsibility, authorized_at=excluded.authorized_at",
                        (order_id, publication["revision"], int(payload.responsibility), s.now()))
            con.execute("UPDATE order_terms SET workflow='production_allowed' WHERE order_id=?", (order_id,))
            order_stages.advance(con, order_id, 'print')
            job = jobs.enqueue(con, "export", {"order_id": order_id}, f"export:{order_id}:{publication['revision']}", s.now())
        if job["status"] == "pending":
            with s.db() as con:
                jobs.run_once(con, {"export": lambda payload: _write_export(s, payload["order_id"])}, s.now())
        return {"authorized": True}

    @app.get("/api/orders/{order_id}/export")
    def export_bundle(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            if con.execute("SELECT 1 FROM authorizations WHERE order_id=?", (order_id,)).fetchone() is None:
                raise HTTPException(409, "Производство ещё не разрешено")
            path = _manifest_path(s, order_id)
            if not path.is_file():
                _write_export(s, order_id)
            return json.loads(path.read_text())

    @app.post("/client-api/{token}/enter")
    def enter(token: str, payload: PinInput):
        with s.db() as con:
            order = _order_by_token(con, token)
            _check_pin(con, order["id"], "entry", payload.pin.strip())
            raw = _open_class(con, order["id"], "entry")
        return set_class_cookie(JSONResponse({"ok": True}), "album_entry", raw)

    @app.get("/client-api/{token}/layout")
    def client_layout(token: str, request: Request):
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "entry")
            row = con.execute("SELECT document FROM publications WHERE order_id=?", (order["id"],)).fetchone()
            if row is None:
                raise HTTPException(409, "Макет ещё не опубликован")
            document = json.loads(row["document"])
            sizes = {}
            for photo_id in publication_photo_ids(document):
                path = Path(s.DATA) / "photos" / f"{photo_id}.jpg"
                if not path.is_file():
                    continue
                try:
                    from PIL import Image
                    with Image.open(path) as image:
                        sizes[photo_id] = list(image.size)
                except OSError:
                    continue
            return client_layout_view(document, sizes)

    @app.get("/client-api/{token}/layout/photos/{photo_id}/{variant}")
    def client_layout_photo(token: str, photo_id: str, variant: str, request: Request):
        if variant not in {"thumb", "full"}:
            raise HTTPException(404, "Фотография не найдена")
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "entry")
            row = con.execute("SELECT document FROM publications WHERE order_id=?", (order["id"],)).fetchone()
            if row is None:
                raise HTTPException(404, "Фотография не найдена")
            document = json.loads(row["document"])
            known = con.execute("SELECT id FROM photos WHERE id=? AND order_id=?", (photo_id, order["id"])).fetchone()
            is_master_asset = bool(re.fullmatch(r"master-[a-f0-9]{64}", photo_id))
            if (known is None and not is_master_asset) or photo_id not in publication_photo_ids(document):
                raise HTTPException(404, "Фотография не найдена")
        path = Path(s.DATA) / "photos" / (photo_id + (".thumb.jpg" if variant == "thumb" and not is_master_asset else ".jpg"))
        if not path.is_file():
            raise HTTPException(404, "Фотография не найдена")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/client-api/{token}/summary")
    def client_summary(token: str, request: Request):
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "entry")
            if con.execute("SELECT 1 FROM publications WHERE order_id=?", (order["id"],)).fetchone() is None:
                raise HTTPException(409, "Макет ещё не опубликован")
            body = summary_body(con, dict(order), public=True)
            if "offer_price" in body or "price" in body:
                body.pop("offer_price", None)
                body.pop("price", None)
            return body

    @app.put("/client-api/{token}/summary")
    def save_summary(token: str, payload: SummaryInput, request: Request):
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "entry")
            terms = _terms(con, order["id"])
            mode = payload.delivery.get("mode")
            allowed = {"personal", "shipping"} if terms["delivery_modes"] == "both" else {terms["delivery_modes"]}
            if mode not in allowed:
                raise HTTPException(422, "Этот способ получения фотограф не использует")
            carrier = "" if mode == "personal" else str(payload.delivery.get("carrier") or "").strip()
            address = "" if mode == "personal" else str(payload.delivery.get("address") or "").strip()
            if mode == "shipping" and not address:
                raise HTTPException(422, "Укажите адрес или пункт выдачи")
            paid = 0
            rows = []
            for item in payload.allocations:
                key, label_paid, gift = str(item.get("key") or ""), int(item.get("paid") or 0), int(item.get("gift") or 0)
                if label_paid < 0 or gift < 0:
                    raise HTTPException(422, "Количество не может быть отрицательным")
                known = con.execute("SELECT label FROM allocations WHERE order_id=? AND recipient_key=?", (order["id"], key)).fetchone()
                if known is None:
                    raise HTTPException(422, "Неизвестный получатель")
                rows.append((order["id"], key, known["label"], label_paid, gift))
                paid += label_paid
            if paid != payload.paid_total:
                raise HTTPException(422, "Сумма по получателям не сходится с платным тиражом")
            con.execute("DELETE FROM allocations WHERE order_id=?", (order["id"],))
            con.executemany("INSERT INTO allocations VALUES (?,?,?,?,?)", rows)
            con.execute("""INSERT INTO deliveries VALUES (?,?,?,?,?,?)
                ON CONFLICT(order_id) DO UPDATE SET mode=excluded.mode, carrier=excluded.carrier, address=excluded.address,
                recipient=excluded.recipient, phone=excluded.phone""", (
                order["id"], mode, carrier, address, str(payload.delivery.get("recipient") or "").strip(),
                str(payload.delivery.get("phone") or "").strip()))
            con.execute("UPDATE order_terms SET current_paid=?, allocations_custom=1 WHERE order_id=?", (payload.paid_total, order["id"]))
            return summary_body(con, dict(order), public=True)

    @app.post("/client-api/{token}/manage")
    def manage(token: str, payload: PinInput):
        with s.db() as con:
            order = _order_by_token(con, token)
            _check_pin(con, order["id"], "manage", payload.pin.strip())
            raw = _open_class(con, order["id"], "manage")
        return set_class_cookie(JSONResponse({"ok": True}), "album_manage", raw)

    @app.post("/client-api/{token}/approve")
    def approve(token: str, payload: ApproveInput, request: Request):
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "manage")
            if con.execute("SELECT 1 FROM publications WHERE order_id=?", (order["id"],)).fetchone() is None:
                raise HTTPException(409, "Макет ещё не опубликован")
            from .client_portal import open_corrections
            if open_corrections(con, order["id"]):
                raise HTTPException(409, "Вы отправили правки. Дождитесь обновлённого макета или отзовите правки")
            if order["stage"] not in ("approval",):
                raise HTTPException(409, "Макет обновляется. Согласуйте новую версию, когда фотограф её отправит")
            body = summary_body(con, dict(order), public=True)
            if payload.hash != body["hash"]:
                raise HTTPException(409, "Сводка изменилась. Проверьте её ещё раз.")
            if body["remainder"] != 0:
                raise HTTPException(409, "Остались нераспределённые экземпляры")
            if not (body["delivery"] or {}).get("mode"):
                raise HTTPException(409, "Укажите получение")
            con.execute("INSERT INTO approvals VALUES (?,?,?,?,?)", (
                s.uid(), order["id"], body["hash"], json.dumps({"revision": body["revision"], "summary": body}, ensure_ascii=False), s.now()))
            con.execute("UPDATE order_terms SET workflow='client_approved' WHERE order_id=?", (order["id"],))
        return {"ok": True}

    @app.post("/client-api/{token}/persons/{person_id}/submit")
    def submit_form(token: str, person_id: str, request: Request):
        with s.db() as con:
            order = _order_by_token(con, token)
            require_level(con, request, order["id"], "entry")
            row = con.execute("SELECT photo_id FROM selection_state WHERE person_id=?", (person_id,)).fetchone()
            person = con.execute("SELECT id FROM persons WHERE id=? AND order_id=?", (person_id, order["id"])).fetchone()
            if person is None or row is None:
                raise HTTPException(409, "Сначала выберите портрет и подпись")
            con.execute("UPDATE selection_state SET submitted=1 WHERE person_id=?", (person_id,))
        return {"ok": True}


def _order_by_token(con, token):
    row = con.execute("SELECT o.* FROM orders o JOIN client_links l ON l.order_id=o.id WHERE l.token=?", (token,)).fetchone()
    if row is None:
        raise HTTPException(404, "Ссылка на заказ не найдена")
    return row


def _manifest_path(server, order_id):
    return Path(server.DATA) / "exports" / order_id / "manifest.json"


def _write_export(server, order_id):
    with server.db() as con:
        rows = [dict(row) for row in con.execute(
            "SELECT recipient_key, label, paid, gift FROM allocations WHERE order_id=?", (order_id,))]
    files = []
    folder = Path(server.DATA) / "exports" / order_id
    folder.mkdir(parents=True, exist_ok=True)
    for row in rows:
        copies = row["paid"] + row["gift"]
        if copies <= 0:
            continue
        safe = "".join(ch if ch.isalnum() or ch in " ._-" else "_" for ch in row["label"]).strip() or row["recipient_key"]
        name = f"{safe}.pdf"
        (folder / name).write_bytes(PDF)
        files.append({"name": name, "copies_paid": row["paid"], "copies_gift": row["gift"]})
    manifest = {"files": files, "total": sum(item["copies_paid"] + item["copies_gift"] for item in files)}
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
    return manifest
