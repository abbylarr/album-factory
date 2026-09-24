import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pypdf import PdfReader

from album_factory.layout_engine import (LayoutEngine, LayoutError, auto_crop, balance_flow,
                                         capacity_matrix, field_limits, load_edition, plan_sections)

EDITION = Path(__file__).resolve().parents[1] / "examples/editions/classic-v1.json"


class FakeMeasurer:
    """Monospace approximation: half an em per character, no font file needed."""

    def height(self, text, font, size, leading, width):
        per_line = max(1, int(width / (size * 0.3528 * 0.5)))
        lines = sum(max(1, -(-len(part) // per_line)) for part in text.split("\n"))
        return lines * leading * 0.3528

    def missing_glyphs(self, text, font):
        return set()


def snapshot(students=12, teachers=3, teacher_variant=True):
    photos = {"class": {"path": "class.jpg", "width": 6000, "height": 4000}}
    selections = [{"owner": "order", "role": "class_photo", "photo": "class"}]
    people, staff = [], []
    for i in range(students):
        sid = f"S{i + 1:02d}"
        photos[f"p-{sid}"] = {"path": "portrait.jpg", "width": 2400, "height": 3300,
                              "face": [0.35, 0.2, 0.3, 0.26]}
        people.append({"id": sid, "first_name": "Анна", "last_name": f"Иванова{i}", "quote": "Привет"})
        selections.append({"owner": f"student:{sid}", "role": "main_portrait", "photo": f"p-{sid}"})
    for i in range(teachers):
        tid = f"T{i + 1:02d}"
        photos[f"p-{tid}"] = {"path": "portrait.jpg", "width": 2400, "height": 3300}
        staff.append({"id": tid, "first_name": "Мария", "last_name": f"Петрова{i}",
                      "school_subject": "Физика", "is_class_teacher": i == 1})
        selections.append({"owner": f"teacher:{tid}", "role": "main_portrait", "photo": f"p-{tid}"})
    return {"schema_version": 2,
            "order": {"id": "o1", "school": "Школа", "class_name": "11 А", "year": "2026"},
            "students": people, "teachers": staff, "photos": photos, "selections": selections,
            "teacher_variant": {"enabled": teacher_variant}}


class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.edition = load_edition(EDITION)
        self.engine = LayoutEngine(self.edition, FakeMeasurer())

    def section(self, section_id):
        return next(s for s in self.edition["sections"] if s["id"] == section_id)

    def test_ten_teachers_are_balanced_not_nine_plus_one(self):
        states = [{"id": "a", "min": 1, "max": 9}]
        self.assertEqual([c for c, _ in balance_flow(10, states, 2)], [5, 5])
        document = self.engine.generate(snapshot(students=12, teachers=10))
        spread = document["shared_spreads"]["teachers#0"]
        self.assertEqual(spread["state"], "t9_12")
        cells = [e for e in spread["elements"] if e["key"].endswith("/portrait")]
        left = [e for e in cells if e["box"][0] < 210]
        self.assertEqual((len(left), len(cells) - len(left)), (5, 5))

    def test_spread_count_follows_class_size_but_is_equal_for_all_variants(self):
        small = self.engine.generate(snapshot(students=12))
        large = self.engine.generate(snapshot(students=30))
        self.assertEqual(small["spread_count"], 5)
        self.assertEqual(large["spread_count"], 6)
        for document in (small, large):
            self.assertEqual({len(v["sequence"]) for v in document["variants"]},
                             {document["spread_count"] + 1})
        self.assertGreater(large["cover_size_mm"][0], small["cover_size_mm"][0])

    def test_filler_then_expansion_reach_minimum_spreads(self):
        document = self.engine.generate(snapshot(students=8, teachers=0))
        self.assertEqual(document["spread_count"], 5)
        self.assertIn("moments", [p["section"] for p in document["plan"]])

    def test_capacity_is_a_clear_error_before_layout(self):
        with self.assertRaisesRegex(LayoutError, "3–54 учеников"):
            self.engine.generate(snapshot(students=60))

    def test_every_declared_class_size_has_a_prepared_composition(self):
        self.assertEqual(capacity_matrix(self.edition), [])

    def test_matrix_reports_gap_in_states(self):
        edition = copy.deepcopy(self.edition)
        students = self.section_in(edition, "students")
        students["states"] = [s for s in students["states"] if s["id"] != "s3_8"]
        failures = capacity_matrix(edition)
        self.assertEqual(sorted({f["students"] for f in failures}), list(range(3, 9)))

    @staticmethod
    def section_in(edition, section_id):
        return next(s for s in edition["sections"] if s["id"] == section_id)

    def test_generation_is_deterministic(self):
        first = self.engine.generate(snapshot())
        second = self.engine.generate(snapshot())
        self.assertEqual(first["revision"], second["revision"])
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_student_sees_own_class_spread_first(self):
        document = self.engine.generate(snapshot(students=23))
        variants = {v["owner"]: v["sequence"] for v in document["variants"]}
        first_half = [k for k in variants["student:S01"] if k.startswith("students#")]
        second_half = [k for k in variants["student:S23"] if k.startswith("students#")]
        self.assertEqual(first_half, ["students#0", "students#1"])
        self.assertEqual(second_half, ["students#1", "students#0"])

    def test_teacher_variant_falls_back_to_class_photo_and_class_teacher_name(self):
        document = self.engine.generate(snapshot())
        spread = document["variant_spreads"]["teacher_variant"]["personal[teacher_variant]"]
        photo = next(e for e in spread["elements"] if e["type"] == "photo")
        name = next(e for e in spread["elements"] if e["key"].endswith("/name"))
        self.assertEqual(photo["photo"], "class")
        self.assertEqual(name["text"], "Петрова1 Мария")
        order = [k for k in document["shared_spreads"]["teachers#0"]["items"]]
        self.assertEqual(order[0], "teacher:T02")

    def test_empty_required_slot_is_an_error(self):
        data = snapshot()
        data["selections"] = [s for s in data["selections"] if s["owner"] != "student:S03"]
        document = self.engine.generate(data)
        keys = {i["key"] for i in document["issues"] if i["code"] == "empty_slot"}
        self.assertIn("students/cell[student:S03]/portrait", keys)
        self.assertIn("personal[student:S03]/portrait", keys)

    def test_overflow_is_reported_not_truncated(self):
        data = snapshot()
        data["students"][0]["quote"] = "очень длинная цитата " * 30
        document = self.engine.generate(data)
        codes = {(i["code"], i["key"]) for i in document["issues"]}
        self.assertIn(("text_overflow", "students/cell[student:S01]/quote"), codes)

    def test_form_limits_come_from_tightest_slot(self):
        self.assertEqual(field_limits(self.edition)["quote"], 180)

    def test_reorderable_section_cannot_have_first_only_elements(self):
        edition = copy.deepcopy(self.edition)
        edition["templates"]["students_grid"]["first_elements"] = [
            {"id": "x", "type": "rect", "box": [0, 0, 1, 1], "fill": "#000000"}]
        with self.assertRaises(LayoutError):
            LayoutEngine(edition, FakeMeasurer())


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.engine = LayoutEngine(load_edition(EDITION), FakeMeasurer())
        self.crop = {"key": "students/cell[student:S05]/portrait", "type": "crop", "base": "p-S05",
                     "value": {"photo": "p-S05", "rect": [0.1, 0.1, 0.5, 0.5]}}

    def cell(self, document, key):
        for spread in document["shared_spreads"].values():
            for element in spread["elements"]:
                if element["key"] == key:
                    return element

    def test_crop_survives_state_change_when_class_grows(self):
        before = self.engine.generate(snapshot(students=12), [self.crop])
        after = self.engine.generate(snapshot(students=13), [self.crop])
        self.assertNotEqual(before["shared_spreads"]["students#0"]["state"],
                            after["shared_spreads"]["students#0"]["state"])
        self.assertEqual(after["overrides"]["conflicts"], [])
        element = self.cell(after, self.crop["key"])
        self.assertIn("crop", element["overridden"])
        self.assertAlmostEqual(element["crop"][0], 240, delta=1)

    def test_changed_selection_turns_crop_into_conflict(self):
        data = snapshot(students=12)
        data["photos"]["p-new"] = dict(data["photos"]["p-S05"])
        for item in data["selections"]:
            if item["owner"] == "student:S05":
                item["photo"] = "p-new"
        document = self.engine.generate(data, [self.crop])
        self.assertEqual(document["overrides"]["conflicts"][0]["reason"], "base_changed")

    def test_removed_student_turns_override_into_missing(self):
        data = snapshot(students=12)
        data["students"] = [s for s in data["students"] if s["id"] != "S05"]
        data["selections"] = [s for s in data["selections"] if s["owner"] != "student:S05"]
        document = self.engine.generate(data, [self.crop])
        self.assertEqual(document["overrides"]["conflicts"][0]["reason"], "missing")

    def test_text_override_is_refitted(self):
        override = {"key": "students/cell[student:S01]/name", "type": "text", "base": "Анна Иванова0",
                    "value": "Анна-Мария Иванова-Петрова"}
        document = self.engine.generate(snapshot(), [override])
        element = self.cell(document, override["key"])
        self.assertEqual(element["text"], "Анна-Мария Иванова-Петрова")
        self.assertEqual(element["overridden"], ["text"])


class CropTests(unittest.TestCase):
    def test_face_crop_keeps_slot_aspect_and_stays_inside_image(self):
        x, y, w, h = auto_crop(2400, 3300, 50, 60, face=[0.7, 0.05, 0.3, 0.26], face_scale=0.4)
        self.assertAlmostEqual(w / h, 50 / 60, places=2)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + w, 2400.01)
        self.assertLessEqual(y + h, 3300.01)

    def test_face_is_centered_when_there_is_room(self):
        x, _, w, _ = auto_crop(2400, 3300, 50, 60, face=[0.35, 0.3, 0.3, 0.26], face_scale=0.4)
        self.assertAlmostEqual(x + w / 2, 0.5 * 2400, delta=1)

    def test_without_face_crop_is_centered(self):
        self.assertEqual(auto_crop(4000, 2000, 10, 10), [1000, 0, 2000, 2000])


class RenderTests(unittest.TestCase):
    def test_variant_pdf_has_cover_and_all_spreads(self):
        font = os.environ.get("ALBUM_TEST_FONT")
        if not font:
            self.skipTest("Set ALBUM_TEST_FONT to a Cyrillic TTF for PDF integration tests")
        from album_factory.layout_engine import ReportLabMeasurer
        from album_factory.layout_render import export_variants
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGB", (2400, 3300), "gray").save(root / "portrait.jpg")
            Image.new("RGB", (6000, 4000), "white").save(root / "class.jpg")
            measurer = ReportLabMeasurer({"main": Path(font)})
            data = snapshot(students=4, teachers=1)
            document = LayoutEngine(load_edition(EDITION), measurer).generate(data)
            paths = export_variants(document, data, root, measurer, root / "pdf")
            self.assertEqual(len(paths), 5)
            reader = PdfReader(paths[0])
            self.assertEqual(len(reader.pages), document["spread_count"] + 1)
            width_mm = float(reader.pages[0].mediabox.width) / 72 * 25.4
            self.assertAlmostEqual(width_mm, document["cover_size_mm"][0], delta=0.5)


if __name__ == "__main__":
    unittest.main()
