"""Studio school catalogue: schools, their teachers and the teachers chosen for each class album.

Every school belongs to one studio. Teachers belong to a school and are reused across that
school's orders, so a portrait taken once keeps working in later albums. The class chooses
which teachers appear in its album and who is the class teacher; the photographer can do the
same from the order page. Nothing here is shared between studios.

Teacher photos arrive unsigned and are grouped by face like pupils' portraits. The photographer picks a frame and releases it for naming. The class only signs that frame; source frames are retained for photographer undo. The photographer can
replace a portrait later.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import mvp, order_stages, upload_runs

LOCKED_STAGES = set(order_stages.STAGES[5:])
PORTRAIT_SUFFIXES = (".original", ".jpg", ".thumb.jpg")


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS order_teachers (
      order_id TEXT NOT NULL, teacher_id TEXT NOT NULL, position INTEGER NOT NULL,
      is_class_teacher INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (order_id, teacher_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS teacher_photos (
      id TEXT PRIMARY KEY, school_id TEXT NOT NULL, order_id TEXT, filename TEXT NOT NULL,
      sha TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE (school_id, sha))""")
    con.execute("""CREATE TABLE IF NOT EXISTS order_teacher_state (
      order_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS teacher_assignments (
      id TEXT PRIMARY KEY, school_id TEXT NOT NULL, teacher_id TEXT NOT NULL, group_id TEXT NOT NULL,
      portrait_path TEXT NOT NULL, previous_path TEXT NOT NULL, previous_by TEXT NOT NULL,
      previous_at TEXT NOT NULL, created_at TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0)""")
    con.execute("""CREATE TABLE IF NOT EXISTS teacher_uploads (
      school_id TEXT NOT NULL, sha TEXT NOT NULL, id TEXT NOT NULL, PRIMARY KEY(school_id,sha))""")
    if "subject" not in {r[1] for r in con.execute("PRAGMA table_info(order_teachers)")}:
        con.execute("ALTER TABLE order_teachers ADD COLUMN subject TEXT")
    if "school_city" not in {r[1] for r in con.execute("PRAGMA table_info(orders)")}:
        con.execute("ALTER TABLE orders ADD COLUMN school_city TEXT NOT NULL DEFAULT ''")
        # Existing orders keep their location even when the catalogue is edited later.
        if "city" in {r[1] for r in con.execute("PRAGMA table_info(schools)")}:
            con.execute("""UPDATE orders SET school_city=COALESCE((SELECT s.city FROM order_terms ot
                JOIN schools s ON s.id=ot.school_id WHERE ot.order_id=orders.id),'')""")
    schools = {r[1] for r in con.execute("PRAGMA table_info(schools)")}
    if "city" not in schools:
        con.execute("ALTER TABLE schools ADD COLUMN city TEXT NOT NULL DEFAULT ''")
    if "short_name" not in schools:
        con.execute("ALTER TABLE schools ADD COLUMN short_name TEXT NOT NULL DEFAULT ''")
    teachers = {r[1] for r in con.execute("PRAGMA table_info(teachers)")}
    for column, kind in (("patronymic", "TEXT NOT NULL DEFAULT ''"), ("subject", "TEXT NOT NULL DEFAULT ''"),
                         ("archived", "INTEGER NOT NULL DEFAULT 0"), ("created_at", "TEXT NOT NULL DEFAULT ''"),
                         ("portrait_by", "TEXT NOT NULL DEFAULT ''"), ("portrait_at", "TEXT NOT NULL DEFAULT ''")):
        if column not in teachers:
            con.execute(f"ALTER TABLE teachers ADD COLUMN {column} {kind}")
    con.execute("""CREATE TABLE IF NOT EXISTS teacher_shoots (
      id TEXT PRIMARY KEY, school_id TEXT NOT NULL, title TEXT NOT NULL,
      shot_on TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS teacher_frame_choices (
      group_id TEXT PRIMARY KEY, photo_id TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0)""")
    photos = {r[1] for r in con.execute("PRAGMA table_info(teacher_photos)")}
    for column, kind in (("group_id", "TEXT"), ("status", "TEXT NOT NULL DEFAULT 'ready'"), ("embedding", "TEXT"), ("shoot_id", "TEXT")):
        if column not in photos:
            con.execute(f"ALTER TABLE teacher_photos ADD COLUMN {column} {kind}")
    con.execute("UPDATE teacher_photos SET group_id=id WHERE group_id IS NULL")
    con.execute("INSERT OR IGNORE INTO teacher_uploads SELECT school_id,sha,id FROM teacher_photos")
    invalid = [r[0] for r in con.execute("""SELECT DISTINCT ot.order_id FROM order_teachers ot
        JOIN teachers t ON t.id=ot.teacher_id JOIN order_terms o ON o.order_id=ot.order_id
        WHERE t.school_id IS NOT o.school_id""")]
    for order_id in invalid:
        con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
        con.execute("DELETE FROM order_teacher_state WHERE order_id=?", (order_id,))


def forget(con, order_id):
    con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
    con.execute("DELETE FROM order_teacher_state WHERE order_id=?", (order_id,))
    con.execute("UPDATE teacher_photos SET order_id=NULL WHERE order_id=?", (order_id,))


def clean(text):
    return " ".join(str(text or "").split())


def full_name(teacher):
    return " ".join(filter(None, (teacher["last_name"], teacher["first_name"], teacher["patronymic"])))


def teacher_view(row):
    return {"id": row["id"], "school_id": row["school_id"], "last_name": row["last_name"],
            "first_name": row["first_name"], "patronymic": row["patronymic"], "subject": row["subject"],
            "archived": bool(row["archived"]), "portrait_at": row["portrait_at"],
            "name": full_name(row), "has_portrait": bool(row["portrait_path"]), "portrait_by": row["portrait_by"],
            "portrait_version": row["portrait_path"].rsplit("/", 1)[-1].split(".")[0] if row["portrait_path"] else ""}


def require_school(con, school_id):
    row = con.execute("SELECT * FROM schools WHERE id=? AND studio_id=?", (school_id, mvp._studio())).fetchone()
    if row is None:
        raise HTTPException(404, "Школа не найдена")
    return row


def require_teacher(con, teacher_id, include_archived=False):
    row = con.execute("""SELECT t.* FROM teachers t JOIN schools s ON s.id=t.school_id
        WHERE t.id=? AND s.studio_id=? AND (t.archived=0 OR ?)""", (teacher_id, mvp._studio(), include_archived)).fetchone()
    if row is None:
        raise HTTPException(404, "Учитель не найден")
    return row


