"""Render layout-document variants to proof PDFs. No bleed, ICC or PDF/X yet."""
from __future__ import annotations

from io import BytesIO
import math
from pathlib import Path
import re

from PIL import Image, ImageOps
from reportlab.lib.colors import HexColor
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .layout_engine import LayoutError, ReportLabMeasurer
from .svg_draw import draw_svg

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


def _shadow_offsets(shadow):
    ox, oy = float(shadow.get('offsetX') or 0), float(shadow.get('offsetY') or 0)
    blur = max(0, float(shadow.get('blur') or 0))
    if blur < 0.2:
        return [(ox, oy, 1)]
    return [(ox + math.cos(i * math.pi / 4) * blur * 0.45, oy + math.sin(i * math.pi / 4) * blur * 0.45, 0.45) for i in range(8)] + [(ox, oy, 0.8)]


def _cast_shadow(pdf, element, paint):
    shadow = element.get('shadow')
    if not isinstance(shadow, dict):
        return
    base = element.get('opacity', 100) / 100 * float(shadow.get('opacity', 35)) / 100
    if base <= 0:
        return
    for ox, oy, weight in _shadow_offsets(shadow):
        pdf.saveState()
        alpha = min(1, base * weight)
        pdf.setFillAlpha(alpha)
        pdf.setStrokeAlpha(0)
        pdf.translate(ox * mm, -oy * mm)
        paint(shadow.get('color') or '#000000')
        pdf.restoreState()


def _rotate(pdf, element, height):
    if element.get('angle'):
        x, top, w, h = element["box"]
        cx,cy=element.get('rotation_center',[x+w/2,top+h/2])
        pdf.translate(cx*mm,(height-cy)*mm)
        pdf.rotate(-element['angle'])
        pdf.translate(-cx*mm,-(height-cy)*mm)


def _stroke_reach(element):
    """How far a photo's stroke extends past its box: the shadow is cast by that outer edge."""
    width = element.get('strokeWidth', 0) or 0
    if not width or not element.get('photo'):
        return 0
    align = element.get('strokeAlign') or 'center'
    return width if align == 'outside' else width / 2 if align == 'center' else 0


def _photo_path(pdf, element, height, grow=0):
    x, top, w, h = element["box"]
    x, bottom, w, h = x - grow, height - top - h - grow, w + 2 * grow, h + 2 * grow
    path = pdf.beginPath()
    if element["mask"] == "ellipse":
        path.ellipse(x * mm, bottom * mm, w * mm, h * mm)
    else:
        radius = min(element.get('radius', 0) and element['radius'] + grow, w / 2, h / 2) * mm
        if radius: path.roundRect(x * mm, bottom * mm, w * mm, h * mm, radius)
        else: path.rect(x * mm, bottom * mm, w * mm, h * mm)
    return path


def _cast_photo_shadow(pdf, element, height):
    path = _photo_path(pdf, element, height, _stroke_reach(element))
    def paint(color):
        pdf.setFillColor(HexColor(color))
        pdf.drawPath(path, stroke=0, fill=1)
    _cast_shadow(pdf, element, paint)


