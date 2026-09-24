"""Build a demo class of labelled test cards and run the auto-layout prototype.

Cards are never synthetic human photographs: a drawn target marks the "face"
box so face-aware cropping is visible in the PDF.
"""
import argparse
import json
from pathlib import Path
import random
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from album_factory.layout_engine import LayoutEngine, LayoutError, ReportLabMeasurer, load_edition  # noqa: E402
from album_factory.layout_render import export_variants  # noqa: E402

FEMALE = ["Анна", "Мария", "Дарья", "Полина", "Софья", "Ксения", "Алиса", "Вера", "Ева", "Милана"]
MALE = ["Михаил", "Александр", "Илья", "Артём", "Иван", "Максим", "Егор", "Тимофей", "Лев", "Роман"]
SURNAMES = ["Иванов", "Петров", "Соколов", "Смирнов", "Волков", "Попов", "Козлов", "Морозов",
            "Новиков", "Лебедев", "Павлов", "Орлов", "Зайцев", "Фёдоров", "Белов", "Никитин"]
QUOTES = ["Впереди много интересного", "Спасибо всем за эти годы!",
          "Самое главное — верить в себя и в тех, кто рядом. Мы были отличным классом, и пусть так будет дальше",
          ""]
DEFAULT_FONT = Path("/System/Library/Fonts/Supplemental/Arial.ttf")


def card(path, size, label, face=None, color=(226, 229, 233)):
    image = Image.new("RGB", size, color)
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((20, 20, w - 20, h - 20), outline=(120, 124, 130), width=6)
    draw.text((60, h - 180), label + "\nTEST CARD / NO PERSON", fill=(50, 50, 50), font_size=max(28, w // 24))
    if face:
        fx, fy, fw, fh = face[0] * w, face[1] * h, face[2] * w, face[3] * h
        draw.ellipse((fx, fy, fx + fw, fy + fh), outline=(200, 60, 40), width=8)
        eye = fy + 0.38 * fh
        draw.line((fx, eye, fx + fw, eye), fill=(200, 60, 40), width=4)
        draw.line((fx + fw / 2, fy, fx + fw / 2, fy + fh), fill=(200, 60, 40), width=4)
    image.save(path, quality=90)


def build_class(out: Path, students: int, teachers: int, seed: int):
    rng = random.Random(seed)
    images = out / "images"
    images.mkdir(parents=True, exist_ok=True)
    photos, selections, people, staff = {}, [], [], []

    def portrait(photo_id, label):
        # Off-centre targets show that the crop follows the face, not the frame centre.
        face = [round(rng.uniform(0.18, 0.5), 3), round(rng.uniform(0.12, 0.3), 3), 0.3, 0.26]
        path = f"images/{photo_id}.jpg"
        card(out / path, (2400, 3300), label, face)
        photos[photo_id] = {"path": path, "width": 2400, "height": 3300, "face": face}

    for index in range(students):
        sid = f"S{index + 1:02d}"
        portrait(f"p-{sid}", sid)
        female = index % 2 == 0
        first = (FEMALE if female else MALE)[(index // 2) % 10]
        last = SURNAMES[(index * 7) % len(SURNAMES)] + ("а" if female else "")
        people.append({"id": sid, "first_name": first, "last_name": last, "quote": QUOTES[index % len(QUOTES)]})
        selections.append({"owner": f"student:{sid}", "role": "main_portrait", "photo": f"p-{sid}"})
    subjects = ["Литература", "Математика", "Русский язык", "История", "Физика", "Английский язык",
                "Химия", "Биология", "География", "Информатика"]
    for index in range(teachers):
        tid = f"T{index + 1:02d}"
        portrait(f"p-{tid}", tid)
        staff.append({"id": tid, "first_name": FEMALE[(index + 3) % 10],
                      "last_name": SURNAMES[(index + 5) % len(SURNAMES)] + "а", "patronymic": "Сергеевна",
                      "school_subject": subjects[index % len(subjects)], "is_class_teacher": index == 0})
        selections.append({"owner": f"teacher:{tid}", "role": "main_portrait", "photo": f"p-{tid}"})
    card(out / "images/class.jpg", (6000, 4000), "CLASS PHOTO", color=(214, 222, 230))
    photos["class"] = {"path": "images/class.jpg", "width": 6000, "height": 4000}
    selections.append({"owner": "order", "role": "class_photo", "photo": "class"})
    return {"schema_version": 2,
            "order": {"id": "demo-layout", "school": "Демонстрационная школа № 1", "class_name": "11 А",
                      "year": "2026", "studio": "Студия «Демо»"},
            "students": people, "teachers": staff, "photos": photos, "selections": selections,
            "teacher_variant": {"enabled": True}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=int, default=23)
    parser.add_argument("--teachers", type=int, default=5)
    parser.add_argument("--edition", type=Path, default=ROOT / "examples/editions/classic-v1.json")
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--output", type=Path, default=ROOT / "output/layout-demo")
    parser.add_argument("--all", action="store_true", help="PDF для всех вариантов, а не для двух учеников и учителя")
    args = parser.parse_args()

    snapshot = build_class(args.output, args.students, args.teachers, seed=7)
    (args.output / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    measurer = ReportLabMeasurer({"main": args.font})
    try:
        document = LayoutEngine(load_edition(args.edition), measurer).generate(snapshot)
    except LayoutError as exc:
        raise SystemExit(f"Генерация невозможна: {exc}")
    (args.output / "document.json").write_text(json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Разворотов: {document['spread_count']}, вариантов: {len(document['variants'])}, "
          f"обложка {document['cover_size_mm'][0]} × {document['cover_size_mm'][1]} мм")
    for item in document["plan"]:
        extra = f" · состояния {item['states']} · по {item['counts']}" if "states" in item else ""
        print(f"  {item['section']}: {item['spreads']}{extra}")
    groups = {}
    for issue in document["issues"]:
        groups.setdefault((issue["level"], issue["code"]), []).append(issue)
    for (level, code), items in sorted(groups.items()):
        print(f"  [{level}] {code} × {len(items)}: {items[0]['key']} — {items[0]['message']}")
    variants = document["variants"]
    owners = None if args.all else {variants[0]["owner"], variants[-2]["owner"], variants[-1]["owner"]}
    for path in export_variants(document, snapshot, args.output, measurer, args.output / "pdf", owners):
        print("  PDF:", path.relative_to(ROOT))


if __name__ == "__main__":
    main()