def school_teachers(con, school_id):
    return con.execute("""SELECT * FROM teachers WHERE school_id=? AND archived=0
        ORDER BY last_name COLLATE NOCASE, first_name COLLATE NOCASE, patronymic COLLATE NOCASE, id""",
                       (school_id,)).fetchall()


def order_school_id(con, order_id):
    row = con.execute("SELECT school_id FROM order_terms WHERE order_id=?", (order_id,)).fetchone()
    return row["school_id"] if row and row["school_id"] else None


def chosen(con, order_id):
    """The album's teachers: class teacher first, then in the order they were chosen."""
    return con.execute("""SELECT t.*, ot.is_class_teacher, COALESCE(ot.subject,t.subject) AS order_subject FROM order_teachers ot
        JOIN teachers t ON t.id=ot.teacher_id
        JOIN order_terms terms ON terms.order_id=ot.order_id AND terms.school_id=t.school_id WHERE ot.order_id=?
        ORDER BY ot.is_class_teacher DESC, ot.position, t.id""", (order_id,)).fetchall()


def order_teachers_body(con, order_id, public=False):
    school_id = order_school_id(con, order_id)
    school = con.execute("SELECT id,name,city FROM schools WHERE id=?", (school_id,)).fetchone() if school_id else None
    selected = {row["id"]: bool(row["is_class_teacher"]) for row in chosen(con, order_id)}
    picked = {row["id"]: row for row in chosen(con, order_id)}
    teachers = []
    rows = list(school_teachers(con, school_id)) if school else []
    rows += [row for row in picked.values() if row["archived"]]
    for row in rows:
        item = teacher_view(row)
        item["subject"] = picked[row["id"]]["order_subject"] if row["id"] in picked else row["subject"]
        item.update(selected=row["id"] in selected, is_class_teacher=selected.get(row["id"], False))
        teachers.append(item)
    stage = con.execute("SELECT stage FROM orders WHERE id=?", (order_id,)).fetchone()
    state = con.execute("SELECT updated_at, updated_by FROM order_teacher_state WHERE order_id=?", (order_id,)).fetchone()
    body = {"school": dict(school) if school else None, "teachers": teachers,
            "class_teacher_id": next((key for key, lead in selected.items() if lead), None),
            "chosen": state is not None, "locked": bool(stage and stage["stage"] in LOCKED_STAGES)}
    if not public:
        layout = con.execute("SELECT generated_at,snapshot FROM order_layouts WHERE order_id=?", (order_id,)).fetchone()
        body.update(updated_at=state["updated_at"] if state else None, updated_by=state["updated_by"] if state else None,
                    unsigned_groups=unsigned_groups(con, school_id) if school else 0,
                    layout_outdated=bool(layout and json.loads(layout["snapshot"]).get("school_catalog_state") != catalog_state(con, order_id)))
    return body


def save_order_teachers(con, order_id, teacher_ids, class_teacher_id, who, when, subjects=None):
    stage = con.execute("SELECT stage FROM orders WHERE id=?", (order_id,)).fetchone()
    if stage and stage["stage"] in LOCKED_STAGES:
        raise HTTPException(409, "Заказ уже отправлен в печать. Состав учителей изменить нельзя")
    school_id = order_school_id(con, order_id)
    if school_id is None:
        raise HTTPException(409, "Фотограф ещё не выбрал школу из каталога")
    ids = list(dict.fromkeys(teacher_ids))
    known = {row["id"] for row in school_teachers(con, school_id)} | {row["id"] for row in chosen(con, order_id)}
    if any(teacher_id not in known for teacher_id in ids):
        raise HTTPException(422, "Учитель не найден в этой школе")
    if class_teacher_id and class_teacher_id not in ids:
        raise HTTPException(422, "Классный руководитель должен быть среди выбранных учителей")
    previous = {row["teacher_id"]: row["subject"] for row in con.execute("SELECT teacher_id,subject FROM order_teachers WHERE order_id=?", (order_id,))}
    subjects = subjects or {}
    if any(key not in ids or len(value) > 100 for key, value in subjects.items()):
        raise HTTPException(422, "Проверьте предметы выбранных учителей (до 100 символов)")
    con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
    con.executemany("INSERT INTO order_teachers (order_id,teacher_id,position,is_class_teacher,subject) VALUES (?,?,?,?,?)", [
        (order_id, teacher_id, index, int(teacher_id == class_teacher_id), clean(subjects[teacher_id]) if teacher_id in subjects else previous.get(teacher_id)) for index, teacher_id in enumerate(ids)])
    con.execute("""INSERT INTO order_teacher_state VALUES (?,?,?) ON CONFLICT(order_id)
        DO UPDATE SET updated_at=excluded.updated_at, updated_by=excluded.updated_by""", (order_id, when, who))


def snapshot_teachers(con, order_id):
    """Teacher records for the layout snapshot, in album order."""
    return [{"id": row["id"], "first_name": row["first_name"], "last_name": row["last_name"],
             "patronymic": row["patronymic"], "school_subject": row["order_subject"],
             "is_class_teacher": bool(row["is_class_teacher"]), "portrait_path": row["portrait_path"]}
            for row in chosen(con, order_id)]


def catalog_state(con, order_id):
    order = con.execute("SELECT school,school_city,class_name,graduation_year FROM orders WHERE id=?", (order_id,)).fetchone()
    value = {"school_id": order_school_id(con, order_id), "order": dict(order), "teachers": snapshot_teachers(con, order_id)}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def resolve_order_school(con, school_id, name, city, uid):
    name, city = clean(name), clean(city)
    if school_id:
        row = require_school(con, school_id)
        name = row["name"]
        city = city or row["city"]
        if row["city"] and city.casefold() != row["city"].casefold():
            raise HTTPException(409, "Город не совпадает со школой. Выберите другую школу или измените её в каталоге")
    if not name or not city:
        raise HTTPException(422, "Укажите школу и город")
    matches = [r for r in con.execute("SELECT * FROM schools WHERE studio_id=?", (mvp._studio(),))
               if clean(r["name"]).casefold() == name.casefold() and clean(r["city"]).casefold() == city.casefold()]
    if school_id:
        if matches and matches[0]["id"] != school_id:
            raise HTTPException(409, "Такая школа с этим городом уже есть. Выберите её из каталога")
        con.execute("UPDATE schools SET city=? WHERE id=?", (city, school_id))
    elif matches:
        school_id, name, city = matches[0]["id"], matches[0]["name"], matches[0]["city"]
    else:
        school_id = uid()
        con.execute("INSERT INTO schools (id,studio_id,name,address,city) VALUES (?,?,?,?,?)", (school_id, mvp._studio(), name, "", city))
    return school_id, name, city


