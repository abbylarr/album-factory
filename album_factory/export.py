"""Proof PDF and CSV exports. No claim of PDF/X or press-ready color."""
from __future__ import annotations

import csv
from io import BytesIO
import json
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageOps
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from .core import Album, ValidationError


def _csv_cell(value):
    # Spreadsheet applications may execute leading formula characters.
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def export_csv(album: Album, destination: Path):
    photos = {p.id: p for p in album.photos}
    with destination.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["person_id", "role", "first_name", "last_name", "quote", "photo_id", "filename"])
        for p in album.people:
            writer.writerow([_csv_cell(v) for v in
                             [p.id, p.role, p.first_name, p.last_name, p.quote,
                              p.portrait, photos[p.portrait].path.name]])


def export_pdf(album: Album, destination: Path, font_path: Path):
    """Render all pages to memory before writing, so overflow cannot leave a partial PDF."""
    font_name = "AlbumFont"
    pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
    font = pdfmetrics.getFont(font_name)
    texts = [album.school, album.class_name, album.year]
    texts += [p.full_name + p.quote for p in album.people]
    missing = sorted({c for text in texts for c in text if not c.isspace()
                      and ord(c) not in font.face.charToGlyph})
    if missing:
        raise ValidationError("Шрифт не поддерживает символы: " + " ".join(missing))
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(210 * mm, 280 * mm), invariant=1,
                        pageCompression=1)
    pdf.setTitle(f"{album.school} / {album.class_name} — контрольный макет")
    pdf.setAuthor("Album Factory")
    photos = {p.id: p for p in album.photos}
    people = {p.id: p for p in album.people}

    def text(value, x, top, width, height, size=11, alignment=0):
        style = ParagraphStyle("Album", fontName=font_name, fontSize=size,
                               leading=size * 1.25, textColor=HexColor("#1D1D1D"),
                               alignment=alignment, splitLongWords=True)
        paragraph = Paragraph(escape(value), style)
        _, used = paragraph.wrap(width * mm, height * mm)
        if used > height * mm + 0.01:
            raise ValidationError(f"Текст не помещается в шаблон: {value[:65]}")
        paragraph.drawOn(pdf, x * mm, (280 - top) * mm - used)

    def picture(photo_id, x, top, width, height, crop=False):
        photo = photos[photo_id]
        with Image.open(photo.path) as original:
            im = ImageOps.exif_transpose(original).convert("RGB")
            # Proof output: RGB pixels; production needs ICC-aware conversion.
            if crop:
                im = ImageOps.fit(im, (int(width / 25.4 * 300), int(height / 25.4 * 300)))
                draw_w, draw_h = width, height
            else:
                ratio = min(width / im.width, height / im.height)
                draw_w, draw_h = im.width * ratio, im.height * ratio
            pdf.drawImage(ImageReader(im), (x + (width - draw_w) / 2) * mm,
                          (280 - top - (height + draw_h) / 2) * mm,
                          draw_w * mm, draw_h * mm)

    for index, page in enumerate(album.pages, 1):
        if page.kind == "cover":
            text("ВЫПУСКНОЙ АЛЬБОМ", 18, 34, 174, 20, 15)
            text(album.class_name, 18, 70, 174, 45, 42)
            text(album.school, 18, 131, 174, 32, 20)
            text(album.year, 18, 191, 174, 25, 30)
            text("Один общий макет для класса", 18, 232, 174, 10, 11)
        elif page.kind in {"student", "teacher"}:
            text("Наш класс" if page.kind == "student" else "Наши учителя",
                 18, 15, 174, 14, 22)
            for slot, person_id in enumerate(page.ids):
                person = people[person_id]
                x, top = 18 + (slot % 3) * 60, 40 + (slot // 3) * 107
                picture(person.portrait, x, top, 54, 72, crop=True)
                text(person.full_name, x, top + 75, 54, 12, 10)
                if person.quote:
                    text(person.quote, x, top + 88, 54, 17, 8)
        else:
            text("Вместе" if page.kind == "class" else "Школьные моменты",
                 18, 15, 174, 14, 22)
            picture(page.ids[0], 18, 42, 174, 200)
        text(f"КОНТРОЛЬНЫЙ PDF · {album.revision[:10]}", 18, 267, 158, 6, 7)
        text(str(index), 183, 266, 9, 7, 9, alignment=2)
        pdf.showPage()
    pdf.save()
    destination.write_bytes(buffer.getvalue())


def export_manifest(album: Album, destination: Path):
    selected = {p.portrait for p in album.people}
    selected.update(i for page in album.pages if page.kind in {"class", "group"} for i in page.ids)
    data = {
        "schema_version": 1, "order_id": album.order_id,
        "revision": album.revision, "template": "common-proof-v1",
        "copies": album.copies, "pdf_count": 1, "status": "proof",
        "print_ready": False, "page_size_mm": [210, 280], "bleed_mm": 0,
        "pages": [vars(p) for p in album.pages],
        "selected_photos": [{"id": p.id, "sha256": p.sha256}
                            for p in album.photos if p.id in selected],
        "warnings": list(album.warnings),
        "limitations": ["RGB proof only; no PDF/X, ICC output intent or bleed",
                        "Center crop only; no face-aware crop", "No authenticated approval"],
    }
    destination.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
