"""Create clearly labelled test cards, never synthetic human photographs."""
import json
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1] / "examples"
root.mkdir(exist_ok=True)
(root / "images").mkdir(exist_ok=True)
names = [("Анна", "Иванова"), ("Михаил", "Петров"), ("Мария", "Соколова"),
         ("Александр", "Смирнов"), ("Дарья", "Волкова"), ("Илья", "Попов"),
         ("Полина", "Козлова")]
people, photos = [], []
for index, (first, last) in enumerate(names, 1):
    person_id, photo_id = f"person-{index}", f"photo-{index}"
    path = f"images/{photo_id}.png"
    im = Image.new("RGB", (900, 1200), (231, 233, 236))
    draw = ImageDraw.Draw(im)
    draw.rectangle((50, 50, 850, 1150), outline=(110, 115, 122), width=5)
    draw.text((100, 450), f"TEST CARD {index:02}\nNO PERSON PHOTO", fill=(40, 40, 40), font_size=60)
    im.save(root / path)
    people.append(dict(id=person_id, first_name=first, last_name=last, role="student",
                       quote="Впереди много интересного", portrait=photo_id))
    photos.append(dict(id=photo_id, path=path, category="portrait", people=[person_id]))
Image.new("RGB", (2400, 1400), (215, 223, 230)).save(root / "images/class.png")
with Image.open(root / "images/class.png") as im:
    ImageDraw.Draw(im).text((180, 580), "SHARED PAGE - TEST CARD", fill=(35, 40, 50), font_size=100)
    im.save(root / "images/class.png")
photos.append(dict(id="class-photo", path="images/class.png", category="class", people=[p["id"] for p in people]))
data = dict(schema_version=1, order=dict(id="demo-order", school="Демонстрационная школа",
            class_name="11 А", year="2026", copies=20), people=people, photos=photos,
            shared_photos=["class-photo"])
(root / "order.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print("Created demo manifest with 7 fictional pupils and numbered test cards")