def unsigned_groups(con, school_id, ready_only=False):
    return con.execute(f"""SELECT COUNT(DISTINCT group_id) FROM teacher_photos
        WHERE school_id=? {"AND status='ready'" if ready_only else "AND status!='signed'"}""", (school_id,)).fetchone()[0]


def photo_groups(con, school_id, ready_only=False):
    """Unsigned photos by teacher group, in upload order."""
    groups = {}
    for row in con.execute(f"""SELECT * FROM teacher_photos WHERE school_id=? {"AND status='ready'" if ready_only else "AND status!='signed'"}
            ORDER BY created_at, filename, id""", (school_id,)):
        groups.setdefault(row["group_id"], []).append(row)
    return groups


def frame_choice(con, rows):
    """A singleton is selected automatically; multiple frames need an explicit choice."""
    choice = con.execute("SELECT * FROM teacher_frame_choices WHERE group_id=?", (rows[0]["group_id"],)).fetchone()
    selected = next((r for r in rows if choice and r["id"] == choice["photo_id"] and r["status"] == "ready"), None)
    if selected is None and len(rows) == 1 and rows[0]["status"] == "ready":
        selected = rows[0]
    return selected, bool(selected and choice and choice["published"])


def client_groups(con, school_id):
    result = []
    for key, rows in photo_groups(con, school_id).items():
        selected, published = frame_choice(con, rows)
        if published:
            result.append({"id": key, "photos": [selected["id"]]})
    return result


def face_engine(server):
    if server.engine is None:
        from .faces import FaceEngine
        server.engine = FaceEngine()
    return server.engine


def group_pending(server, engine=None):
    """Group new teacher photos by face within their school, like pupils' portraits.

    Without the face models every photo stays in its own group; the photographer can move
    photos between groups by hand.
    """
    from .faces import choose_person
    if engine is None:
        try:
            engine = face_engine(server)
        except Exception:
            server.log.warning("Face models are missing: teacher photos are not grouped")
    while True:
        with server.db() as con:
            row = con.execute("SELECT * FROM teacher_photos WHERE status='pending' ORDER BY created_at, filename, id LIMIT 1").fetchone()
        if row is None:
            return
        vector = None
        if engine is not None:
            try:
                import cv2
                pixels = cv2.imread(str(server.DATA / "photos" / f"tphoto-{row['id']}.jpg"))
                if pixels is not None:
                    vector = engine.extract(pixels)[1]
            except Exception:
                server.log.exception("Teacher photo analysis failed: %s", row["id"])
        with server.db() as con:
            con.execute("BEGIN IMMEDIATE")
            if not con.execute("SELECT 1 FROM teacher_photos WHERE id=? AND status='pending'", (row["id"],)).fetchone():
                continue
            group = row["group_id"]
            if vector is not None:
                samples = {}
                for sample in con.execute("""SELECT group_id, embedding FROM teacher_photos
                        WHERE school_id=? AND shoot_id IS ? AND status='ready' AND embedding IS NOT NULL""", (row["school_id"], row["shoot_id"])):
                    samples.setdefault(sample["group_id"], []).append(json.loads(sample["embedding"]))
                match, _uncertain = choose_person(vector, samples, strong_match_threshold=0.93, join_threshold=0.75)
                group = match or group
            con.execute("UPDATE teacher_photos SET status='ready', group_id=?, embedding=? WHERE id=?",
                        (group, json.dumps(vector) if vector is not None else None, row["id"]))


def sign_photo(server, con, photo, teacher_id, by):
    """Keep source frames and the previous portrait so a photographer can undo a mistake."""
    teacher = con.execute("SELECT * FROM teachers WHERE id=? AND archived=0", (teacher_id,)).fetchone()
    if teacher is None or teacher["school_id"] != photo["school_id"]:
        raise HTTPException(422, "Учитель не найден в этой школе")
    if photo["status"] != "ready":
        raise HTTPException(409, "Дождитесь обработки фотографии или обновите список")
    stem = "teacher-" + server.uid()
    for suffix in PORTRAIT_SUFFIXES:
        source = server.DATA / "photos" / (f"tphoto-{photo['id']}" + suffix)
        if source.is_file():
            shutil.copyfile(source, server.DATA / "photos" / (stem + suffix))
    path, when = f"photos/{stem}.jpg", server.now()
    if not (server.DATA / path).is_file():
        raise HTTPException(404, "Исходная фотография не найдена")
    assignment_id = server.uid()
    con.execute("INSERT INTO teacher_assignments VALUES (?,?,?,?,?,?,?,?,?,0)",
                (assignment_id, photo["school_id"], teacher_id, photo["group_id"], path,
                 teacher["portrait_path"], teacher["portrait_by"], teacher["portrait_at"], when))
    con.execute("INSERT INTO teacher_frame_choices VALUES (?,?,0) ON CONFLICT(group_id) DO UPDATE SET photo_id=excluded.photo_id,published=0", (photo["group_id"], photo["id"]))
    con.execute("UPDATE teachers SET portrait_path=?, portrait_by=?, portrait_at=? WHERE id=?", (path, by, when, teacher_id))
    con.execute("UPDATE teacher_photos SET status='signed' WHERE school_id=? AND group_id=?", (photo["school_id"], photo["group_id"]))
    return assignment_id


def client_summary(con, order_id):
    """Short state for the client portal's status card."""
    school_id = order_school_id(con, order_id)
    available = len(school_teachers(con, school_id)) if school_id else 0
    picked = chosen(con, order_id)
    lead = next((row for row in picked if row["is_class_teacher"]), None)
    return {"available": available, "chosen": len(picked),
            "unsigned": len(client_groups(con, school_id)) if school_id else 0,
            "done": con.execute("SELECT 1 FROM order_teacher_state WHERE order_id=?", (order_id,)).fetchone() is not None,
            "class_teacher": full_name(lead) if lead else ""}


class SchoolInput(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=100)
    short_name: str = Field(default="", max_length=100)


class TeacherInput(BaseModel):
    last_name: str = Field(min_length=1, max_length=60)
    first_name: str = Field(default="", max_length=60)
    patronymic: str = Field(default="", max_length=60)
    subject: str = Field(default="", max_length=100)


