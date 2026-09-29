"""Studio school catalogue: schools, their teachers and the teachers chosen for each class album.

Every school belongs to one studio. Teachers belong to a school and are reused across that
school's orders, so a portrait taken once keeps working in later albums. The class chooses
which teachers appear in its album and who is the class teacher; the photographer can do the
same from the order page. Nothing here is shared between studios.

Teacher photos arrive unsigned and are grouped by face like pupils' portraits. Anyone in the
class (or the teacher with the class entry code) picks the best frame of a teacher who has no
portrait yet and signs the name; the rest of that group is deleted. The photographer can
replace a portrait later.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import mvp, order_stages

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
    schools = {r[1] for r in con.execute("PRAGMA table_info(schools)")}
    if "city" not in schools:
        con.execute("ALTER TABLE schools ADD COLUMN city TEXT NOT NULL DEFAULT ''")
    teachers = {r[1] for r in con.execute("PRAGMA table_info(teachers)")}
    for column, kind in (("patronymic", "TEXT NOT NULL DEFAULT ''"), ("subject", "TEXT NOT NULL DEFAULT ''"),
                         ("archived", "INTEGER NOT NULL DEFAULT 0"), ("created_at", "TEXT NOT NULL DEFAULT ''"),
                         ("portrait_by", "TEXT NOT NULL DEFAULT ''")):
        if column not in teachers:
            con.execute(f"ALTER TABLE teachers ADD COLUMN {column} {kind}")
    photos = {r[1] for r in con.execute("PRAGMA table_info(teacher_photos)")}
    for column, kind in (("group_id", "TEXT"), ("status", "TEXT NOT NULL DEFAULT 'ready'"), ("embedding", "TEXT")):
        if column not in photos:
            con.execute(f"ALTER TABLE teacher_photos ADD COLUMN {column} {kind}")
    con.execute("UPDATE teacher_photos SET group_id=id WHERE group_id IS NULL")


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
            "name": full_name(row), "has_portrait": bool(row["portrait_path"]), "portrait_by": row["portrait_by"],
            "portrait_version": row["portrait_path"].rsplit("/", 1)[-1].split(".")[0] if row["portrait_path"] else ""}


def require_school(con, school_id):
    row = con.execute("SELECT * FROM schools WHERE id=? AND studio_id=?", (school_id, mvp._studio())).fetchone()
    if row is None:
        raise HTTPException(404, "Школа не найдена")
    return row


def require_teacher(con, teacher_id):
    row = con.execute("""SELECT t.* FROM teachers t JOIN schools s ON s.id=t.school_id
        WHERE t.id=? AND s.studio_id=? AND t.archived=0""", (teacher_id, mvp._studio())).fetchone()
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
    return con.execute("""SELECT t.*, ot.is_class_teacher FROM order_teachers ot
        JOIN teachers t ON t.id=ot.teacher_id WHERE ot.order_id=?
        ORDER BY ot.is_class_teacher DESC, ot.position, t.id""", (order_id,)).fetchall()


def order_teachers_body(con, order_id, public=False):
    school_id = order_school_id(con, order_id)
    school = con.execute("SELECT id,name,city FROM schools WHERE id=?", (school_id,)).fetchone() if school_id else None
    selected = {row["id"]: bool(row["is_class_teacher"]) for row in chosen(con, order_id)}
    teachers = []
    for row in (school_teachers(con, school_id) if school else []):
        item = teacher_view(row)
        item.update(selected=row["id"] in selected, is_class_teacher=selected.get(row["id"], False))
        teachers.append(item)
    stage = con.execute("SELECT stage FROM orders WHERE id=?", (order_id,)).fetchone()
    state = con.execute("SELECT updated_at, updated_by FROM order_teacher_state WHERE order_id=?", (order_id,)).fetchone()
    body = {"school": dict(school) if school else None, "teachers": teachers,
            "class_teacher_id": next((key for key, lead in selected.items() if lead), None),
            "chosen": state is not None, "locked": bool(stage and stage["stage"] in LOCKED_STAGES)}
    if not public:
        layout = con.execute("SELECT generated_at FROM order_layouts WHERE order_id=?", (order_id,)).fetchone()
        body.update(updated_at=state["updated_at"] if state else None, updated_by=state["updated_by"] if state else None,
                    unsigned_groups=unsigned_groups(con, school_id) if school else 0,
                    layout_outdated=bool(state and layout and state["updated_at"] > layout["generated_at"]))
    return body


def save_order_teachers(con, order_id, teacher_ids, class_teacher_id, who, when):
    stage = con.execute("SELECT stage FROM orders WHERE id=?", (order_id,)).fetchone()
    if stage and stage["stage"] in LOCKED_STAGES:
        raise HTTPException(409, "Заказ уже отправлен в печать. Состав учителей изменить нельзя")
    school_id = order_school_id(con, order_id)
    if school_id is None:
        raise HTTPException(409, "Фотограф ещё не выбрал школу из каталога")
    ids = list(dict.fromkeys(teacher_ids))
    known = {row["id"] for row in school_teachers(con, school_id)}
    if any(teacher_id not in known for teacher_id in ids):
        raise HTTPException(422, "Учитель не найден в этой школе")
    if class_teacher_id and class_teacher_id not in ids:
        raise HTTPException(422, "Классный руководитель должен быть среди выбранных учителей")
    con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
    con.executemany("INSERT INTO order_teachers VALUES (?,?,?,?)", [
        (order_id, teacher_id, index, int(teacher_id == class_teacher_id)) for index, teacher_id in enumerate(ids)])
    con.execute("""INSERT INTO order_teacher_state VALUES (?,?,?) ON CONFLICT(order_id)
        DO UPDATE SET updated_at=excluded.updated_at, updated_by=excluded.updated_by""", (order_id, when, who))


def snapshot_teachers(con, order_id):
    """Teacher records for the layout snapshot, in album order."""
    return [{"id": row["id"], "first_name": row["first_name"], "last_name": row["last_name"],
             "patronymic": row["patronymic"], "school_subject": row["subject"],
             "is_class_teacher": bool(row["is_class_teacher"]), "portrait_path": row["portrait_path"]}
            for row in chosen(con, order_id)]


def unsigned_groups(con, school_id, ready_only=False):
    return con.execute(f"""SELECT COUNT(DISTINCT group_id) FROM teacher_photos
        WHERE school_id=? {"AND status='ready'" if ready_only else ''}""", (school_id,)).fetchone()[0]


def photo_groups(con, school_id, ready_only=False):
    """Unsigned photos by teacher group, in upload order."""
    groups = {}
    for row in con.execute(f"""SELECT * FROM teacher_photos WHERE school_id=? {"AND status='ready'" if ready_only else ''}
            ORDER BY created_at, filename, id""", (school_id,)):
        groups.setdefault(row["group_id"], []).append(row)
    return groups


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
                        WHERE school_id=? AND status='ready' AND embedding IS NOT NULL""", (row["school_id"],)):
                    samples.setdefault(sample["group_id"], []).append(json.loads(sample["embedding"]))
                match, _uncertain = choose_person(vector, samples, strong_match_threshold=0.93, join_threshold=0.75)
                group = match or group
            con.execute("UPDATE teacher_photos SET status='ready', group_id=?, embedding=? WHERE id=?",
                        (group, json.dumps(vector) if vector is not None else None, row["id"]))


