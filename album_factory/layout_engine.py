"""Deterministic auto-layout prototype: edition + order snapshot -> layout document.

Units are millimetres; the origin is the top-left corner of a spread or cover.
The engine never invents compositions: it chooses only among states prepared
by the edition author and reports an error when none fits.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Protocol

PLACEHOLDER = re.compile(r"\{(order|item|variant)\.([a-z_]+)\}")
TEACHER_VARIANT = "teacher_variant"
STUDENT = "student"


class LayoutError(ValueError):
    """Structural or capacity problem: no document can be produced."""


def canonical_hash(value) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def _r(value):
    return round(float(value), 3)


class TextMeasurer(Protocol):
    def height(self, text: str, font: str, size: float, leading: float, width: float) -> float: ...
    def missing_glyphs(self, text: str, font: str) -> set[str]: ...


class ReportLabMeasurer:
    """Measures with the same Paragraph engine the renderer draws with."""

    def __init__(self, fonts: dict[str, Path]):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        self._pdfmetrics = pdfmetrics
        self.names = {}
        for name, path in fonts.items():
            path = Path(path)
            rl_name = f"AF-{name}-{hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]}"
            if rl_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(rl_name, str(path)))
            self.names[name] = rl_name

    def _font(self, font):
        if font not in self.names:
            raise LayoutError(f"Шрифт {font!r} не передан генератору")
        return self.names[font]

    def paragraph(self, text, font, size, leading, align="left", color="#1D1D1D"):
        from xml.sax.saxutils import escape
        from reportlab.lib.colors import HexColor
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph
        style = ParagraphStyle("AF", fontName=self._font(font), fontSize=size, leading=leading,
                               textColor=HexColor(color), splitLongWords=True,
                               alignment={"left": 0, "center": 1, "right": 2}[align])
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    def height(self, text, font, size, leading, width):
        from reportlab.lib.units import mm
        _, used = self.paragraph(text, font, size, leading).wrap(width * mm, 100000)
        return used / mm

    def missing_glyphs(self, text, font):
        face = self._pdfmetrics.getFont(self._font(font)).face
        return {c for c in text if not c.isspace() and ord(c) not in face.charToGlyph}


# ---------------------------------------------------------------- planning

def split_even(n: int, k: int) -> list[int]:
    base, extra = divmod(n, k)
    return [base + 1] * extra + [base] * (k - extra)


def _state_for(count, states):
    return next((s for s in states if s["min"] <= count <= s["max"]), None)


def balance_flow(n: int, states: list[dict], spreads: int):
    """Even split over a fixed number of spreads; every share needs a prepared state."""
    counts = split_even(n, spreads)
    chosen = [_state_for(c, states) for c in counts]
    return None if None in chosen else list(zip(counts, chosen))


def block_counts(count: int, blocks: list[dict]) -> list[int]:
    """Distribute cells over page blocks, larger share first (11 -> 6 + 5)."""
    result, remaining = [], count
    for index, block in enumerate(blocks):
        share = math.ceil(remaining / (len(blocks) - index))
        take = min(block["cols"] * block["rows"], share)
        result.append(take)
        remaining -= take
    if remaining:
        raise LayoutError(f"Состояние не вмещает {count} участников")
    return result


def plan_sections(edition: dict, counts: dict[str, int], include=lambda section: True):
    """Return [(section, spreads)] in book order or raise LayoutError."""
    lo, hi = edition["spreads"]["min"], edition["spreads"]["max"]
    chosen, fillers, flows, total = {}, [], [], 0
    for section in edition["sections"]:
        if section.get("fill_to_min"):
            fillers.append(section)
            continue
        if section["kind"] == "flow":
            n = counts.get(section["collection"], 0)
            if n == 0:
                if section.get("optional"):
                    continue
                raise LayoutError(f"{section['title']}: нет участников")
            max_k = section.get("max_spreads", hi)
            biggest = max(s["max"] for s in section["states"])
            for k in range(math.ceil(n / biggest), max_k + 1):
                if balance_flow(n, section["states"], k):
                    break
            else:
                raise LayoutError(f"{section['title']}: нет подготовленной композиции для {n} участников")
            chosen[section["id"]] = k
            flows.append(section)
            total += k
        elif include(section):
            chosen[section["id"]] = 1
            total += 1
        elif not section.get("optional"):
            raise LayoutError(f"{section['title']}: нет обязательного содержимого")
    for section in fillers:
        if total >= lo:
            break
        if include(section):
            chosen[section["id"]] = 1
            total += 1
    expandable = [s for s in flows if s.get("expandable")]
    while total < lo:
        grown = False
        for section in expandable:
            k = chosen[section["id"]] + 1
            if (total < lo and k <= section.get("max_spreads", hi)
                    and balance_flow(counts[section["collection"]], section["states"], k)):
                chosen[section["id"]] = k
                total += 1
                grown = True
        if not grown:
            raise LayoutError(f"Недостаточно содержимого: {total} разворотов, издание требует от {lo}")
    if total > hi:
        raise LayoutError(f"Нужно {total} разворотов, издание допускает до {hi}")
    return [(s, chosen[s["id"]]) for s in edition["sections"] if s["id"] in chosen]


def capacity_matrix(edition: dict) -> list[dict]:
    """Publication check: every class size inside the declared capacity must plan."""
    failures = []
    (s_lo, s_hi), (t_lo, t_hi) = edition["capacity"]["students"], edition["capacity"]["teachers"]
    for students in range(s_lo, s_hi + 1):
        for teachers in range(t_lo, t_hi + 1):
            try:
                plan_sections(edition, {"students": students, "teachers": teachers})
            except LayoutError as exc:
                failures.append({"students": students, "teachers": teachers, "error": str(exc)})
    return failures


def field_limits(edition: dict) -> dict[str, int]:
    """Form limits for the client questionnaire, derived from the tightest slot."""
    limits = {}
    for template in edition["templates"].values():
        specs = template.get("elements", []) + template.get("first_elements", [])
        specs += template.get("cell", {}).get("elements", [])
        for spec in specs:
            if spec["type"] != "text" or "max_chars" not in spec:
                continue
            for scope, name in PLACEHOLDER.findall(spec["text"]):
                if scope in {"item", "variant"}:
                    limits[name] = min(limits.get(name, spec["max_chars"]), spec["max_chars"])
    return limits


def validate_edition(edition: dict):
    templates = edition["templates"]
    kinds = [STUDENT] + ([TEACHER_VARIANT] if edition.get("teacher_variant") else [])
    references = [edition["cover"]["templates"][k] for k in kinds]
    for section in edition["sections"]:
        if section["kind"] == "per_variant":
            references += [section["templates"][k] for k in kinds]
        else:
            references.append(section["template"])
        if section["kind"] == "flow":
            if section.get("subject_first") and templates.get(section["template"], {}).get("first_elements"):
                raise LayoutError(f"{section['id']}: в переставляемом разделе нет «первого» разворота")
            for state in section["states"]:
                capacity = sum(b["cols"] * b["rows"] for b in state["blocks"])
                if not 1 <= state["min"] <= state["max"] <= capacity:
                    raise LayoutError(f"{section['id']}/{state['id']}: неверная вместимость")
    for ref in references:
        if ref not in templates:
            raise LayoutError(f"Шаблон {ref} не найден")
    for name, template in templates.items():
        ids = [e["id"] for key in ("elements", "first_elements") for e in template.get(key, [])]
        ids += [e["id"] for e in template.get("cell", {}).get("elements", [])]
        if len(ids) != len(set(ids)):
            raise LayoutError(f"{name}: повторяющиеся id элементов")


def auto_crop(width, height, box_w, box_h, face=None, face_scale=None, eye_line=0.4):
    """Crop rectangle in source pixels with the slot aspect.

    With a face box (normalised x, y, w, h) the face occupies `face_scale` of the
    slot height and the eyes sit at `eye_line`; otherwise a centred crop is used.
    """
    aspect = box_w / box_h
    max_w, max_h = (height * aspect, height) if width / height > aspect else (width, width / aspect)
    if not face or not face_scale:
        return [_r((width - max_w) / 2), _r((height - max_h) / 2), _r(max_w), _r(max_h)]
    fx, fy, fw, fh = face[0] * width, face[1] * height, face[2] * width, face[3] * height
    crop_h = min(max_h, fh / face_scale)
    crop_w = crop_h * aspect
    if crop_w > max_w:
        crop_w, crop_h = max_w, max_w / aspect
    # YuNet boxes place the eyes at roughly 38% of the face height.
    x = fx + fw / 2 - crop_w / 2
    y = fy + 0.38 * fh - eye_line * crop_h
    x = min(max(x, 0), width - crop_w)
    y = min(max(y, 0), height - crop_h)
    return [_r(x), _r(y), _r(crop_w), _r(crop_h)]


# ---------------------------------------------------------------- snapshot

class _Snapshot:
    def __init__(self, data: dict):
        if data.get("schema_version") != 2:
            raise LayoutError("Поддерживается снимок schema_version 2")
        order = data["order"]
        self.photos = data["photos"]
        self.students = [dict(s, key=f"student:{s['id']}", name=f"{s['first_name']} {s['last_name']}",
                              quote=s.get("quote", "")) for s in data["students"]]
        self.teachers = [dict(t, key=f"teacher:{t['id']}", school_subject=t.get("school_subject", ""),
                              name=" ".join(filter(None, (t["last_name"], t["first_name"],
                                                          t.get("patronymic")))))
                         for t in data.get("teachers", [])]
        for group in (self.students, self.teachers):
            if len({p["key"] for p in group}) != len(group):
                raise LayoutError("Повторяющиеся идентификаторы участников")
        class_teacher = next((t for t in self.teachers if t.get("is_class_teacher")), None)
        self.order = dict(order, key="order",
                          class_teacher_name=class_teacher["name"] if class_teacher else "")
        self.teacher_variant = bool(data.get("teacher_variant", {}).get("enabled"))
        owners = {p["key"] for p in self.students + self.teachers} | {"order", TEACHER_VARIANT}
        self.selections = {}
        for item in data.get("selections", []):
            if item["owner"] not in owners:
                raise LayoutError(f"Выбор для неизвестного участника {item['owner']}")
            if item["photo"] not in self.photos:
                raise LayoutError(f"Выбор ссылается на неизвестное фото {item['photo']}")
            self.selections[(item["owner"], item["role"])] = item["photo"]

    def collection(self, name, sort=None):
        items = {"students": self.students, "teachers": self.teachers}[name]
        if sort == "class_teacher_first":
            items = sorted(items, key=lambda t: not t.get("is_class_teacher"))
        return items

    def variant_owners(self):
        owners = [dict(s, kind=STUDENT) for s in self.students]
        if self.teacher_variant:
            owners.append({"key": TEACHER_VARIANT, "kind": TEACHER_VARIANT,
                           "name": self.order["class_teacher_name"], "quote": ""})
        return owners


# ---------------------------------------------------------------- engine

class LayoutEngine:
    def __init__(self, edition: dict, measurer: TextMeasurer):
        validate_edition(edition)
        self.edition = edition
        self.templates = edition["templates"]
        self.measurer = measurer

    def generate(self, snapshot: dict, overrides=()) -> dict:
        snap = _Snapshot(snapshot)
        if snap.teacher_variant and not self.edition.get("teacher_variant"):
            raise LayoutError("Издание не поддерживает учительский вариант")
        self._check_capacity(snap)
        plan = plan_sections(self.edition, {"students": len(snap.students), "teachers": len(snap.teachers)},
                             include=lambda section: self._available(section, snap))
        owners = snap.variant_owners()
        shared, per_variant, book, plan_info = {}, {o["key"]: {} for o in owners}, [], []
        for section, spreads in plan:
            kind = section["kind"]
            if kind == "flow":
                keys = self._flow(section, spreads, snap, shared, plan_info)
                book.append(("flow", section, keys))
            elif kind == "per_variant":
                for owner in owners:
                    key = f"{section['id']}[{owner['key']}]"
                    template = section["templates"][owner["kind"]]
                    scopes = {"order": snap.order, "variant": owner}
                    per_variant[owner["key"]][key] = self._spread(key, section, template, scopes, snap)
                book.append(("per_variant", section, None))
                plan_info.append({"section": section["id"], "spreads": 1})
            else:
                key = section["id"]
                shared[key] = self._spread(key, section, section["template"], {"order": snap.order}, snap)
                book.append(("page", section, [key]))
                plan_info.append({"section": section["id"], "spreads": 1})
        spread_count = sum(spreads for _, spreads in plan)
        covers = {o["key"]: self._cover(o, snap, spread_count) for o in owners}
        variants = [self._variant(o, book, shared) for o in owners]
        if len({len(v["sequence"]) for v in variants}) > 1:
            raise LayoutError("Варианты заказа получили разное число разворотов")

        index = {}
        for spread in [*shared.values(), *covers.values(),
                       *(s for group in per_variant.values() for s in group.values())]:
            for element in spread["elements"]:
                index[element["key"]] = element
        applied, conflicts = self._apply_overrides(index, overrides, snap)

        pw, ph = self.edition["page_size_mm"]
        document = {
            "schema_version": 1,
            "edition": {"id": self.edition["id"], "version": self.edition["version"]},
            "input_hash": canonical_hash(snapshot),
            "spread_count": spread_count,
            "page_count": spread_count * 2,
            "spread_size_mm": [2 * pw, ph],
            "cover_size_mm": covers[owners[0]["key"]]["size_mm"] if owners else None,
            "plan": plan_info,
            "shared_spreads": shared,
            "variant_spreads": per_variant,
            "covers": covers,
            "variants": variants,
            "overrides": {"applied": applied, "conflicts": conflicts},
            "issues": self._validate(shared, per_variant, covers),
        }
        document["revision"] = canonical_hash(document)
        return document

    # -- planning helpers

    def _check_capacity(self, snap):
        for name, items in (("students", snap.students), ("teachers", snap.teachers)):
            lo, hi = self.edition["capacity"][name]
            if not lo <= len(items) <= hi:
                label = {"students": "учеников", "teachers": "учителей"}[name]
                raise LayoutError(f"Издание рассчитано на {lo}–{hi} {label}, в заказе {len(items)}")

    def _available(self, section, snap):
        scopes = {"order": snap.order}
        return all(self._resolve_photo(bind, scopes, section["id"], snap)[0]
                   for bind in section.get("requires", []))

    def _flow(self, section, spreads, snap, shared, plan_info):
        items = snap.collection(section["collection"], section.get("sort"))
        template = self.templates[section["template"]]
        keys, start = [], 0
        balance = balance_flow(len(items), section["states"], spreads)
        for index, (count, state) in enumerate(balance):
            key = f"{section['id']}#{index}"
            chunk = items[start:start + count]
            start += count
            scopes = {"order": snap.order}
            elements = [self._element(spec, spec["box"], f"{key}/{spec['id']}", scopes, snap)
                        for spec in template.get("elements", [])]
            if index == 0:
                elements += [self._element(spec, spec["box"], f"{key}/{spec['id']}", scopes, snap)
                             for spec in template.get("first_elements", [])]
            offset = 0
            for block, block_count in zip(state["blocks"], block_counts(count, state["blocks"])):
                for cell_box, item in zip(self._cells(block, block_count), chunk[offset:offset + block_count]):
                    cell_scopes = {"order": snap.order, "item": item}
                    for spec in template["cell"]["elements"]:
                        rx, ry, rw, rh = spec["rel"]
                        box = [cell_box[0] + rx * cell_box[2], cell_box[1] + ry * cell_box[3],
                               rw * cell_box[2], rh * cell_box[3]]
                        elements.append(self._element(
                            spec, box, f"{section['id']}/cell[{item['key']}]/{spec['id']}", cell_scopes, snap))
                offset += block_count
            shared[key] = {"key": key, "section": section["id"], "template": section["template"],
                           "state": state["id"], "items": [i["key"] for i in chunk],
                           "elements": [e for e in elements if e]}
            keys.append(key)
        plan_info.append({"section": section["id"], "spreads": spreads,
                          "states": [s["id"] for _, s in balance], "counts": [c for c, _ in balance]})
        return keys

    @staticmethod
    def _cells(block, count):
        """Row-major cells; the last row and an incomplete grid are centred."""
        x, y, w, h = block["box"]
        cols, rows = block["cols"], block["rows"]
        gx, gy = block.get("gap", [8, 8])
        cw, ch = (w - gx * (cols - 1)) / cols, (h - gy * (rows - 1)) / rows
        used_rows = math.ceil(count / cols) if count else 0
        top = y + (h - (used_rows * ch + gy * max(used_rows - 1, 0))) / 2
        cells = []
        for index in range(count):
            row, col = divmod(index, cols)
            in_row = min(cols, count - row * cols)
            left = x + (w - (in_row * cw + gx * (in_row - 1))) / 2
            cells.append([left + col * (cw + gx), top + row * (ch + gy), cw, ch])
        return cells

    def _spread(self, key, section, template_id, scopes, snap):
        template = self.templates[template_id]
        elements = [self._element(spec, spec["box"], f"{key}/{spec['id']}", scopes, snap)
                    for spec in template["elements"]]
        return {"key": key, "section": section["id"], "template": template_id,
                "elements": [e for e in elements if e]}

    def _cover(self, owner, snap, spread_count):
        pw, ph = self.edition["page_size_mm"]
        spine_spec = self.edition["print_spec"]["spine"]
        spine = spine_spec["base_mm"] + spine_spec["per_spread_mm"] * spread_count
        panels = {"back": (0, pw), "spine": (pw, spine), "front": (pw + spine, pw)}
        template_id = self.edition["cover"]["templates"][owner["kind"]]
        key = f"cover[{owner['key']}]"
        scopes = {"order": snap.order, "variant": owner}
        elements = []
        for spec in self.templates[template_id]["elements"]:
            left, width = panels[spec.get("panel", "front")]
            box = [0, 0, width, ph] if spec["box"] == "panel" else spec["box"]
            box = [left + box[0], box[1], box[2], box[3]]
            elements.append(self._element(spec, box, f"{key}/{spec['id']}", scopes, snap))
        return {"key": key, "section": "cover", "template": template_id,
                "size_mm": [_r(2 * pw + spine), ph], "spine_mm": _r(spine),
                "elements": [e for e in elements if e]}

    @staticmethod
    def _variant(owner, book, shared):
        """Same spreads for everyone; a student's own class spread may move first."""
        sequence = [f"cover[{owner['key']}]"]
        for kind, section, keys in book:
            if kind == "per_variant":
                sequence.append(f"{section['id']}[{owner['key']}]")
                continue
            if kind == "flow" and section.get("subject_first"):
                own = [k for k in keys if owner["key"] in shared[k]["items"]]
                keys = own + [k for k in keys if k not in own]
            sequence.extend(keys)
        return {"owner": owner["key"], "kind": owner["kind"], "name": owner.get("name", ""),
                "sequence": sequence}

    # -- elements

    def _format(self, template, scopes, key):
        empty = []

        def replace(match):
            scope, name = match.groups()
            if scope not in scopes:
                raise LayoutError(f"{key}: данные {scope} недоступны в этом разделе")
            value = scopes[scope].get(name)
            if value in (None, ""):
                empty.append(f"{scope}.{name}")
                return ""
            return str(value)

        return PLACEHOLDER.sub(replace, template), empty

    def _resolve_photo(self, binds, scopes, key, snap):
        for bind in [binds] if isinstance(binds, str) else binds or []:
            scope, _, role = bind.partition(".photo:")
            if scope not in scopes:
                raise LayoutError(f"{key}: данные {scope} недоступны в этом разделе")
            photo = snap.selections.get((scopes[scope]["key"], role))
            if photo:
                return photo, bind
        return None, None

    def _element(self, spec, box, key, scopes, snap):
        element = {"key": key, "type": spec["type"], "box": [_r(v) for v in box]}
        if spec["type"] == "rect":
            element["fill"] = spec["fill"]
            return element
        if spec["type"] == "text":
            text, empty = self._format(spec["text"], scopes, key)
            if empty and spec.get("optional"):
                return None
            element.update(text=text, base=text, font=spec.get("font", "main"),
                           align=spec.get("align", "left"), valign=spec.get("valign", "top"),
                           color=spec.get("color", "#1D1D1D"), max_size=spec["size"],
                           min_size=spec.get("min_size", spec["size"]),
                           leading_ratio=spec.get("leading", 1.2))
            if "max_chars" in spec:
                element["max_chars"] = spec["max_chars"]
            self._fit(element)
            return element
        if spec["type"] == "photo":
            photo, bind = self._resolve_photo(spec.get("bind"), scopes, key, snap)
            element.update(photo=photo, base=photo, source=bind, mask=spec.get("mask", "rect"),
                           face_scale=spec.get("face_scale"), eye_line=spec.get("eye_line", 0.4),
                           required=bool(spec.get("required")))
            element["crop"] = self._auto_crop(element, snap) if photo else None
            return element
        raise LayoutError(f"{key}: неизвестный тип элемента {spec['type']}")

    def _auto_crop(self, element, snap):
        meta = snap.photos[element["photo"]]
        return auto_crop(meta["width"], meta["height"], element["box"][2], element["box"][3],
                         meta.get("face"), element["face_scale"], element["eye_line"])

    def _fit(self, element):
        size, width, height = element["max_size"], element["box"][2], element["box"][3]
        while size >= element["min_size"] - 1e-9:
            leading = size * element["leading_ratio"]
            if not element["text"] or self.measurer.height(
                    element["text"], element["font"], size, leading, width) <= height + 0.01:
                element.update(size=_r(size), leading=_r(leading), overflow=False)
                return
            size -= 0.5
        size = element["min_size"]
        element.update(size=_r(size), leading=_r(size * element["leading_ratio"]), overflow=True)

    # -- overrides

    def _apply_overrides(self, index, overrides, snap):
        applied, conflicts = [], []
        for override in overrides:
            element = index.get(override["key"])
            if element is None:
                reason = "missing"
            elif override.get("base") != element.get("base"):
                reason = "base_changed"
            else:
                reason = self._apply_one(element, override, snap)
            if reason:
                conflicts.append(dict(override, reason=reason))
            else:
                applied.append(override)
                element.setdefault("overridden", []).append(override["type"])
        return applied, conflicts

    def _apply_one(self, element, override, snap):
        kind, value = override["type"], override.get("value")
        if kind == "hide":
            element["hidden"] = True
        elif kind == "text" and element["type"] == "text" and isinstance(value, str):
            element["text"] = value
            self._fit(element)
        elif kind == "photo" and element["type"] == "photo" and value in snap.photos:
            element["photo"] = value
            element["crop"] = self._auto_crop(element, snap)
        elif kind == "crop" and element["type"] == "photo" and element["photo"]:
            if value.get("photo") != element["photo"]:
                return "photo_changed"
            meta = snap.photos[element["photo"]]
            x, y, w, _ = value["rect"]
            aspect = element["box"][2] / element["box"][3]
            crop_w = min(w * meta["width"], meta["height"] * aspect)
            crop_h = crop_w / aspect
            left = min(max(x * meta["width"], 0), meta["width"] - crop_w)
            top = min(max(y * meta["height"], 0), meta["height"] - crop_h)
            element["crop"] = [_r(left), _r(top), _r(crop_w), _r(crop_h)]
        else:
            return "invalid"
        return None

    # -- checks

    def _validate(self, shared, per_variant, covers):
        spec = self.edition["print_spec"]
        pw, ph = self.edition["page_size_mm"]
        safe = spec["safe_mm"]
        issues = []
        spreads = [(s, True) for s in shared.values()]
        spreads += [(s, True) for group in per_variant.values() for s in group.values()]
        spreads += [(s, False) for s in covers.values()]
        for spread, is_block in spreads:
            for element in spread["elements"]:
                if element.get("hidden"):
                    continue
                key = element["key"]
                if element["type"] == "photo":
                    if not element["photo"]:
                        if element.get("required"):
                            issues.append(_issue("error", "empty_slot", key, "Не выбрано обязательное фото"))
                        continue
                    dpi = element["crop"][2] / (element["box"][2] / 25.4)
                    if dpi < spec["hard_min_dpi"]:
                        issues.append(_issue("error", "low_dpi", key, f"Около {math.floor(dpi)} DPI"))
                    elif dpi < spec["min_dpi"]:
                        issues.append(_issue("warning", "low_dpi", key, f"Около {math.floor(dpi)} DPI"))
                elif element["type"] == "text":
                    if element["overflow"]:
                        issues.append(_issue("error", "text_overflow", key,
                                             f"Текст не помещается: {element['text'][:40]}"))
                    missing = self.measurer.missing_glyphs(element["text"], element["font"])
                    if missing:
                        issues.append(_issue("error", "missing_glyphs", key,
                                             "Нет символов в шрифте: " + " ".join(sorted(missing))))
                    if len(element["text"]) > element.get("max_chars", math.inf):
                        issues.append(_issue("warning", "text_too_long", key,
                                             f"Длиннее {element['max_chars']} символов"))
                    x, y, w, h = element["box"]
                    if is_block and (x < safe or y < safe or x + w > 2 * pw - safe or y + h > ph - safe):
                        issues.append(_issue("warning", "unsafe_zone", key, "Текст вне безопасной зоны"))
                    if is_block and x < pw < x + w:
                        issues.append(_issue("warning", "gutter", key, "Текст пересекает корешок"))
        return issues


def _issue(level, code, key, message):
    return {"level": level, "code": code, "key": key, "message": message}


def load_edition(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