def _draw(pdf, spread, size, measurer, images):
    _, height = size
    cast_groups = set()
    for element in spread["elements"]:
        if element.get("hidden"):
            continue
        group = element.get('shadowGroup')
        if group and group not in cast_groups:
            # Vignette cards share one shadow layer, so a card's shadow never falls on its neighbour.
            cast_groups.add(group)
            for member in spread["elements"]:
                if member.get('shadowGroup') == group and not member.get('hidden'):
                    pdf.saveState()
                    _rotate(pdf, member, height)
                    _cast_photo_shadow(pdf, member, height)
                    pdf.restoreState()
        x, top, w, h = element["box"]
        bottom = height - top - h
        pdf.saveState()
        pdf.setFillAlpha(element.get("opacity",100)/100)
        pdf.setStrokeAlpha(element.get("opacity",100)/100)
        _rotate(pdf, element, height)
        stroke_width=element.get('strokeWidth',0) or 0
        stroke_alpha=element.get("opacity",100)/100 * element.get('strokeOpacity',100)/100
        pdf.setStrokeAlpha(stroke_alpha)
        pdf.setStrokeColor(HexColor(element.get('stroke','#333333')))
        dash=element.get('strokeDash') or 'solid'
        if dash=='dashed': pdf.setDash(1.8*mm, 1.15*mm)
        elif dash=='dotted': pdf.setDash(0.4*mm, 1.15*mm)
        pdf.setLineWidth(stroke_width*mm)
        pdf.setLineCap({"butt": 0, "round": 1, "square": 2}.get(element.get("strokeCap"), 0))
        pdf.setLineJoin({"miter": 0, "round": 1, "bevel": 2}.get(element.get("strokeJoin"), 0))
        if element["type"] in {"rect", "line", "ellipse"}:
            radius=min(element.get('radius',0),w/2,h/2)*mm
            def paint_shape(color, stroked):
                pdf.setFillColor(HexColor(color))
                if element["type"] == "ellipse":
                    pdf.ellipse(x*mm,bottom*mm,(x+w)*mm,(bottom+h)*mm,stroke=stroked,fill=1)
                else:
                    pdf.roundRect(x*mm,bottom*mm,w*mm,h*mm,radius,stroke=stroked,fill=1)
            _cast_shadow(pdf, element, lambda color: paint_shape(color, False))
            outside=element.get('strokeAlign')=='outside' and stroke_width and element["type"]!='line'
            inside=element.get('strokeAlign')=='inside' and stroke_width and element["type"]!='line'
            if outside:
                pdf.setLineWidth(stroke_width*2*mm)
                pdf.setFillColor(HexColor(element["fill"]))
                if element["type"]=="ellipse":
                    pdf.ellipse(x*mm,bottom*mm,(x+w)*mm,(bottom+h)*mm,stroke=1,fill=0)
                    pdf.ellipse(x*mm,bottom*mm,(x+w)*mm,(bottom+h)*mm,stroke=0,fill=1)
                else:
                    pdf.roundRect(x*mm,bottom*mm,w*mm,h*mm,radius,stroke=1,fill=0)
                    pdf.roundRect(x*mm,bottom*mm,w*mm,h*mm,radius,stroke=0,fill=1)
            elif inside:
                pdf.saveState()
                clip=pdf.beginPath()
                if element["type"]=="ellipse": clip.ellipse(x*mm,bottom*mm,(x+w)*mm,(bottom+h)*mm)
                else: clip.roundRect(x*mm,bottom*mm,w*mm,h*mm,radius)
                pdf.clipPath(clip, stroke=0, fill=0)
                pdf.setLineWidth(stroke_width*2*mm)
                paint_shape(element["fill"], True)
                pdf.restoreState()
            else:
                paint_shape(element["fill"], bool(stroke_width))
        elif element["type"] == "frame" and stroke_width:
            path = pdf.beginPath()
            radius = min(element.get('radius', 0), w / 2, h / 2) * mm
            if radius:
                path.roundRect(x * mm, bottom * mm, w * mm, h * mm, radius)
            else:
                path.rect(x * mm, bottom * mm, w * mm, h * mm)
            align = element.get('strokeAlign') or 'center'
            if align in {'inside', 'outside'}:
                pdf.setLineWidth(stroke_width * 2 * mm)
            if align == 'inside':
                pdf.saveState()
                pdf.clipPath(path, stroke=0, fill=0)
                pdf.drawPath(path, stroke=1, fill=0)
                pdf.restoreState()
            else:
                pdf.drawPath(path, stroke=1, fill=0)
        elif element["type"]=="svg" and element.get("svg"):
            flipped=element.get("flipX") or element.get("flipY")
            if flipped:
                pdf.saveState()
                cx,cy=(x+w/2)*mm,(bottom+h/2)*mm
                pdf.translate(cx,cy)
                pdf.scale(-1 if element.get("flipX") else 1, -1 if element.get("flipY") else 1)
                pdf.translate(-cx,-cy)
            draw_svg(pdf, element["svg"], x*mm, bottom*mm, w*mm, h*mm, element.get("strokeAlign") or "center")
            if flipped: pdf.restoreState()
        elif element["type"] == "photo":
            if not element["photo"] and not element.get("required"):
                pdf.restoreState()
                continue
            path = _photo_path(pdf, element, height)
            if not element.get('shadowGroup'):
                _cast_photo_shadow(pdf, element, height)
            align = element.get('strokeAlign') or 'center'
            if stroke_width and align == 'outside' and element['photo']:
                pdf.setLineWidth(stroke_width * 2 * mm)
                pdf.drawPath(path, stroke=1, fill=0)
            pdf.saveState()
            if element["photo"]:
                pdf.clipPath(path, stroke=0, fill=0)
                pdf.drawImage(images.get(element["photo"], element["crop"], w, h),
                              x * mm, bottom * mm, w * mm, h * mm)
                if stroke_width and align == 'inside':
                    pdf.setLineWidth(stroke_width * 2 * mm)
                    pdf.drawPath(path, stroke=1, fill=0)
            else:
                pdf.setFillColor(HexColor("#D9D9D9"))
                pdf.setStrokeColor(HexColor("#C0392B"))
                pdf.setDash(4, 3)
                pdf.drawPath(path, stroke=1, fill=1)
            pdf.restoreState()
            if stroke_width and align == 'center' and element['photo']:
                pdf.drawPath(path, stroke=1, fill=0)
        elif element["type"] == "text" and element["text"]:
            def draw_text(color, mode=0, width_scale=1):
                if width_scale!=1:
                    pdf.setLineWidth(stroke_width*width_scale*mm)
                paragraph = measurer.paragraph(element["text"], element["font"], element["size"],
                                               element["leading"], element.get("align","left"), color,
                                               letter=element.get("letterSpacing") or 0, render_mode=mode,
                                               underline=bool(element.get("underline")), strike=bool(element.get("strike")))
                _, used = paragraph.wrap(w * mm, 100000)
                offset = {"top": 0, "middle": (h * mm - used) / 2, "bottom": h * mm - used}[element["valign"]]
                paragraph.drawOn(pdf, x * mm, (height - top) * mm - offset - used)
            def paint_text_shadow(color):
                draw_text(color, 0, 1)
            _cast_shadow(pdf, element, paint_text_shadow)
            if stroke_width and element.get('strokeAlign')=='outside':
                draw_text(element["color"], 1, 2)
                draw_text(element["color"], 0, 1)
            elif stroke_width:
                draw_text(element["color"], 2, 1)
            else:
                draw_text(element["color"])
        pdf.restoreState()


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
            spread = document["covers"][owner]
            size = spread.get("size_mm") or document["cover_size_mm"]
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


