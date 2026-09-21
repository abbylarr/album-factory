"""Validate selections and compile a deterministic, common-class layout.

No network, face recognition or identity verification occurs in this module.
Input is a trusted local manifest; every photograph must be under its root.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageOps


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Photo:
    id: str
    path: Path
    people: tuple[str, ...]
    category: str
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class Person:
    id: str
    first_name: str
    last_name: str
    role: str
    quote: str
    portrait: str

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


@dataclass(frozen=True)
class Page:
    kind: str
    ids: tuple[str, ...]


@dataclass(frozen=True)
class Album:
    order_id: str
    school: str
    class_name: str
    year: str
    copies: int
    people: tuple[Person, ...]
    photos: tuple[Photo, ...]
    pages: tuple[Page, ...]
    revision: str
    warnings: tuple[str, ...]


def _text(value, field, limit, optional=False):
    if not isinstance(value, str):
        raise ValidationError(f"{field}: ожидается текст")
    value = value.strip()
    if (not value and not optional) or len(value) > limit:
        raise ValidationError(f"{field}: требуется от {0 if optional else 1} до {limit} символов")
    if any(ord(c) < 32 for c in value):
        raise ValidationError(f"{field}: управляющие символы недопустимы")
    return value


def _unique(items, field):
    if len(set(items)) != len(items):
        raise ValidationError(f"{field}: повторяющиеся идентификаторы")


def compile_album(data: dict, root: Path) -> Album:
    """The fixed proof template has six portraits per page, 210 × 280 mm.

    The content fingerprint includes ordered participants, selected image bytes
    and template version. Unused uploads and print quantity do not affect it.
    """
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValidationError("Поддерживается schema_version 1")
    root = root.resolve()
    try:
        order = data["order"]
        order_id = _text(order["id"], "order.id", 80)
        school = _text(order["school"], "school", 100)
        class_name = _text(order["class_name"], "class_name", 30)
        year = _text(order["year"], "year", 10)
        copies = order["copies"]
        if type(copies) is not int or not 1 <= copies <= 1000:
            raise ValidationError("copies: требуется целое число от 1 до 1000")
        raw_people, raw_photos = data["people"], data["photos"]
        if not isinstance(raw_people, list) or not 1 <= len(raw_people) <= 200:
            raise ValidationError("Требуется от 1 до 200 участников")
        if not isinstance(raw_photos, list) or not 1 <= len(raw_photos) <= 1000:
            raise ValidationError("Требуется от 1 до 1000 фотографий")
        people = tuple(Person(
            _text(p["id"], "person.id", 80),
            _text(p["first_name"], "first_name", 50),
            _text(p["last_name"], "last_name", 70),
            _text(p["role"], "role", 20),
            _text(p.get("quote", ""), "quote", 180, optional=True),
            _text(p["portrait"], "portrait", 80),
        ) for p in raw_people)
        _unique([p.id for p in people], "people")
        person_ids = {p.id for p in people}
        if any(p.role not in {"student", "teacher"} for p in people):
            raise ValidationError("role: допустимы student и teacher")
        if not any(p.role == "student" for p in people):
            raise ValidationError("Нужен хотя бы один ученик")
        photos = []
        for raw in raw_photos:
            photo_id = _text(raw["id"], "photo.id", 80)
            relative = Path(_text(raw["path"], "photo.path", 500))
            path = (root / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root):
                raise ValidationError(f"{photo_id}: файл должен находиться внутри папки заказа")
            if not path.is_file():
                raise ValidationError(f"{photo_id}: файл не найден")
            if path.stat().st_size > 50 * 1024 * 1024:
                raise ValidationError(f"{photo_id}: файл больше 50 МБ")
            ids = raw.get("people", [])
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                raise ValidationError(f"{photo_id}: people должен быть списком идентификаторов")
            _unique(ids, photo_id)
            if not set(ids) <= person_ids:
                raise ValidationError(f"{photo_id}: неизвестная персона")
            category = _text(raw["category"], "photo.category", 20)
            if category not in {"portrait", "class", "group"}:
                raise ValidationError(f"{photo_id}: неизвестная категория")
            try:
                with Image.open(path) as im:
                    # MPO is a multi-image JPEG container used by many cameras (e.g. Sony).
                    if im.format not in {"JPEG", "PNG", "MPO"}:
                        raise ValidationError(f"{photo_id}: нужен JPEG или PNG")
                    im.verify()
                with Image.open(path) as im:
                    oriented = ImageOps.exif_transpose(im)
                    width, height = oriented.size
            except (OSError, Image.DecompressionBombError) as exc:
                raise ValidationError(f"{photo_id}: изображение повреждено или слишком большое") from exc
            photos.append(Photo(photo_id, path, tuple(ids), category,
                                hashlib.sha256(path.read_bytes()).hexdigest(), width, height))
        _unique([p.id for p in photos], "photos")
        photo_map = {p.id: p for p in photos}
        for person in people:
            photo = photo_map.get(person.portrait)
            if photo is None or photo.category != "portrait" or person.id not in photo.people:
                raise ValidationError(f"{person.id}: портрет не принадлежит этой персоне")
        shared = data.get("shared_photos", [])
        if not isinstance(shared, list) or any(not isinstance(i, str) for i in shared):
            raise ValidationError("shared_photos: нужен список идентификаторов")
        _unique(shared, "shared_photos")
        for photo_id in shared:
            if photo_id not in photo_map or photo_map[photo_id].category not in {"class", "group"}:
                raise ValidationError(f"{photo_id}: общая страница требует class или group")
    except (KeyError, TypeError) as exc:
        raise ValidationError(f"Неверная структура заказа: {exc}") from exc

    pages = [Page("cover", ())]
    for role in ("student", "teacher"):
        ids = tuple(p.id for p in people if p.role == role)
        pages += [Page(role, ids[start:start + 6]) for start in range(0, len(ids), 6)]
    pages += [Page(photo_map[i].category, (i,)) for i in shared]
    selected = {p.portrait for p in people} | set(shared)
    content = {
        "template": "common-proof-v1", "order": order_id, "school": school,
        "class_name": class_name, "year": year,
        "people": [vars(p) for p in people],
        "pages": [vars(p) for p in pages],
        "images": {i: photo_map[i].sha256 for i in sorted(selected)},
    }
    revision = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
    warnings = []
    for photo_id in sorted(selected):
        photo = photo_map[photo_id]
        w_mm, h_mm = (54, 72) if photo.category == "portrait" else (174, 200)
        # Portraits fill the slot by cropping; shared images fit without cropping.
        ratios = (photo.width / (w_mm / 25.4), photo.height / (h_mm / 25.4))
        dpi = min(ratios) if photo.category == "portrait" else max(ratios)
        if dpi < 300:
            warnings.append(f"{photo_id}: около {math.floor(dpi)} DPI, ниже ориентира 300 DPI")
    return Album(order_id, school, class_name, year, copies, people, tuple(photos),
                 tuple(pages), revision, tuple(warnings))


def approval_matches(album: Album, approval: dict) -> bool:
    """Content check only; caller must separately authenticate the approver."""
    return (approval.get("order_id") == album.order_id
            and approval.get("revision") == album.revision
            and approval.get("decision") == "approved")