def sign_photo(server, con, photo, teacher_id, by):
    """The photo becomes the teacher's portrait; the rest of its group is no longer needed.

    Returns file paths to delete once the transaction is committed.
    """
    teacher = con.execute("SELECT * FROM teachers WHERE id=? AND archived=0", (teacher_id,)).fetchone()
    if teacher is None or teacher["school_id"] != photo["school_id"]:
        raise HTTPException(422, "Учитель не найден в этой школе")
    stem = "teacher-" + server.uid()
    for suffix in PORTRAIT_SUFFIXES:
        source = server.DATA / "photos" / (f"tphoto-{photo['id']}" + suffix)
        if source.is_file():
            source.rename(server.DATA / "photos" / (stem + suffix))
    con.execute("UPDATE teachers SET portrait_path=?, portrait_by=? WHERE id=?", (f"photos/{stem}.jpg", by, teacher_id))
    siblings = [row["id"] for row in con.execute(
        "SELECT id FROM teacher_photos WHERE school_id=? AND group_id=? AND id<>?", (photo["school_id"], photo["group_id"], photo["id"]))]
    con.execute("DELETE FROM teacher_photos WHERE school_id=? AND group_id=?", (photo["school_id"], photo["group_id"]))
    return [teacher["portrait_path"]] + [f"photos/tphoto-{sibling}.jpg" for sibling in siblings]


