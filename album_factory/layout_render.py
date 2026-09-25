"""Render layout-document variants to proof PDFs. No bleed, ICC or PDF/X yet."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageOps
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .layout_engine import LayoutError, ReportLabMeasurer

TARGET_DPI = 300


class _Images:
    """Decoded crops are shared between variants: most spreads are common."""

    def __init__(self, snapshot: dict, root: Path):
        self.photos, self.root, self.cache = snapshot["photos"], Path(root), {}

    def get(self, photo_id, crop, box_w, box_h):
        target = (max(1, round(min(crop[2], box_w / 25.4 * TARGET_DPI))),
                  max(1, round(min(crop[3], box_h / 25.4 * TARGET_DPI))))
        key = (photo_id, tuple(crop), target)
        if key not in self.cache:
            with Image.open(self.root / self.photos[photo_id]["path"]) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
                x, y, w, h = crop
                image = image.crop((round(x), round(y), round(x + w), round(y + h)))
                self.cache[key] = ImageReader(image.resize(target, Image.LANCZOS))
        return self.cache[key]


def _draw(pdf, spread, size, measurer, images):
    _, height = size
    for element in spread["elements"]:
        if element.get("hidden"):
            continue
        x, top, w, h = element["box"]
        bottom = height - top - h
        if element["type"] == "rect":
            pdf.setFillColor(HexColor(element["fill"]))
            pdf.rect(x * mm, bottom * mm, w * mm, h * mm, stroke=0, fill=1)
        elif element["type"] == "photo":
            if not element["photo"] and not element.get("required"):
                continue
            path = pdf.beginPath()
            if element["mask"] == "ellipse":
                path.ellipse(x * mm, bottom * mm, w * mm, h * mm)
            else:
                path.rect(x * mm, bottom * mm, w * mm, h * mm)
            pdf.saveState()
            if element["photo"]:
                pdf.clipPath(path, stroke=0, fill=0)
                pdf.drawImage(images.get(element["photo"], element["crop"], w, h),
                              x * mm, bottom * mm, w * mm, h * mm)
            else:
                pdf.setFillColor(HexColor("#D9D9D9"))
                pdf.setStrokeColor(HexColor("#C0392B"))
                pdf.setDash(4, 3)
                pdf.drawPath(path, stroke=1, fill=1)
            pdf.restoreState()
        elif element["type"] == "text" and element["text"]:
            paragraph = measurer.paragraph(element["text"], element["font"], element["size"],
                                           element["leading"], element["align"], element["color"])
            _, used = paragraph.wrap(w * mm, 100000)
            offset = {"top": 0, "middle": (h * mm - used) / 2, "bottom": h * mm - used}[element["valign"]]
            paragraph.drawOn(pdf, x * mm, (height - top) * mm - offset - used)


def render_variant(document: dict, owner: str, snapshot: dict, root: Path,
                   measurer: ReportLabMeasurer, destination: Path, images: _Images | None = None):
    variant = next((v for v in document["variants"] if v["owner"] == owner), None)
    if variant is None:
        raise LayoutError(f"Вариант {owner} не найден")
    images = images or _Images(snapshot, root)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, invariant=1, pageCompression=1)
    pdf.setTitle(f"Альбом · {variant['name'] or owner} · {document['revision'][:10]}")
    pdf.setAuthor("Album Factory")
    for key in variant["sequence"]:
        if key.startswith("cover["):
            spread, size = document["covers"][owner], document["cover_size_mm"]
        else:
            spread = document["shared_spreads"].get(key) or document["variant_spreads"][owner][key]
            size = document["spread_size_mm"]
        pdf.setPageSize((size[0] * mm, size[1] * mm))
        _draw(pdf, spread, size, measurer, images)
        pdf.showPage()
    pdf.save()
    Path(destination).write_bytes(buffer.getvalue())


def variant_filename(index: int, variant: dict) -> str:
    safe = re.sub(r"[^\w-]+", "_", variant["name"] or variant["kind"]).strip("_")
    return f"{index:02d}-{variant['owner'].replace(':', '-')}-{safe}.pdf"


def export_variants(document, snapshot, root, measurer, out_dir: Path, owners=None) -> list[Path]:
    if any(issue["level"] == "error" for issue in document["issues"]):
        raise LayoutError("В макете есть ошибки; экспорт заблокирован")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    images, paths = _Images(snapshot, root), []
    for index, variant in enumerate(document["variants"], 1):
        if owners is not None and variant["owner"] not in owners:
            continue
        path = out_dir / variant_filename(index, variant)
        render_variant(document, variant["owner"], snapshot, root, measurer, path, images)
        paths.append(path)
    return paths
