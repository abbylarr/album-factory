import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest
import os
from PIL import Image
from pypdf import PdfReader

from album_factory.core import compile_album, approval_matches, ValidationError
from album_factory.export import export_csv, export_pdf, export_manifest


class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        Image.new("RGB", (900, 1200), "gray").save(self.root / "portrait.png")
        self.data = {"schema_version": 1,
                     "order": {"id": "o1", "school": "Школа", "class_name": "11 А", "year": "2026", "copies": 20},
                     "people": [{"id": "p1", "first_name": "Анна", "last_name": "Иванова", "role": "student", "quote": "Привет", "portrait": "img1"}],
                     "photos": [{"id": "img1", "path": "portrait.png", "category": "portrait", "people": ["p1"]}],
                     "shared_photos": []}

    def album(self):
        return compile_album(self.data, self.root)

    def add_person(self, index, role="student"):
        person = copy.deepcopy(self.data["people"][0])
        person["id"] = f"p{index}"
        person["role"] = role
        self.data["people"].append(person)
        self.data["photos"][0]["people"].append(person["id"])

    def test_common_album_copies_do_not_duplicate_pages(self):
        album = self.album()
        self.assertEqual(len(album.pages), 2)
        self.assertEqual(album.copies, 20)
        self.assertEqual([p.kind for p in album.pages], ["cover", "student"])

    def test_pagination_no_lost_people_variable_teachers(self):
        for i in range(2, 36):
            self.add_person(i)
        for i in range(36, 48):
            self.add_person(i, "teacher")
        pages = self.album().pages
        self.assertEqual(len([p for p in pages if p.kind == "student"]), 6)
        self.assertEqual(len([p for p in pages if p.kind == "teacher"]), 2)
        self.assertEqual(sum(len(p.ids) for p in pages), 47)

    def test_one_teacher_is_present(self):
        self.add_person(2, "teacher")
        self.assertEqual(self.album().pages[-1].ids, ("p2",))

    def test_wrong_person_portrait_rejected(self):
        self.data["photos"][0]["people"] = []
        with self.assertRaisesRegex(ValidationError, "не принадлежит"):
            self.album()

    def test_duplicate_person_rejected(self):
        self.data["people"].append(copy.deepcopy(self.data["people"][0]))
        with self.assertRaisesRegex(ValidationError, "повторяющиеся"):
            self.album()

    def test_missing_image_rejected(self):
        self.data["photos"][0]["path"] = "missing.jpg"
        with self.assertRaisesRegex(ValidationError, "не найден"):
            self.album()

    def test_path_traversal_rejected(self):
        self.data["photos"][0]["path"] = "../outside.png"
        with self.assertRaisesRegex(ValidationError, "внутри"):
            self.album()

    def test_symlink_escape_rejected(self):
        (self.root / "outside.png").symlink_to(self.root.parent / "outside.png")
        self.data["photos"][0]["path"] = "outside.png"
        with self.assertRaisesRegex(ValidationError, "внутри"):
            self.album()

    def test_revision_changes_after_selection_text_and_bytes(self):
        before = self.album()
        approval = dict(order_id="o1", revision=before.revision, decision="approved")
        self.assertTrue(approval_matches(before, approval))
        self.data["people"][0]["quote"] = "Другая цитата"
        after = self.album()
        self.assertFalse(approval_matches(after, approval))
        Image.new("RGB", (900, 1200), "red").save(self.root / "portrait.png")
        self.assertNotEqual(after.revision, self.album().revision)

    def test_copies_do_not_invalidate_content_approval(self):
        before = self.album().revision
        self.data["order"]["copies"] = 21
        self.assertEqual(before, self.album().revision)

    def test_csv_formula_is_escaped(self):
        self.data["people"][0]["quote"] = '=HYPERLINK("evil")'
        export_csv(self.album(), self.root / "out.csv")
        with (self.root / "out.csv").open(encoding="utf-8-sig") as file:
            rows = list(csv.reader(file, delimiter=";"))
        self.assertEqual(rows[1][4], "'" + self.data["people"][0]["quote"])

    def test_shared_photo_category_is_checked(self):
        self.data["shared_photos"] = ["img1"]
        with self.assertRaisesRegex(ValidationError, "class или group"):
            self.album()

    def test_manifest_declares_proof_and_selected_hashes(self):
        export_manifest(self.album(), self.root / "manifest.json")
        data = json.loads((self.root / "manifest.json").read_text())
        self.assertFalse(data["print_ready"])
        self.assertEqual(data["pdf_count"], 1)
        self.assertEqual(len(data["selected_photos"][0]["sha256"]), 64)

    def font(self):
        path = os.environ.get("ALBUM_TEST_FONT")
        if not path:
            self.skipTest("Set ALBUM_TEST_FONT to a Cyrillic TTF for PDF integration tests")
        return Path(path)

    def test_pdf_pages_cyrillic_and_embedded_font(self):
        output = self.root / "proof.pdf"
        export_pdf(self.album(), output, self.font())
        reader = PdfReader(output)
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("Анна Иванова", reader.pages[1].extract_text())
        self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 210 / 25.4 * 72, places=3)
        fonts = reader.pages[1]["/Resources"]["/Font"].get_object().values()
        self.assertTrue(any("/FontFile2" in font.get_object().get("/FontDescriptor", {}) for font in fonts))

    def test_text_overflow_is_not_silently_clipped(self):
        self.data["people"][0]["first_name"] = "Ш" * 50
        self.data["people"][0]["last_name"] = "Ш" * 70
        output = self.root / "bad.pdf"
        with self.assertRaisesRegex(ValidationError, "не помещается"):
            export_pdf(self.album(), output, self.font())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
