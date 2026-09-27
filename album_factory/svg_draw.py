"""Safe SVG checks and a vector drawing path for proof PDFs.

The drawer covers the shapes albums actually use: groups, paths, rectangles,
circles, ellipses, lines and polygons, with fill, stroke, dashes and transforms.
Scripts, external links and embedded documents are rejected before storage.
"""
from __future__ import annotations

import math
import re
from xml.etree import ElementTree as ET

from reportlab.lib.colors import Color

_UNSAFE = re.compile(
    r"<!DOCTYPE|<!ENTITY|<script|</script|<foreignObject|<iframe|<embed|<object|javascript:|vbscript:|data:text/html",
    re.I,
)
_PAINT = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon"}
_SKIP = {"defs", "clippath", "mask", "symbol", "pattern", "marker", "filter", "style", "title", "desc", "metadata", "script", "lineargradient", "radialgradient"}
_NUM = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NAMED = {
    "black": (0, 0, 0), "white": (1, 1, 1), "red": (1, 0, 0), "green": (0, 0.5, 0), "blue": (0, 0, 1),
    "gray": (0.5, 0.5, 0.5), "grey": (0.5, 0.5, 0.5), "orange": (1, 0.65, 0), "yellow": (1, 1, 0),
    "purple": (0.5, 0, 0.5), "navy": (0, 0, 0.5), "silver": (0.75, 0.75, 0.75),
}


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def svg_is_safe(value) -> bool:
    if not isinstance(value, str) or not 20 <= len(value) <= 200_000 or _UNSAFE.search(value):
        return False
    if re.search(r"\son[a-z]+\s*=", value, re.I):
        return False
    try:
        root = ET.fromstring(value)
    except ET.ParseError:
        return False
    if local(root.tag) != "svg":
        return False
    for element in root.iter():
        if local(element.tag) in {"script", "foreignobject", "iframe", "embed", "object"}:
            return False
        for name, attr in element.attrib.items():
            if local(name).startswith("on"):
                return False
            if local(name) in {"href"} and attr and not attr.startswith("#"):
                return False
    return True


def _length(value):
    if not value:
        return None
    match = _NUM.search(str(value))
    return float(match.group()) if match else None


def _view_box(root):
    raw = root.get("viewBox")
    if raw:
        parts = [float(item) for item in re.split(r"[\s,]+", raw.strip()) if item]
        if len(parts) == 4 and parts[2] > 0 and parts[3] > 0:
            return parts
    width, height = _length(root.get("width")) or 100, _length(root.get("height")) or 100
    return [0, 0, width or 100, height or 100]