def _variant_spreads(document: dict, owner: str):
    """(is_cover, spread, size) of one variant in book order."""
    variant = next((v for v in document["variants"] if v["owner"] == owner), None)
    if variant is None:
        raise LayoutError(f"Вариант {owner} не найден")
    for key in variant["sequence"]:
        if key.startswith("cover["):
            spread = document["covers"][owner]
            yield True, spread, spread.get("size_mm") or document["cover_size_mm"]
        else:
            yield False, document["shared_spreads"].get(key) or document["variant_spreads"][owner][key], document["spread_size_mm"]


def export_print_files(document: dict, owner: str, snapshot: dict, root: Path,
                       measurer: ReportLabMeasurer, destination: Path):
    """Printer files of one book as a zip: one sRGB JPEG per spread, or per page for books printed page by page.

    Each spread is drawn to its own PDF and rasterised by PDFium, so the files match the proof PDF exactly.
    Pages a book does not print (the left one of the first spread, the right one of the last) are skipped.
    """
    import zipfile
    import pypdfium2
    from PIL import ImageCms

    settings = document.get("print") or {}
    dpi, per_page = settings.get("dpi", 300), settings.get("files") == "pages"
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    images, spread_no, page_no = _Images(snapshot, root), 0, 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_STORED) as archive:
        def put(name, image):
            buffer = BytesIO()
            image.save(buffer, "JPEG", quality=100, subsampling=0, dpi=(dpi, dpi), icc_profile=icc)
            archive.writestr(name, buffer.getvalue())
        for is_cover, spread, size in _variant_spreads(document, owner):
            buffer = BytesIO()
            pdf = canvas.Canvas(buffer, pagesize=(size[0] * mm, size[1] * mm), invariant=1)
            _draw(pdf, spread, size, measurer, images)
            pdf.showPage()
            pdf.save()
            pixels = round(size[0] / 25.4 * dpi), round(size[1] / 25.4 * dpi)
            page = pypdfium2.PdfDocument(buffer.getvalue())[0]
            image = page.render(scale=pixels[0] / page.get_width()).to_pil().convert("RGB")
            if image.size != pixels:
                image = image.resize(pixels, Image.LANCZOS)
            if is_cover:
                put("cover.jpg", image)
            elif per_page:
                half = pixels[0] // 2
                for side, box in enumerate(((0, 0, half, pixels[1]), (half, 0, pixels[0], pixels[1]))):
                    if side not in spread.get("blank", ()):
                        page_no += 1
                        put(f"page-{page_no:03d}.jpg", image.crop(box))
            else:
                spread_no += 1
                put(f"spread-{spread_no:02d}.jpg", image)