def client_summary(con, order_id):
    """Short state for the client portal's status card."""
    school_id = order_school_id(con, order_id)
    available = len(school_teachers(con, school_id)) if school_id else 0
    picked = chosen(con, order_id)
    lead = next((row for row in picked if row["is_class_teacher"]), None)
    return {"available": available, "chosen": len(picked),
            "unsigned": unsigned_groups(con, school_id, ready_only=True) if school_id else 0,
            "done": con.execute("SELECT 1 FROM order_teacher_state WHERE order_id=?", (order_id,)).fetchone() is not None,
            "class_teacher": full_name(lead) if lead else ""}


class SchoolInput(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    city: str = Field(default="", max_length=100)


class TeacherInput(BaseModel):
    last_name: str = Field(min_length=1, max_length=60)
    first_name: str = Field(default="", max_length=60)
    patronymic: str = Field(default="", max_length=60)
    subject: str = Field(default="", max_length=100)


class AssignInput(BaseModel):
    teacher_id: str | None = None
    teacher: TeacherInput | None = None


class MoveInput(BaseModel):
    group_id: str | None = None


class ChoiceInput(BaseModel):
    teacher_ids: list[str] = Field(default_factory=list, max_length=300)
    class_teacher_id: str | None = None


def install(app, s):
    def remove_portrait_files(path):
        if path:
            stem = path.rsplit("/", 1)[-1].removesuffix(".jpg")
            for suffix in PORTRAIT_SUFFIXES:
                (s.DATA / "photos" / (stem + suffix)).unlink(missing_ok=True)

    def school_body(row, con):
        counts = con.execute("""SELECT
            (SELECT COUNT(*) FROM teachers WHERE school_id=? AND archived=0) AS teachers,
            (SELECT COUNT(*) FROM order_terms WHERE school_id=?) AS orders""", (row["id"], row["id"])).fetchone()
        return {"id": row["id"], "name": row["name"], "city": row["city"],
                "teacher_count": counts["teachers"], "order_count": counts["orders"]}

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
        if not name:
            raise HTTPException(422, "Укажите полное название школы")
        with s.db() as con:
            # Creating a school that already exists selects it instead of adding a duplicate.
            existing = same_school(con, name, city)
            if existing is None and not city:
                existing = next((row for row in con.execute("SELECT * FROM schools WHERE studio_id=?", (mvp._studio(),))
                                 if row["name"].casefold() == name.casefold()), None)
            if existing is not None:
                return school_body(existing, con)
            school_id = s.uid()
            con.execute("INSERT INTO schools (id,studio_id,name,address,city) VALUES (?,?,?,?,?)",
                        (school_id, mvp._studio(), name, "", city))
            return school_body(require_school(con, school_id), con)

    @app.get("/api/schools/{school_id}")
    def get_school(school_id: str):
        with s.db() as con:
            body = school_body(require_school(con, school_id), con)
            body["teachers"] = [teacher_view(row) for row in school_teachers(con, school_id)]
            return body

    @app.patch("/api/schools/{school_id}")
    def edit_school(school_id: str, payload: SchoolInput):
        name, city = clean(payload.name), clean(payload.city)
        if not name:
            raise HTTPException(422, "Укажите полное название школы")
        with s.db() as con:
            require_school(con, school_id)
            if same_school(con, name, city, skip=school_id):
                raise HTTPException(409, "Такая школа уже есть в каталоге")
            con.execute("UPDATE schools SET name=?, city=? WHERE id=?", (name, city, school_id))
            con.execute("""UPDATE orders SET school=? WHERE id IN (SELECT order_id FROM order_terms WHERE school_id=?)""",
                        (name, school_id))
            return school_body(require_school(con, school_id), con)

    @app.delete("/api/schools/{school_id}")
    def delete_school(school_id: str):
        with s.db() as con:
            require_school(con, school_id)
            if con.execute("SELECT 1 FROM order_terms WHERE school_id=?", (school_id,)).fetchone():
                raise HTTPException(409, "У школы есть заказы. Удалить можно только школу без заказов")
            paths = [row[0] for row in con.execute("SELECT portrait_path FROM teachers WHERE school_id=?", (school_id,))]
            paths += [f"photos/tphoto-{row[0]}.jpg" for row in con.execute("SELECT id FROM teacher_photos WHERE school_id=?", (school_id,))]
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
        teacher_id = s.uid()
        con.execute("""INSERT INTO teachers (id,school_id,last_name,first_name,patronymic,subject,defined,created_at)
            VALUES (?,?,?,?,?,?,1,?)""", (teacher_id, school_id, *values, s.now()))
        return teacher_id

    @app.post("/api/schools/{school_id}/teachers", status_code=201)
    def create_teacher(school_id: str, payload: TeacherInput):
        with s.db() as con:
            require_school(con, school_id)
            return teacher_view(require_teacher(con, insert_teacher(con, school_id, payload)))

    @app.patch("/api/teachers/{teacher_id}")
    def edit_teacher(teacher_id: str, payload: TeacherInput):
        values = [clean(v) for v in (payload.last_name, payload.first_name, payload.patronymic, payload.subject)]
        if not values[0]:
            raise HTTPException(422, "Укажите фамилию учителя")
        with s.db() as con:
            require_teacher(con, teacher_id)
            con.execute("UPDATE teachers SET last_name=?, first_name=?, patronymic=?, subject=? WHERE id=?", (*values, teacher_id))
            return teacher_view(require_teacher(con, teacher_id))

    @app.delete("/api/teachers/{teacher_id}")
    def delete_teacher(teacher_id: str):
        """Albums that already chose the teacher keep them; the catalogue and new choices do not."""
        with s.db() as con:
            teacher = require_teacher(con, teacher_id)
            if con.execute("SELECT 1 FROM order_teachers WHERE teacher_id=?", (teacher_id,)).fetchone():
                con.execute("UPDATE teachers SET archived=1 WHERE id=?", (teacher_id,))
                return {"ok": True, "archived": True}
            con.execute("DELETE FROM teachers WHERE id=?", (teacher_id,))
        remove_portrait_files(teacher["portrait_path"])
        return {"ok": True, "archived": False}

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
            con.execute("UPDATE teachers SET portrait_path=?, portrait_by='photographer' WHERE id=?", (f"photos/{stem}.jpg", teacher_id))
            fresh = teacher_view(require_teacher(con, teacher_id))
        remove_portrait_files(teacher["portrait_path"])
        return fresh

    @app.delete("/api/teachers/{teacher_id}/portrait")
    def delete_portrait(teacher_id: str):
        with s.db() as con:
            teacher = require_teacher(con, teacher_id)
            con.execute("UPDATE teachers SET portrait_path='', portrait_by='' WHERE id=?", (teacher_id,))
        remove_portrait_files(teacher["portrait_path"])
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
            teacher = require_teacher(con, teacher_id)
        return portrait_file(teacher, variant)

    # Unsorted teacher photos: uploaded from the catalogue or from an order of the school,
    # then each one is given to a teacher and becomes that teacher's portrait.
    def photo_view(row):
        return {"id": row["id"], "filename": row["filename"], "order_id": row["order_id"], "created_at": row["created_at"],
                "status": row["status"], "group_id": row["group_id"]}

    def remove_files(paths):
        for path in paths:
            remove_portrait_files(path)

    def require_photo(con, photo_id):
        row = con.execute("""SELECT p.* FROM teacher_photos p JOIN schools s ON s.id=p.school_id
            WHERE p.id=? AND s.studio_id=?""", (photo_id, mvp._studio())).fetchone()
        if row is None:
            raise HTTPException(404, "Фотография не найдена")
        return row

    @app.get("/api/schools/{school_id}/teacher-photos")
    def teacher_photos(school_id: str):
        with s.db() as con:
            require_school(con, school_id)
            groups = photo_groups(con, school_id)
            return {"groups": [{"id": key, "photos": [photo_view(row) for row in rows]} for key, rows in groups.items()],
                    "pending": sum(row["status"] == "pending" for rows in groups.values() for row in rows)}

    @app.post("/api/schools/{school_id}/teacher-photos", status_code=201)
    async def upload_teacher_photo(school_id: str, request: Request, filename: str, order_id: str | None = None):
        if len(filename) > 240 or not filename.strip():
            raise HTTPException(422, "Некорректное имя файла")
        with s.db() as con:
            require_school(con, school_id)
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
            existing = con.execute("SELECT id FROM teacher_photos WHERE school_id=? AND sha=?", (school_id, sha)).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
        photo_id = s.uid()
        s.prepare_photo_files(bytes(body), "tphoto-" + photo_id)
        with s.db() as con:
            try:
                con.execute("""INSERT INTO teacher_photos (id,school_id,order_id,filename,sha,created_at,group_id,status)
                    VALUES (?,?,?,?,?,?,?,'pending')""", (photo_id, school_id, order_id, Path(filename).name, sha, s.now(), photo_id))
            except sqlite3.IntegrityError:
                remove_portrait_files(f"photos/tphoto-{photo_id}.jpg")
                existing = con.execute("SELECT id FROM teacher_photos WHERE school_id=? AND sha=?", (school_id, sha)).fetchone()
                return {"id": existing["id"], "duplicate": True}
        s.executor.submit(group_pending, s)
        return {"id": photo_id, "duplicate": False}

    @app.get("/api/teacher-photos/{photo_id}/{variant}")
    def teacher_photo_file(photo_id: str, variant: str):
        if variant not in {"thumb", "full"}:
            raise HTTPException(404, "Фотография не найдена")
        with s.db() as con:
            require_photo(con, photo_id)
        path = s.DATA / "photos" / (f"tphoto-{photo_id}" + (".thumb.jpg" if variant == "thumb" else ".jpg"))
        if not path.is_file():
            raise HTTPException(404, "Фотография не найдена")
        return FileResponse(path, media_type="image/jpeg")

    @app.delete("/api/teacher-photos/{photo_id}")
    def delete_teacher_photo(photo_id: str):
        with s.db() as con:
            require_photo(con, photo_id)
            con.execute("DELETE FROM teacher_photos WHERE id=?", (photo_id,))
        remove_portrait_files(f"photos/tphoto-{photo_id}.jpg")
        return {"ok": True}

    @app.post("/api/teacher-photos/{photo_id}/assign")
    def assign_teacher_photo(photo_id: str, payload: AssignInput):
        """The photo becomes the teacher's portrait (replacing an old one); its group is cleared."""
        if bool(payload.teacher_id) == bool(payload.teacher):
            raise HTTPException(422, "Выберите учителя или добавьте нового")
        with s.db() as con:
            con.execute("BEGIN IMMEDIATE")
            photo = require_photo(con, photo_id)
            teacher_id = insert_teacher(con, photo["school_id"], payload.teacher) if payload.teacher else payload.teacher_id
            require_teacher(con, teacher_id)
            stale = sign_photo(s, con, photo, teacher_id, "photographer")
            fresh = teacher_view(require_teacher(con, teacher_id))
        remove_files(stale)
        return fresh

    @app.post("/api/teacher-photos/{photo_id}/move")
    def move_teacher_photo(photo_id: str, payload: MoveInput):
        """Fix face grouping: join another group, or stand alone when group_id is empty."""
        with s.db() as con:
            photo = require_photo(con, photo_id)
            group = payload.group_id or s.uid()
            if payload.group_id and not con.execute("SELECT 1 FROM teacher_photos WHERE school_id=? AND group_id=?",
                                                    (photo["school_id"], group)).fetchone():
                raise HTTPException(404, "Группа не найдена")
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
            save_order_teachers(con, order_id, payload.teacher_ids, payload.class_teacher_id, "photographer", s.now())
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
            save_order_teachers(con, order["id"], payload.teacher_ids, payload.class_teacher_id, "client", s.now())
            return order_teachers_body(con, order["id"], public=True)

    def client_photo(con, token, request, photo_id):
        order = mvp._order_by_token(con, token)
        mvp.require_level(con, request, order["id"], "entry")
        photo = con.execute("SELECT * FROM teacher_photos WHERE id=? AND status='ready' AND school_id IS ?",
                            (photo_id, order_school_id(con, order["id"]))).fetchone()
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
            groups = photo_groups(con, school_id, ready_only=True)
            waiting = [{"id": row["id"], "name": full_name(row), "subject": row["subject"]}
                       for row in school_teachers(con, school_id) if not row["portrait_path"]]
            return {"groups": [{"id": key, "photos": [row["id"] for row in rows]} for key, rows in groups.items()],
                    "teachers": waiting}

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
            stale = sign_photo(s, con, photo, teacher_id, "client")
            teacher = con.execute("SELECT * FROM teachers WHERE id=?", (teacher_id,)).fetchone()
        remove_files(stale)
        return {"id": teacher_id, "name": full_name(teacher)}

    @app.get("/client-api/{token}/teachers/{teacher_id}/portrait")
    def client_portrait(token: str, teacher_id: str, request: Request):
        with s.db() as con:
            order = mvp._order_by_token(con, token)
            mvp.require_level(con, request, order["id"], "entry")
            school_id = order_school_id(con, order["id"])
            teacher = con.execute("SELECT * FROM teachers WHERE id=? AND school_id IS ? AND archived=0",
                                  (teacher_id, school_id)).fetchone()
            if teacher is None or school_id is None:
                raise HTTPException(404, "Портрет не найден")
        return portrait_file(teacher, "thumb")