class TeacherShootInput(BaseModel):
    title: str = Field(default="Учителя", min_length=1, max_length=100)
    shot_on: str = Field(default="", max_length=10)


class AssignInput(BaseModel):
    teacher_id: str | None = None
    teacher: TeacherInput | None = None


class MergeInput(BaseModel):
    target_id: str


class MoveInput(BaseModel):
    group_id: str | None = None


class ChoiceInput(BaseModel):
    teacher_ids: list[str] = Field(default_factory=list, max_length=300)
    class_teacher_id: str | None = None
    subjects: dict[str, str] = Field(default_factory=dict, max_length=300)


def install(app, s):
    def remove_portrait_files(path):
        if path:
            stem = path.rsplit("/", 1)[-1].removesuffix(".jpg")
            for suffix in PORTRAIT_SUFFIXES:
                (s.DATA / "photos" / (stem + suffix)).unlink(missing_ok=True)

    def remove_unused_portrait(path):
        if not path:
            return
        with s.db() as con:
            used = con.execute("SELECT 1 FROM teachers WHERE portrait_path=? UNION ALL SELECT 1 FROM teacher_assignments WHERE portrait_path=? OR previous_path=? LIMIT 1", (path, path, path)).fetchone()
        if not used:
            remove_portrait_files(path)

    def school_body(row, con):
        counts = con.execute("""SELECT
            (SELECT COUNT(*) FROM teachers WHERE school_id=? AND archived=0) AS teachers,
            (SELECT COUNT(*) FROM order_terms WHERE school_id=?) AS orders""", (row["id"], row["id"])).fetchone()
        return {"id": row["id"], "name": row["name"], "short_name": row["short_name"], "city": row["city"],
                "teacher_count": counts["teachers"], "order_count": counts["orders"],
                "previews": [teacher_view(t) for t in con.execute(
                    "SELECT * FROM teachers WHERE school_id=? AND archived=0 AND portrait_path!='' ORDER BY portrait_at DESC LIMIT 3", (row["id"],))]}

    def same_school(con, name, city, skip=None):
        for row in con.execute("SELECT * FROM schools WHERE studio_id=?", (mvp._studio(),)):
            if row["id"] != skip and row["name"].casefold() == name.casefold() and row["city"].casefold() == city.casefold():
                return row
        return None

    @app.get("/api/schools")
    def list_schools():
        with s.db() as con:
            rows = con.execute("SELECT * FROM schools WHERE studio_id=? ORDER BY name COLLATE NOCASE, city", (mvp._studio(),)).fetchall()
            return [school_body(row, con) for row in rows]

    @app.post("/api/schools", status_code=201)
    def create_school(payload: SchoolInput):
        name, city = clean(payload.name), clean(payload.city)
        if not name or not city:
            raise HTTPException(422, "Укажите название школы и город")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            # Creating a school that already exists selects it instead of adding a duplicate.
            existing = same_school(con, name, city)
            if existing is not None:
                return school_body(existing, con)
            school_id = s.uid()
            con.execute("INSERT INTO schools (id,studio_id,name,address,city,short_name) VALUES (?,?,?,?,?,?)",
                        (school_id, mvp._studio(), name, "", city, clean(payload.short_name)))
            return school_body(require_school(con, school_id), con)

    @app.get("/api/schools/{school_id}")
    def get_school(school_id: str):
        with s.db() as con:
            body = school_body(require_school(con, school_id), con)
            body["teachers"] = [teacher_view(row) for row in school_teachers(con, school_id)]
            body["archived_teachers"] = [teacher_view(row) for row in con.execute("SELECT * FROM teachers WHERE school_id=? AND archived=1", (school_id,))]
            body["orders"] = [dict(row) for row in con.execute("""SELECT o.id,o.class_name,o.graduation_year,o.stage FROM orders o
                JOIN order_terms t ON t.order_id=o.id WHERE t.school_id=? ORDER BY o.created_at DESC""", (school_id,))]
            return body

    @app.patch("/api/schools/{school_id}")
    def edit_school(school_id: str, payload: SchoolInput):
        name, city = clean(payload.name), clean(payload.city)
        if not name or not city:
            raise HTTPException(422, "Укажите название школы и город")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            require_school(con, school_id)
            if same_school(con, name, city, skip=school_id):
                raise HTTPException(409, "Такая школа уже есть в каталоге")
            con.execute("UPDATE schools SET name=?, city=?, short_name=? WHERE id=?", (name, city, clean(payload.short_name), school_id))
            con.execute("""UPDATE orders SET school=?,school_city=? WHERE stage NOT IN ('print','delivery','archive')
                AND id IN (SELECT order_id FROM order_terms WHERE school_id=?)""", (name, city, school_id))
            return school_body(require_school(con, school_id), con)

    @app.delete("/api/schools/{school_id}")
    def delete_school(school_id: str):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            require_school(con, school_id)
            if con.execute("SELECT 1 FROM order_terms WHERE school_id=?", (school_id,)).fetchone():
                raise HTTPException(409, "У школы есть заказы. Удалить можно только школу без заказов")
            paths = [row[0] for row in con.execute("SELECT portrait_path FROM teachers WHERE school_id=?", (school_id,))]
            paths += [f"photos/tphoto-{row[0]}.jpg" for row in con.execute("SELECT id FROM teacher_photos WHERE school_id=?", (school_id,))]
            paths += [r[0] for r in con.execute("SELECT portrait_path FROM teacher_assignments WHERE school_id=? UNION SELECT previous_path FROM teacher_assignments WHERE school_id=?", (school_id, school_id))]
            con.execute("DELETE FROM teacher_frame_choices WHERE group_id IN (SELECT group_id FROM teacher_photos WHERE school_id=?)", (school_id,))
            con.execute("DELETE FROM teacher_shoots WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM teacher_assignments WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM teacher_uploads WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM teacher_photos WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM teachers WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM schools WHERE id=?", (school_id,))
        for path in paths:
            remove_portrait_files(path)
        return {"ok": True}

    def insert_teacher(con, school_id, payload):
        values = [clean(v) for v in (payload.last_name, payload.first_name, payload.patronymic, payload.subject)]
        if not values[0]:
            raise HTTPException(422, "Укажите фамилию учителя")
        similar = [row for row in school_teachers(con, school_id)
                   if all(clean(row[key]).casefold().replace('ё','е') == value.casefold().replace('ё','е')
                          for key, value in zip(('last_name','first_name','patronymic'), values[:3]))]
        if similar:
            raise HTTPException(409, "Учитель с таким ФИО уже есть: " + full_name(similar[0]) + ". Выберите его из списка или уточните имя")
        teacher_id = s.uid()
        con.execute("""INSERT INTO teachers (id,school_id,last_name,first_name,patronymic,subject,defined,created_at)
            VALUES (?,?,?,?,?,?,1,?)""", (teacher_id, school_id, *values, s.now()))
        return teacher_id

    @app.post("/api/schools/{school_id}/teachers", status_code=201)
    def create_teacher(school_id: str, payload: TeacherInput):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            require_school(con, school_id)
            return teacher_view(require_teacher(con, insert_teacher(con, school_id, payload)))

    @app.patch("/api/teachers/{teacher_id}")
    def edit_teacher(teacher_id: str, payload: TeacherInput):
        values = [clean(v) for v in (payload.last_name, payload.first_name, payload.patronymic, payload.subject)]
        if not values[0]:
            raise HTTPException(422, "Укажите фамилию учителя")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            teacher = require_teacher(con, teacher_id)
            for other in school_teachers(con, teacher["school_id"]):
                if other["id"] != teacher_id and all(clean(other[key]).casefold().replace('ё','е') == value.casefold().replace('ё','е')
                        for key, value in zip(('last_name','first_name','patronymic'), values[:3])):
                    raise HTTPException(409, "Учитель с таким ФИО уже есть. Объедините карточки или уточните имя")
            con.execute("UPDATE teachers SET last_name=?, first_name=?, patronymic=?, subject=? WHERE id=?", (*values, teacher_id))
            return teacher_view(require_teacher(con, teacher_id))

    @app.delete("/api/teachers/{teacher_id}")
    def delete_teacher(teacher_id: str):
        """Albums that already chose the teacher keep them; the catalogue and new choices do not."""
        with s.db() as con:
            teacher = require_teacher(con, teacher_id)
            con.execute("UPDATE teachers SET archived=1 WHERE id=?", (teacher_id,))
        return {"ok": True, "archived": True}

    @app.post("/api/teachers/{teacher_id}/restore")
    def restore_teacher(teacher_id: str):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            row = require_teacher(con, teacher_id, include_archived=True)
            for other in school_teachers(con, row["school_id"]):
                if other["id"] != teacher_id and full_name(other).casefold().replace('ё','е') == full_name(row).casefold().replace('ё','е'):
                    raise HTTPException(409, "Учитель с таким ФИО уже есть. Объедините карточки")
            con.execute("UPDATE teachers SET archived=0 WHERE id=?", (teacher_id,))
        return {"ok": True}

    @app.post("/api/teachers/{teacher_id}/merge")
    def merge_teacher(teacher_id: str, payload: MergeInput):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            source = require_teacher(con, teacher_id, include_archived=True)
            target = require_teacher(con, payload.target_id)
            if source["id"] == target["id"] or source["school_id"] != target["school_id"]:
                raise HTTPException(422, "Выберите другую карточку учителя этой школы")
            links = con.execute("SELECT ot.*,o.stage FROM order_teachers ot JOIN orders o ON o.id=ot.order_id WHERE ot.teacher_id=?", (teacher_id,)).fetchall()
            if any(row["stage"] in LOCKED_STAGES for row in links):
                raise HTTPException(409, "Карточка используется в печати или архиве. Сохраните её отдельно")
            for row in links:
                existing = con.execute("SELECT * FROM order_teachers WHERE order_id=? AND teacher_id=?", (row["order_id"], target["id"])).fetchone()
                if existing:
                    con.execute("UPDATE order_teachers SET is_class_teacher=MAX(is_class_teacher,?),position=MIN(position,?) WHERE order_id=? AND teacher_id=?",
                                (row["is_class_teacher"], row["position"], row["order_id"], target["id"]))
                    con.execute("DELETE FROM order_teachers WHERE order_id=? AND teacher_id=?", (row["order_id"], teacher_id))
                else:
                    con.execute("UPDATE order_teachers SET teacher_id=? WHERE order_id=? AND teacher_id=?", (target["id"], row["order_id"], teacher_id))
            if not target["portrait_path"] and source["portrait_path"]:
                stem = "teacher-" + s.uid()
                old = source["portrait_path"].rsplit("/", 1)[-1].removesuffix(".jpg")
                for suffix in PORTRAIT_SUFFIXES:
                    path = s.DATA / "photos" / (old + suffix)
                    if path.is_file():
                        shutil.copyfile(path, s.DATA / "photos" / (stem + suffix))
                con.execute("UPDATE teachers SET portrait_path=?,portrait_by=?,portrait_at=? WHERE id=?",
                            (f"photos/{stem}.jpg", source["portrait_by"], source["portrait_at"], target["id"]))
            con.execute("UPDATE teachers SET archived=1 WHERE id=?", (teacher_id,))
            return teacher_view(require_teacher(con, target["id"]))

    @app.post("/api/teacher-assignments/{assignment_id}/undo")
    def undo_assignment(assignment_id: str):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            event = con.execute("SELECT * FROM teacher_assignments WHERE id=?", (assignment_id,)).fetchone()
            if not event:
                raise HTTPException(404, "Подпись не найдена")
            require_school(con, event["school_id"])
            teacher = require_teacher(con, event["teacher_id"], include_archived=True)
            if event["undone"] or teacher["portrait_path"] != event["portrait_path"]:
                raise HTTPException(409, "Портрет уже изменён. Отменить можно только актуальную подпись")
            con.execute("UPDATE teachers SET portrait_path=?,portrait_by=?,portrait_at=? WHERE id=?",
                        (event["previous_path"], event["previous_by"], event["previous_at"], teacher["id"]))
            con.execute("UPDATE teacher_photos SET status='ready' WHERE school_id=? AND group_id=? AND status='signed'", (event["school_id"], event["group_id"]))
            con.execute("DELETE FROM teacher_frame_choices WHERE group_id=?", (event["group_id"],))
            con.execute("UPDATE teacher_assignments SET undone=1 WHERE id=?", (assignment_id,))
        return {"ok": True}

    @app.put("/api/teachers/{teacher_id}/portrait")
    async def upload_portrait(teacher_id: str, request: Request):
        with s.db() as con:
            require_teacher(con, teacher_id)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > s.MAX_BYTES:
                raise HTTPException(413, "Файл больше 30 МБ")
        if not body:
            raise HTTPException(422, "Выберите файл портрета")
        stem = "teacher-" + s.uid()
        s.prepare_photo_files(bytes(body), stem)
        with s.db() as con:
            try:
                teacher = require_teacher(con, teacher_id)
            except HTTPException:
                remove_portrait_files(f"photos/{stem}.jpg")
                raise
            con.execute("UPDATE teachers SET portrait_path=?, portrait_by='photographer',portrait_at=? WHERE id=?", (f"photos/{stem}.jpg", s.now(), teacher_id))
            con.execute("INSERT OR IGNORE INTO teacher_uploads VALUES (?,?,?)", (teacher["school_id"], hashlib.sha256(body).hexdigest(), teacher_id))
            fresh = teacher_view(require_teacher(con, teacher_id))
        remove_unused_portrait(teacher["portrait_path"])
        return fresh

    @app.delete("/api/teachers/{teacher_id}/portrait")
    def delete_portrait(teacher_id: str):
        with s.db() as con:
            teacher = require_teacher(con, teacher_id)
            con.execute("UPDATE teachers SET portrait_path='', portrait_by='',portrait_at='' WHERE id=?", (teacher_id,))
        remove_unused_portrait(teacher["portrait_path"])
        return {"ok": True}

    def portrait_file(teacher, variant):
        if variant not in {"thumb", "full"} or not teacher["portrait_path"]:
            raise HTTPException(404, "Портрет не найден")
        stem = teacher["portrait_path"].rsplit("/", 1)[-1].removesuffix(".jpg")
        path = s.DATA / "photos" / (stem + (".thumb.jpg" if variant == "thumb" else ".jpg"))
        if not path.is_file():
            raise HTTPException(404, "Портрет не найден")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/teachers/{teacher_id}/portrait/{variant}")
    def portrait(teacher_id: str, variant: str):
        with s.db() as con:
            teacher = require_teacher(con, teacher_id, include_archived=True)
        return portrait_file(teacher, variant)

    # Unsorted teacher photos: uploaded from the catalogue or from an order of the school,
    # then each one is given to a teacher and becomes that teacher's portrait.
    def photo_view(row):
        return {"id": row["id"], "filename": row["filename"], "order_id": row["order_id"], "created_at": row["created_at"],
                "status": row["status"], "group_id": row["group_id"], "shoot_id": row["shoot_id"]}

    def require_photo(con, photo_id, include_signed=False):
        row = con.execute("""SELECT p.* FROM teacher_photos p JOIN schools s ON s.id=p.school_id
            WHERE p.id=? AND s.studio_id=? AND (p.status!='signed' OR ?)""", (photo_id, mvp._studio(), include_signed)).fetchone()
        if row is None:
            raise HTTPException(404, "Фотография не найдена")
        return row

    @app.get("/api/schools/{school_id}/teacher-photos")
    def teacher_photos(school_id: str):
        with s.db() as con:
            require_school(con, school_id)
            groups = photo_groups(con, school_id)
            signed = {}
            for row in con.execute("SELECT * FROM teacher_photos WHERE school_id=? AND status='signed' ORDER BY created_at", (school_id,)):
                signed.setdefault(row["group_id"], []).append(row)
            signed_groups = []
            for key, rows in signed.items():
                assignment = con.execute("SELECT a.*,t.last_name,t.first_name,t.patronymic FROM teacher_assignments a JOIN teachers t ON t.id=a.teacher_id WHERE a.group_id=? AND a.undone=0 ORDER BY a.created_at DESC LIMIT 1", (key,)).fetchone()
                choice = con.execute("SELECT photo_id FROM teacher_frame_choices WHERE group_id=?", (key,)).fetchone()
                signed_groups.append({"id": key, "photos": [photo_view(r) for r in rows], "signed": True,
                                      "selected_photo_id": choice[0] if choice else rows[0]["id"],
                                      "teacher_id": assignment["teacher_id"] if assignment else None,
                                      "name": full_name(assignment) if assignment else "Учитель"})
            return {"signed_groups": signed_groups, "groups": [{"id": key, "photos": [photo_view(row) for row in rows],
                                "selected_photo_id": frame_choice(con, rows)[0]["id"] if frame_choice(con, rows)[0] else None,
                                "published": frame_choice(con, rows)[1]} for key, rows in groups.items()],
                    "shoots": [dict(r) for r in con.execute("""SELECT ts.*,
                      (SELECT COUNT(*) FROM teacher_photos WHERE shoot_id=ts.id) AS photo_count,
                      (SELECT id FROM teacher_photos WHERE shoot_id=ts.id ORDER BY created_at LIMIT 1) AS preview_id
                      FROM teacher_shoots ts WHERE school_id=? ORDER BY created_at DESC""", (school_id,))],
                    "pending": sum(row["status"] == "pending" for rows in groups.values() for row in rows),
                    "assignments": [dict(row) for row in con.execute("""SELECT a.id,a.created_at,t.last_name,t.first_name,t.patronymic
                        FROM teacher_assignments a JOIN teachers t ON t.id=a.teacher_id
                        WHERE a.school_id=? AND a.undone=0 AND a.portrait_path=t.portrait_path
                        ORDER BY a.created_at DESC LIMIT 20""", (school_id,))]}

    @app.post("/api/schools/{school_id}/teacher-shoots", status_code=201)
    def create_teacher_shoot(school_id: str, payload: TeacherShootInput):
        title = clean(payload.title)
        if not title:
            raise HTTPException(422, "Укажите название съёмки")
        if payload.shot_on:
            from datetime import date
            try:
                date.fromisoformat(payload.shot_on)
            except ValueError:
                raise HTTPException(422, "Некорректная дата съёмки")
        with s.db() as con:
            require_school(con, school_id)
            shoot_id = s.uid()
            con.execute("INSERT INTO teacher_shoots VALUES (?,?,?,?,?)", (shoot_id, school_id, title, payload.shot_on, s.now()))
            return dict(con.execute("SELECT * FROM teacher_shoots WHERE id=?", (shoot_id,)).fetchone())

    @app.patch("/api/schools/{school_id}/teacher-shoots/{shoot_id}")
    def edit_teacher_shoot(school_id: str, shoot_id: str, payload: TeacherShootInput):
        title = clean(payload.title)
        if not title:
            raise HTTPException(422, "Укажите название съёмки")
        if payload.shot_on:
            from datetime import date
            try:
                date.fromisoformat(payload.shot_on)
            except ValueError:
                raise HTTPException(422, "Некорректная дата съёмки")
        with s.db() as con:
            require_school(con, school_id)
            if not con.execute("SELECT 1 FROM teacher_shoots WHERE school_id=? AND id=?", (school_id, shoot_id)).fetchone():
                raise HTTPException(404, "Съёмка не найдена")
            con.execute("UPDATE teacher_shoots SET title=?,shot_on=? WHERE id=?", (title, payload.shot_on, shoot_id))
        return {"ok": True}

    @app.post("/api/teacher-photos/{photo_id}/select")
    def select_teacher_frame(photo_id: str):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            photo = require_photo(con, photo_id, include_signed=True)
            if photo["status"] == "signed":
                event = con.execute("SELECT teacher_id FROM teacher_assignments WHERE group_id=? AND undone=0 ORDER BY created_at DESC LIMIT 1", (photo["group_id"],)).fetchone()
                if event is None:
                    raise HTTPException(409, "Не найдена карточка учителя")
                con.execute("UPDATE teacher_photos SET status='ready' WHERE school_id=? AND group_id=?", (photo["school_id"], photo["group_id"]))
                photo = require_photo(con, photo_id)
                sign_photo(s, con, photo, event["teacher_id"], "photographer")
                return {"ok": True}
            if photo["status"] != "ready":
                raise HTTPException(409, "Дождитесь обработки фотографии")
            con.execute("INSERT INTO teacher_frame_choices VALUES (?,?,0) ON CONFLICT(group_id) DO UPDATE SET photo_id=excluded.photo_id,published=0", (photo["group_id"], photo_id))
        return {"ok": True}

    @app.post("/api/schools/{school_id}/teacher-photos/publish")
    def publish_teacher_frames(school_id: str):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            require_school(con, school_id)
            released = 0
            for group_id, rows in photo_groups(con, school_id).items():
                selected, published = frame_choice(con, rows)
                if selected and not published and all(r["status"] == "ready" for r in rows):
                    con.execute("INSERT INTO teacher_frame_choices VALUES (?,?,1) ON CONFLICT(group_id) DO UPDATE SET photo_id=excluded.photo_id,published=1", (group_id, selected["id"]))
                    released += 1
            return {"published": released}

    @app.post("/api/schools/{school_id}/teacher-photos", status_code=201)
    async def upload_teacher_photo(school_id: str, request: Request, filename: str, order_id: str | None = None, shoot_id: str | None = None):
        if len(filename) > 240 or not filename.strip():
            raise HTTPException(422, "Некорректное имя файла")
        with s.db() as con:
            require_school(con, school_id)
            if shoot_id and not con.execute("SELECT 1 FROM teacher_shoots WHERE id=? AND school_id=?", (shoot_id, school_id)).fetchone():
                raise HTTPException(422, "Съёмка относится к другой школе")
            if order_id:
                s.require_order(con, order_id)
                if order_school_id(con, order_id) != school_id:
                    raise HTTPException(422, "Заказ относится к другой школе")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > s.MAX_BYTES:
                raise HTTPException(413, "Файл больше 30 МБ")
        sha = hashlib.sha256(body).hexdigest()
        with s.db() as con:
            existing = con.execute("SELECT id FROM teacher_uploads WHERE school_id=? AND sha=?", (school_id, sha)).fetchone()
            if existing:
                if order_id:
                    upload_runs.arrived(con, order_id)
                return {"id": existing["id"], "duplicate": True}
        photo_id = s.uid()
        s.prepare_photo_files(bytes(body), "tphoto-" + photo_id)
        with s.db() as con:
            try:
                con.execute("BEGIN IMMEDIATE")
                require_school(con, school_id)
                con.execute("INSERT INTO teacher_uploads VALUES (?,?,?)", (school_id, sha, photo_id))
                con.execute("""INSERT INTO teacher_photos (id,school_id,order_id,filename,sha,created_at,group_id,status,shoot_id)
                    VALUES (?,?,?,?,?,?,?,'pending',?)""", (photo_id, school_id, order_id, Path(filename).name, sha, s.now(), photo_id, shoot_id))
                if order_id:
                    upload_runs.arrived(con, order_id)
            except sqlite3.IntegrityError:
                con.rollback()
                remove_portrait_files(f"photos/tphoto-{photo_id}.jpg")
                existing = con.execute("SELECT id FROM teacher_uploads WHERE school_id=? AND sha=?", (school_id, sha)).fetchone()
                if existing is None:
                    raise
                if order_id:
                    upload_runs.arrived(con, order_id)
                return {"id": existing["id"], "duplicate": True}
            except Exception:
                remove_portrait_files(f"photos/tphoto-{photo_id}.jpg")
                raise
        s.executor.submit(group_pending, s)
        return {"id": photo_id, "duplicate": False}

    @app.get("/api/teacher-photos/{photo_id}/{variant}")
    def teacher_photo_file(photo_id: str, variant: str):
        if variant not in {"thumb", "full"}:
            raise HTTPException(404, "Фотография не найдена")
        with s.db() as con:
            require_photo(con, photo_id, include_signed=True)
        path = s.DATA / "photos" / (f"tphoto-{photo_id}" + (".thumb.jpg" if variant == "thumb" else ".jpg"))
        if not path.is_file():
            raise HTTPException(404, "Фотография не найдена")
        return FileResponse(path, media_type="image/jpeg")

    @app.delete("/api/teacher-photos/{photo_id}")
    def delete_teacher_photo(photo_id: str):
        with s.db() as con:
            photo = require_photo(con, photo_id)
            con.execute("DELETE FROM teacher_frame_choices WHERE group_id=?", (photo["group_id"],))
            con.execute("DELETE FROM teacher_uploads WHERE id=?", (photo_id,))
            con.execute("DELETE FROM teacher_photos WHERE id=?", (photo_id,))
        remove_portrait_files(f"photos/tphoto-{photo_id}.jpg")
        return {"ok": True}

    @app.post("/api/teacher-photos/{photo_id}/assign")
    def assign_teacher_photo(photo_id: str, payload: AssignInput):
        """The photo becomes the teacher's portrait (replacing an old one); its group leaves the unsigned queue."""
        if bool(payload.teacher_id) == bool(payload.teacher):
            raise HTTPException(422, "Выберите учителя или добавьте нового")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            photo = require_photo(con, photo_id, include_signed=True)
            if photo["status"] == "signed":
                con.execute("UPDATE teacher_photos SET status='ready' WHERE school_id=? AND group_id=?", (photo["school_id"], photo["group_id"]))
                photo = require_photo(con, photo_id)
            teacher_id = insert_teacher(con, photo["school_id"], payload.teacher) if payload.teacher else payload.teacher_id
            require_teacher(con, teacher_id)
            assignment_id = sign_photo(s, con, photo, teacher_id, "photographer")
            fresh = teacher_view(require_teacher(con, teacher_id))
        fresh["assignment_id"] = assignment_id
        return fresh

    @app.post("/api/teacher-photos/{photo_id}/move")
    def move_teacher_photo(photo_id: str, payload: MoveInput):
        """Fix face grouping: join another group, or stand alone when group_id is empty."""
        with s.db() as con:
            photo = require_photo(con, photo_id)
            if photo["status"] != "ready":
                raise HTTPException(409, "Дождитесь обработки фотографии")
            group = payload.group_id or s.uid()
            if payload.group_id and not con.execute("SELECT 1 FROM teacher_photos WHERE school_id=? AND group_id=? AND shoot_id IS ? AND status='ready'",
                                                    (photo["school_id"], group, photo["shoot_id"])).fetchone():
                raise HTTPException(404, "Группа не найдена")
            con.execute("DELETE FROM teacher_frame_choices WHERE group_id IN (?,?)", (photo["group_id"], group))
            con.execute("UPDATE teacher_photos SET group_id=? WHERE id=?", (group, photo_id))
        return {"group_id": group}

    @app.get("/api/orders/{order_id}/teachers")
    def order_teachers(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            return order_teachers_body(con, order_id)

    @app.put("/api/orders/{order_id}/teachers")
    def choose_teachers(order_id: str, payload: ChoiceInput):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            s.require_order(con, order_id)
            save_order_teachers(con, order_id, payload.teacher_ids, payload.class_teacher_id, "photographer", s.now(), payload.subjects)
            return order_teachers_body(con, order_id)

    @app.get("/client-api/{token}/teachers")
    def client_teachers(token: str, request: Request):
        with s.db() as con:
            order = mvp._order_by_token(con, token)
            mvp.require_level(con, request, order["id"], "entry")
            return order_teachers_body(con, order["id"], public=True)

    @app.put("/client-api/{token}/teachers")
    def client_choose(token: str, payload: ChoiceInput, request: Request):
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            order = mvp._order_by_token(con, token)
            mvp.require_level(con, request, order["id"], "manage")
            save_order_teachers(con, order["id"], payload.teacher_ids, payload.class_teacher_id, "client", s.now(), payload.subjects)
            return order_teachers_body(con, order["id"], public=True)

    def client_photo(con, token, request, photo_id):
        order = mvp._order_by_token(con, token)
        mvp.require_level(con, request, order["id"], "entry")
        photo = con.execute("SELECT * FROM teacher_photos WHERE id=? AND status='ready' AND school_id IS ?",
                            (photo_id, order_school_id(con, order["id"]))).fetchone()
        if photo is not None:
            rows = con.execute("SELECT * FROM teacher_photos WHERE school_id=? AND group_id=? AND status!='signed'", (photo["school_id"], photo["group_id"])).fetchall()
            selected, published = frame_choice(con, rows)
            if not published or selected["id"] != photo_id:
                photo = None
        if photo is None:
            raise HTTPException(404, "Фотография уже подписана или удалена. Обновите страницу.")
        return photo

    @app.get("/client-api/{token}/teacher-photos")
    def client_teacher_photos(token: str, request: Request):
        with s.db() as con:
            order = mvp._order_by_token(con, token)
            mvp.require_level(con, request, order["id"], "entry")
            school_id = order_school_id(con, order["id"])
            if school_id is None:
                return {"groups": [], "teachers": []}
            groups = client_groups(con, school_id)
            waiting = [{"id": row["id"], "name": full_name(row), "subject": row["subject"]}
                       for row in school_teachers(con, school_id) if not row["portrait_path"]]
            return {"groups": groups, "teachers": waiting}

    @app.get("/client-api/{token}/teacher-photos/{photo_id}/{variant}")
    def client_teacher_photo_file(token: str, photo_id: str, variant: str, request: Request):
        if variant not in {"thumb", "full"}:
            raise HTTPException(404, "Фотография не найдена")
        with s.db() as con:
            client_photo(con, token, request, photo_id)
        path = s.DATA / "photos" / (f"tphoto-{photo_id}" + (".thumb.jpg" if variant == "thumb" else ".jpg"))
        if not path.is_file():
            raise HTTPException(404, "Фотография не найдена")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/client-api/{token}/teacher-photos/{photo_id}/sign")
    def client_sign(token: str, photo_id: str, payload: AssignInput, request: Request):
        """A pupil or the teacher signs a teacher who has no portrait yet. Replacing is the photographer's job."""
        if bool(payload.teacher_id) == bool(payload.teacher):
            raise HTTPException(422, "Выберите учителя или впишите его имя")
        if payload.teacher and not clean(payload.teacher.first_name):
            raise HTTPException(422, "Укажите имя и фамилию учителя")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            photo = client_photo(con, token, request, photo_id)
            if payload.teacher:
                teacher_id = insert_teacher(con, photo["school_id"], payload.teacher)
            else:
                teacher_id = payload.teacher_id
                teacher = con.execute("SELECT portrait_path FROM teachers WHERE id=? AND school_id=? AND archived=0",
                                      (teacher_id, photo["school_id"])).fetchone()
                if teacher is None:
                    raise HTTPException(422, "Учитель не найден в этой школе")
                if teacher["portrait_path"]:
                    raise HTTPException(409, "У этого учителя уже есть фото. Заменить его может фотограф")
            sign_photo(s, con, photo, teacher_id, "client")
            teacher = con.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)).fetchone()
        return {"id": teacher_id, "name": full_name(teacher)}

    @app.get("/client-api/{token}/teachers/{teacher_id}/portrait")
    def client_portrait(token: str, teacher_id: str, request: Request):
        with s.db() as con:
            order = mvp._order_by_token(con, token)
            mvp.require_level(con, request, order["id"], "entry")
            school_id = order_school_id(con, order["id"])
            teacher = con.execute("""SELECT * FROM teachers WHERE id=? AND school_id IS ? AND
                (archived=0 OR EXISTS(SELECT 1 FROM order_teachers WHERE order_id=? AND teacher_id=teachers.id))""",
                                  (teacher_id, school_id, order["id"])).fetchone()
            if teacher is None or school_id is None:
                raise HTTPException(404, "Портрет не найден")
        return portrait_file(teacher, "thumb")
