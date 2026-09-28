"""Studio school catalogue: schools, their teachers and the teachers chosen for each class album.

Every school belongs to one studio. Teachers belong to a school and are reused across that
school's orders, so a portrait taken once keeps working in later albums. The class chooses
which teachers appear in its album and who is the class teacher; the photographer can do the
same from the order page. Nothing here is shared between studios.
"""
from __future__ import annotations

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
    con.execute("""CREATE TABLE IF NOT EXISTS order_teacher_state (
      order_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)""")
    schools = {r[1] for r in con.execute("PRAGMA table_info(schools)")}
    if "city" not in schools:
        con.execute("ALTER TABLE schools ADD COLUMN city TEXT NOT NULL DEFAULT ''")
    teachers = {r[1] for r in con.execute("PRAGMA table_info(teachers)")}
    for column, kind in (("patronymic", "TEXT NOT NULL DEFAULT ''"), ("subject", "TEXT NOT NULL DEFAULT ''"),
                         ("archived", "INTEGER NOT NULL DEFAULT 0"), ("created_at", "TEXT NOT NULL DEFAULT ''")):
        if column not in teachers:
            con.execute(f"ALTER TABLE teachers ADD COLUMN {column} {kind}")


def forget(con, order_id):
    con.execute("DELETE FROM order_teachers WHERE order_id=?", (order_id,))
    con.execute("DELETE FROM order_teacher_state WHERE order_id=?", (order_id,))


def clean(text):
    return " ".join(str(text or "").split())


def full_name(teacher):
    return " ".join(filter(None, (teacher["last_name"], teacher["first_name"], teacher["patronymic"])))


def teacher_view(row):
    return {"id": row["id"], "school_id": row["school_id"], "last_name": row["last_name"],
            "first_name": row["first_name"], "patronymic": row["patronymic"], "subject": row["subject"],
            "name": full_name(row), "has_portrait": bool(row["portrait_path"]),
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


def client_summary(con, order_id):
    """Short state for the client portal's status card."""
    school_id = order_school_id(con, order_id)
    available = len(school_teachers(con, school_id)) if school_id else 0
    picked = chosen(con, order_id)
    lead = next((row for row in picked if row["is_class_teacher"]), None)
    return {"available": available, "chosen": len(picked),
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
            con.execute("DELETE FROM teachers WHERE school_id=?", (school_id,))
            con.execute("DELETE FROM schools WHERE id=?", (school_id,))
        for path in paths:
            remove_portrait_files(path)
        return {"ok": True}

    @app.post("/api/schools/{school_id}/teachers", status_code=201)
    def create_teacher(school_id: str, payload: TeacherInput):
        values = [clean(v) for v in (payload.last_name, payload.first_name, payload.patronymic, payload.subject)]
        if not values[0]:
            raise HTTPException(422, "Укажите фамилию учителя")
        with s.db() as con:
            require_school(con, school_id)
            teacher_id = s.uid()
            con.execute("""INSERT INTO teachers (id,school_id,last_name,first_name,patronymic,subject,defined,created_at)
                VALUES (?,?,?,?,?,?,1,?)""", (teacher_id, school_id, *values, s.now()))
            return teacher_view(require_teacher(con, teacher_id))

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
            con.execute("UPDATE teachers SET portrait_path=? WHERE id=?", (f"photos/{stem}.jpg", teacher_id))
            fresh = teacher_view(require_teacher(con, teacher_id))
        remove_portrait_files(teacher["portrait_path"])
        return fresh

    @app.delete("/api/teachers/{teacher_id}/portrait")
    def delete_portrait(teacher_id: str):
        with s.db() as con:
            teacher = require_teacher(con, teacher_id)
            con.execute("UPDATE teachers SET portrait_path='' WHERE id=?", (teacher_id,))
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