def _color(value, opacity=1):
    if not value:
        return None
    text = value.strip().lower()
    if text in {"none", "transparent"} or text.startswith("url("):
        return None
    alpha = opacity
    rgb = None
    if text.startswith("#"):
        hex_color = text[1:]
        if len(hex_color) == 3:
            hex_color = "".join(ch * 2 for ch in hex_color)
        if len(hex_color) == 8:
            alpha *= int(hex_color[6:], 16) / 255
            hex_color = hex_color[:6]
        if len(hex_color) == 6:
            rgb = tuple(int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    elif text.startswith("rgb"):
        nums = [float(item) for item in _NUM.findall(text)]
        if len(nums) >= 3:
            rgb = tuple(channel / 255 if channel > 1 else channel for channel in nums[:3])
            if len(nums) >= 4:
                alpha *= nums[3] if nums[3] <= 1 else nums[3] / 255
    elif text in _NAMED:
        rgb = _NAMED[text]
    if not rgb:
        return None
    return Color(rgb[0], rgb[1], rgb[2], alpha=max(0, min(1, alpha)))


def _styles(element, parent):
    style = dict(parent)
    raw = element.get("style") or ""
    declared = {}
    for chunk in raw.split(";"):
        if ":" in chunk:
            key, value = chunk.split(":", 1)
            declared[key.strip().lower()] = value.strip()
    for key in ("fill", "stroke", "stroke-width", "stroke-opacity", "fill-opacity", "opacity", "stroke-linecap", "stroke-linejoin", "stroke-dasharray", "fill-rule"):
        if element.get(key) is not None:
            declared[key] = element.get(key)
    if "opacity" in declared:
        try:
            style["opacity"] *= float(declared["opacity"])
        except ValueError:
            pass
    if "fill" in declared:
        style["fill"] = declared["fill"]
    if "stroke" in declared:
        style["stroke"] = declared["stroke"]
    if "stroke-width" in declared:
        width = _length(declared["stroke-width"])
        if width is not None:
            style["stroke_width"] = width
    if "fill-opacity" in declared:
        try:
            style["fill_opacity"] = float(declared["fill-opacity"])
        except ValueError:
            pass
    if "stroke-opacity" in declared:
        try:
            style["stroke_opacity"] = float(declared["stroke-opacity"])
        except ValueError:
            pass
    for source, target in (("stroke-linecap", "cap"), ("stroke-linejoin", "join"), ("stroke-dasharray", "dash"), ("fill-rule", "rule")):
        if source in declared:
            style[target] = declared[source]
    return style


def _set_paint(element, key, value):
    element.set(key, value)
    raw = element.get("style")
    if not raw or key not in raw.lower():
        return
    parts = []
    for chunk in raw.split(";"):
        if ":" not in chunk:
            continue
        name, _ = chunk.split(":", 1)
        if name.strip().lower() != key:
            parts.append(chunk.strip())
    parts.append(f"{key}:{value}")
    element.set("style", ";".join(parts))


def present_svg(source, layer):
    """Bake fill and stroke overrides. Original paint is kept until a mode asks otherwise."""
    fill_mode = layer.get("fillMode") or "original"
    stroke_mode = layer.get("strokeMode") or "original"
    if fill_mode == "original" and stroke_mode == "original":
        return source
    ET.register_namespace("", "http://www.w3.org/2000/svg")
    root = ET.fromstring(source)
    box = layer.get("box") or {}
    view = _view_box(root)
    height = float(box.get("h") or view[3] or 1)
    user_stroke = float(layer.get("strokeWidth") or 0) * view[3] / height if height else 0

    def visit(element, skipped=False):
        name = local(element.tag)
        skip = skipped or name in _SKIP
        if not skip and name in _PAINT:
            if fill_mode == "none":
                _set_paint(element, "fill", "none")
            elif fill_mode == "color":
                _set_paint(element, "fill", layer.get("fill") or "#29282d")
            if stroke_mode == "none":
                _set_paint(element, "stroke", "none")
            elif stroke_mode == "color":
                _set_paint(element, "stroke", layer.get("stroke") or "#29282d")
                _set_paint(element, "stroke-width", f"{user_stroke:.4f}")
                _set_paint(element, "stroke-linecap", layer.get("strokeCap") or "butt")
                _set_paint(element, "stroke-linejoin", layer.get("strokeJoin") or "miter")
                dash = layer.get("strokeDash") or "solid"
                if dash == "dashed":
                    pattern = f"{user_stroke * 2:.3f} {user_stroke * 1.2:.3f}"
                elif dash == "dotted":
                    pattern = f"{max(user_stroke * 0.15, 0.2):.3f} {user_stroke * 1.2:.3f}"
                else:
                    pattern = "none"
                _set_paint(element, "stroke-dasharray", pattern)
        for child in list(element):
            visit(child, skip)

    visit(root)
    return ET.tostring(root, encoding="unicode")


def _multiply(a, b):
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _parse_transform(value):
    matrix = (1, 0, 0, 1, 0, 0)
    if not value:
        return matrix
    for name, args in re.findall(r"([a-zA-Z]+)\s*\(([^)]*)\)", value):
        nums = [float(item) for item in _NUM.findall(args)]
        if name == "matrix" and len(nums) == 6:
            step = tuple(nums)
        elif name == "translate" and nums:
            step = (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0)
        elif name == "scale" and nums:
            step = (nums[0], 0, 0, nums[1] if len(nums) > 1 else nums[0], 0, 0)
        elif name == "rotate" and nums:
            angle = math.radians(nums[0])
            cos, sin = math.cos(angle), math.sin(angle)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(nums) == 3:
                step = _multiply((1, 0, 0, 1, nums[1], nums[2]), _multiply(step, (1, 0, 0, 1, -nums[1], -nums[2])))
        elif name == "skewX" and nums:
            step = (1, 0, math.tan(math.radians(nums[0])), 1, 0, 0)
        elif name == "skewY" and nums:
            step = (1, math.tan(math.radians(nums[0])), 0, 1, 0, 0)
        else:
            continue
        matrix = _multiply(matrix, step)
    return matrix


def _apply(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _arc_curves(x0, y0, rx, ry, phi, large, sweep, x1, y1):
    if math.hypot(x1 - x0, y1 - y0) < 1e-6:
        return []
    if rx == 0 or ry == 0:
        return None
    phi = math.radians(phi % 360)
    cos, sin = math.cos(phi), math.sin(phi)
    dx, dy = (x0 - x1) / 2, (y0 - y1) / 2
    x1p, y1p = cos * dx + sin * dy, -sin * dx + cos * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1p * x1p / (rx * rx) + y1p * y1p / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    sign = -1 if bool(large) == bool(sweep) else 1
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = sign * math.sqrt(max(0, num / den)) if den else 0
    cxp, cyp = coef * rx * y1p / ry, coef * -ry * x1p / rx
    cx = cos * cxp - sin * cyp + (x0 + x1) / 2
    cy = sin * cxp + cos * cyp + (y0 + y1) / 2

    def angle(ux, uy, vx, vy):
        dot = ux * vx + uy * vy
        norm = math.hypot(ux, uy) * math.hypot(vx, vy) or 1
        result = math.acos(min(1, max(-1, dot / norm)))
        if ux * vy - uy * vx < 0:
            result = -result
        return result

    theta = angle(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    delta = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi
    segments = max(1, math.ceil(abs(delta) / (math.pi / 2)))
    step = delta / segments
    curves = []
    for index in range(segments):
        start, end = theta + index * step, theta + (index + 1) * step
        alpha = math.sin(step) * (math.sqrt(4 + 3 * math.tan(step / 2) ** 2) - 1) / 3

        def point(t, _cos=cos, _sin=sin):
            return (_cos * rx * math.cos(t) - _sin * ry * math.sin(t) + cx, _sin * rx * math.cos(t) + _cos * ry * math.sin(t) + cy)

        def deriv(t, _cos=cos, _sin=sin):
            return (-_cos * rx * math.sin(t) - _sin * ry * math.cos(t), -_sin * rx * math.sin(t) + _cos * ry * math.cos(t))

        p1, p2, d1, d2 = point(start), point(end), deriv(start), deriv(end)
        curves.append((p1[0] + alpha * d1[0], p1[1] + alpha * d1[1], p2[0] - alpha * d2[0], p2[1] - alpha * d2[1], p2[0], p2[1]))
    return curves


def _path_commands(d, matrix, mapper):
    tokens = []
    index = 0
    while index < len(d):
        if d[index].isspace() or d[index] == ",":
            index += 1
            continue
        if d[index] in "MmLlHhVvCcSsQqTtAaZz":
            tokens.append(d[index])
            index += 1
            continue
        match = _NUM.match(d, index)
        if not match:
            break
        tokens.append(float(match.group()))
        index = match.end()
    commands = []
    cursor = start = (0, 0)
    control = cursor
    command = None
    position = 0
    while position < len(tokens):
        if isinstance(tokens[position], str):
            command = tokens[position]
            position += 1
        if command is None:
            break
        relative = command.islower()
        kind = command.upper()
        need = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}[kind]
        if position + need > len(tokens):
            break
        args = tokens[position:position + need]
        position += need
        if kind == "Z":
            commands.append(("Z",))
            cursor = start
            continue
        if kind == "M":
            x = cursor[0] + args[0] if relative else args[0]
            y = cursor[1] + args[1] if relative else args[1]
            cursor = start = (x, y)
            commands.append(("M", mapper(*_apply(matrix, x, y))))
            command = "l" if relative else "L"
            continue
        if kind == "H":
            x = cursor[0] + args[0] if relative else args[0]
            cursor = (x, cursor[1])
            commands.append(("L", mapper(*_apply(matrix, *cursor))))
        elif kind == "V":
            y = cursor[1] + args[0] if relative else args[0]
            cursor = (cursor[0], y)
            commands.append(("L", mapper(*_apply(matrix, *cursor))))
        elif kind == "L":
            x = cursor[0] + args[0] if relative else args[0]
            y = cursor[1] + args[1] if relative else args[1]
            cursor = (x, y)
            commands.append(("L", mapper(*_apply(matrix, x, y))))
        elif kind in {"C", "S", "Q", "T"}:
            points = []
            if kind == "S":
                reflected = (2 * cursor[0] - control[0], 2 * cursor[1] - control[1]) if control else cursor
                points.extend(reflected)
                nums = args
            elif kind == "T":
                reflected = (2 * cursor[0] - control[0], 2 * cursor[1] - control[1]) if control else cursor
                points.extend(reflected)
                nums = args
            else:
                nums = args
            for i in range(0, len(nums), 2):
                x = cursor[0] + nums[i] if relative else nums[i]
                y = cursor[1] + nums[i + 1] if relative else nums[i + 1]
                points.append((x, y))
            if kind in {"Q", "T"}:
                (qx, qy), (x, y) = points[-2], points[-1]
                c1 = (cursor[0] + 2 / 3 * (qx - cursor[0]), cursor[1] + 2 / 3 * (qy - cursor[1]))
                c2 = (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y))
                control = (qx, qy)
            else:
                (c1x, c1y), (c2x, c2y), (x, y) = points[-3], points[-2], points[-1]
                c1, c2, control = (c1x, c1y), (c2x, c2y), (c2x, c2y)
            commands.append(("C", mapper(*_apply(matrix, *c1)), mapper(*_apply(matrix, *c2)), mapper(*_apply(matrix, x, y))))
            cursor = (x, y)
        elif kind == "A":
            rx, ry, phi, large, sweep, dx, dy = args
            x = cursor[0] + dx if relative else dx
            y = cursor[1] + dy if relative else dy
            curves = _arc_curves(cursor[0], cursor[1], rx, ry, phi, large >= 1, sweep >= 1, x, y)
            if not curves:
                commands.append(("L", mapper(*_apply(matrix, x, y))))
            else:
                for c1x, c1y, c2x, c2y, ex, ey in curves:
                    commands.append(("C", mapper(*_apply(matrix, c1x, c1y)), mapper(*_apply(matrix, c2x, c2y)), mapper(*_apply(matrix, ex, ey))))
            cursor = (x, y)
            control = cursor
        if kind not in {"C", "S", "Q", "T"}:
            control = cursor
    return commands


def _points(value):
    nums = [float(item) for item in _NUM.findall(value or "")]
    return list(zip(nums[::2], nums[1::2]))


def draw_svg(pdf, source, x, bottom, w, h, align="center"):
    """Draw SVG into a point-sized box. `bottom` is the PDF y of the box bottom."""
    if not svg_is_safe(source) or w <= 0 or h <= 0:
        return
    root = ET.fromstring(source)
    min_x, min_y, view_w, view_h = _view_box(root)

    def mapper(px, py):
        return x + (px - min_x) / view_w * w, bottom + h - (py - min_y) / view_h * h

    def paint(commands, style, matrix):
        if not commands:
            return
        path = pdf.beginPath()
        for command in commands:
            if command[0] == "M":
                path.moveTo(*command[1])
            elif command[0] == "L":
                path.lineTo(*command[1])
            elif command[0] == "C":
                path.curveTo(*command[1], *command[2], *command[3])
            else:
                path.close()
        opacity = style["opacity"]
        fill = _color(style["fill"], opacity * style["fill_opacity"]) if style["fill"] not in {None, "none"} else None
        stroke = _color(style["stroke"], opacity * style["stroke_opacity"]) if style["stroke"] not in {None, "none"} else None
        sx, sy = math.hypot(matrix[0], matrix[1]), math.hypot(matrix[2], matrix[3])
        scale = ((w / view_w) * sx + (h / view_h) * sy) / 2
        width = max(0, style["stroke_width"] * scale)
        caps = {"butt": 0, "round": 1, "square": 2}
        joins = {"miter": 0, "round": 1, "bevel": 2}
        pdf.setLineCap(caps.get(style["cap"], 0))
        pdf.setLineJoin(joins.get(style["join"], 0))
        dash = style["dash"]
        if dash and dash not in {"none", "0"}:
            parts = [abs(float(item)) * scale for item in _NUM.findall(dash)]
            if len(parts) >= 2 and any(parts):
                pdf.setDash(parts)
            else:
                pdf.setDash()
        else:
            pdf.setDash()
        if style["rule"] == "evenodd" and hasattr(path, "fillMode"):
            path.fillMode = 1
        do_stroke = stroke is not None and width > 0.05
        if align == "inside" and do_stroke and fill is not None:
            pdf.saveState()
            pdf.clipPath(path, stroke=0, fill=0)
            pdf.setStrokeColor(stroke)
            pdf.setFillColor(fill)
            pdf.setLineWidth(width * 2)
            pdf.drawPath(path, stroke=1, fill=1)
            pdf.restoreState()
            return
        if align == "outside" and do_stroke and fill is not None:
            pdf.setStrokeColor(stroke)
            pdf.setFillColor(fill)
            pdf.setLineWidth(width * 2)
            pdf.drawPath(path, stroke=1, fill=0)
            pdf.drawPath(path, stroke=0, fill=1)
            return
        if fill is not None:
            pdf.setFillColor(fill)
        if do_stroke:
            pdf.setStrokeColor(stroke)
            pdf.setLineWidth(width)
        if fill is not None or do_stroke:
            pdf.drawPath(path, stroke=1 if do_stroke else 0, fill=1 if fill is not None else 0)

    def shape_commands(element, matrix):
        name = local(element.tag)
        if name == "path":
            return _path_commands(element.get("d") or "", matrix, mapper)
        if name == "rect":
            rx = _length(element.get("x")) or 0
            ry = _length(element.get("y")) or 0
            width = _length(element.get("width")) or 0
            height = _length(element.get("height")) or 0
            points = [(rx, ry), (rx + width, ry), (rx + width, ry + height), (rx, ry + height)]
            mapped = [mapper(*_apply(matrix, *point)) for point in points]
            return [("M", mapped[0]), ("L", mapped[1]), ("L", mapped[2]), ("L", mapped[3]), ("Z",)]
        if name in {"circle", "ellipse"}:
            cx = _length(element.get("cx")) or 0
            cy = _length(element.get("cy")) or 0
            rx = _length(element.get("r") if name == "circle" else element.get("rx")) or 0
            ry = _length(element.get("r") if name == "circle" else element.get("ry")) or 0
            curves = []
            for index, (a0, a1) in enumerate(((0, 90), (90, 180), (180, 270), (270, 360))):
                # Quarter-circle via the arc converter in user space, then mapped.
                p0 = (cx + rx * math.cos(math.radians(a0)), cy + ry * math.sin(math.radians(a0)))
                p1 = (cx + rx * math.cos(math.radians(a1)), cy + ry * math.sin(math.radians(a1)))
                piece = _arc_curves(*p0, rx, ry, 0, 0, 1, *p1) or []
                if index == 0 and piece:
                    curves.append(("M", mapper(*_apply(matrix, *p0))))
                for c1x, c1y, c2x, c2y, ex, ey in piece:
                    curves.append(("C", mapper(*_apply(matrix, c1x, c1y)), mapper(*_apply(matrix, c2x, c2y)), mapper(*_apply(matrix, ex, ey))))
            curves.append(("Z",))
            return curves
        if name == "line":
            start = mapper(*_apply(matrix, _length(element.get("x1")) or 0, _length(element.get("y1")) or 0))
            end = mapper(*_apply(matrix, _length(element.get("x2")) or 0, _length(element.get("y2")) or 0))
            return [("M", start), ("L", end)]
        if name in {"polyline", "polygon"}:
            points = [mapper(*_apply(matrix, *point)) for point in _points(element.get("points"))]
            if not points:
                return []
            commands = [("M", points[0])] + [("L", point) for point in points[1:]]
            if name == "polygon":
                commands.append(("Z",))
            return commands
        return []

    base = {"fill": "#000000", "stroke": "none", "stroke_width": 1, "opacity": 1, "fill_opacity": 1, "stroke_opacity": 1, "cap": "butt", "join": "miter", "dash": "none", "rule": "nonzero"}

    def visit(element, matrix, inherited, skipped=False):
        name = local(element.tag)
        skip = skipped or name in _SKIP
        here = _multiply(matrix, _parse_transform(element.get("transform")))
        style = _styles(element, inherited)
        if not skip and name in _PAINT and element.get("display") != "none" and element.get("visibility") != "hidden":
            paint(shape_commands(element, here), style, here)
        if not skip:
            for child in list(element):
                visit(child, here, style, False)

    visit(root, (1, 0, 0, 1, 0, 0), base)
