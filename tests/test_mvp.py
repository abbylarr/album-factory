"""Acceptance checks for the local MVP: studios, catalogue, pins, copies and export."""
import json
import unittest
from fastapi.testclient import TestClient
from album_factory.layout_engine import load_edition
from album_factory.server import ROOT
import test_server_v2


def mini_edition():
    document = load_edition(ROOT / "examples/editions/classic-v1.json")
    document["id"] = "mini"
    document["version"] = 1
    document["capacity"] = {"students": [3, 3], "teachers": [0, 0]}
    return document


class MvpTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def publish(self):
        edition = self.client.post("/api/catalog/editions", json={"document": mini_edition()}).json()
        offer = self.client.post("/api/offers", json={"title": "Стандарт", "price": 1500, "edition_id": edition["id"]}).json()
        return offer["id"]

    def people(self, count):
        from album_factory import server as s
        with s.db() as con:
            for index in range(count):
                con.execute("INSERT INTO persons VALUES (?,?,?,?)", (
                    f"p{index:02d}", self.order, "", f"2020-01-01T00:00:{index:02d}+00:00"))

    def link(self):
        data = self.client.post(f"/api/orders/{self.order}/client-link").json()
        token = data["url"].rsplit("/", 1)[1]
        self.client.post(f"/client-api/{token}/enter", json={"pin": data["entry_pin"]})
        return token, data

    def layout(self):
        from album_factory import server as s
        document = {"revision": "rev-1", "variants": [{"owner": "p00", "name": "Первый"}]}
        with s.db() as con:
            con.execute("INSERT INTO order_layouts VALUES (?,?,?,?,?)", (
                self.order, "{}", json.dumps(document), "[]", s.now()))
        self.client.post(f"/api/orders/{self.order}/layout/publish")

    def test_studios_do_not_see_each_other(self):
        other = TestClient(self.client.app)
        other.headers["origin"] = "http://testserver"
        registered = other.post("/api/register", json={"email": "b@studio.test", "password": "secret-pass", "studio_name": "Вторая"}).json()
        self.assertTrue(registered["studio_id"])
        self.assertEqual(other.get("/api/orders").json(), [])
        self.assertEqual(other.get(f"/api/orders/{self.order}").status_code, 404)

    def test_offer_snapshot_and_capacity(self):
        offer = self.publish()
        self.client.put("/api/profile", json={"teacher_gift": False, "delivery_modes": "personal"})
        created = self.client.post("/api/orders", json={
            'school_city': 'Казань',
            "school": "Лицей", "class_name": "11А", "copies": 20, "customer_name": "Ирина Петрова",
            "customer_contact": "+79990000000", "offer_id": offer, "student_count": 2})
        self.assertEqual(created.status_code, 422)
        created = self.client.post("/api/orders", json={
            'school_city': 'Казань',
            "school": "Лицей", "class_name": "11А", "copies": 20, "customer_name": "Ирина Петрова",
            "customer_contact": "+79990000000", "offer_id": offer, "student_count": 3}).json()
        self.client.put("/api/profile", json={"teacher_gift": True, "delivery_modes": "shipping"})
        deal = self.client.get(f"/api/orders/{created['id']}/deal").json()
        self.assertEqual(deal["offer_price"], 1500)
        self.assertEqual(deal["gift"], 0)
        self.assertEqual(deal["delivery_modes"], "personal")
        self.assertEqual(deal["delivery"], None)
        fresh_offer = self.client.post("/api/offers", json={"title": "Стандарт", "price": 9000, "edition_id": "mini"}).json()
        self.assertNotEqual(fresh_offer["id"], offer)
        self.assertEqual(self.client.get(f"/api/orders/{created['id']}/deal").json()["offer_price"], 1500)

    def test_copy_rules_pins_and_export(self):
        self.client.put("/api/profile", json={"teacher_gift": True, "delivery_modes": "both"})
        self.people(19)
        deal = self.client.get(f"/api/orders/{self.order}/deal").json()
        paid = {row["key"]: row["paid"] for row in deal["allocations"] if row["key"] != "gift"}
        self.assertEqual(set(paid.values()), {1})
        self.assertEqual(len(paid), 19)
        self.assertEqual(sum(paid.values()), 19)
        self.assertEqual(deal["planned_paid"], 20)
        self.assertTrue(any(row["key"] == "gift" and row["paid"] == 0 and row["gift"] == 1 for row in deal["allocations"]))
        self.layout()
        token, pins = self.link()
        summary = self.client.get(f"/client-api/{token}/summary").json()
        self.assertNotIn("price", json.dumps(summary))
        self.assertNotIn("offer_price", summary)
        self.assertEqual(summary["remainder"], 1)
        entry = TestClient(self.client.app)
        entry.headers["origin"] = "http://testserver"
        entry.post(f"/client-api/{token}/enter", json={"pin": pins["entry_pin"]})
        blocked = entry.post(f"/client-api/{token}/approve", json={"hash": summary["hash"]})
        self.assertEqual(blocked.status_code, 401)
        summary = self.client.put(f"/client-api/{token}/summary", json={
            "allocations": [{**row, "paid": 2 if row["key"] == "p00" else row["paid"]} for row in summary["allocations"]],
            "paid_total": 20,
            "delivery": {"mode": "personal", "carrier": "секрет", "address": "скрыть", "recipient": "Ирина", "phone": "1"},
        }).json()
        self.assertEqual(summary["remainder"], 0)
        self.assertEqual(summary["delivery"]["address"], "")
        self.assertEqual(summary["delivery"]["mode"], "personal")
        stale = summary["hash"]
        bumped = [{**row, "paid": row["paid"] + (1 if row["key"] == "p01" else 0)} for row in summary["allocations"]]
        changed = self.client.put(f"/client-api/{token}/summary", json={
            "allocations": bumped,
            "paid_total": 21,
            "delivery": {"mode": "shipping", "carrier": "Почта", "address": "ПВЗ 1", "recipient": "Ирина", "phone": "1"},
        }).json()
        self.client.post(f"/client-api/{token}/manage", json={"pin": pins["manage_pin"]})
        self.assertEqual(self.client.post(f"/client-api/{token}/approve", json={"hash": stale}).status_code, 409)
        self.assertEqual(self.client.post(f"/client-api/{token}/approve", json={"hash": changed["hash"]}).status_code, 200)
        self.assertIsNone(self.client.get(f"/api/orders/{self.order}/deal").json()["production"])
        self.assertEqual(self.client.post(f"/api/orders/{self.order}/production", json={"responsibility": False}).status_code, 200)
        bundle = self.client.get(f"/api/orders/{self.order}/export").json()
        self.assertEqual(len(bundle["files"]), 20)
        self.assertEqual(bundle["total"], 22)
        again = self.client.post(f"/api/orders/{self.order}/production", json={"responsibility": False})
        self.assertEqual(again.status_code, 200)
        self.assertEqual(self.client.get(f"/api/orders/{self.order}/export").json()["files"], bundle["files"])

    def test_twenty_six_students_fill_first_twenty(self):
        self.client.put("/api/profile", json={"teacher_gift": False, "delivery_modes": "both"})
        self.people(26)
        rows = [row for row in self.client.get(f"/api/orders/{self.order}/deal").json()["allocations"] if row["gift"] == 0]
        self.assertEqual([row["paid"] for row in rows], [1] * 20 + [0] * 6)

    def test_client_sees_only_the_published_layout(self):
        photo = test_server_v2.V2Tests.photo(self, person=None)
        outsider = test_server_v2.V2Tests.photo(self, person="other")
        document = {
            "revision": "rev-pub",
            "spread_size_mm": [200, 100],
            "cover_size_mm": [210, 100],
            "issues": [{"level": "error", "message": "внутреннее"}],
            "overrides": {"conflicts": [{"key": "secret"}]},
            "variants": [{"owner": "class", "name": "11А", "sequence": ["cover[class]", "shared"]}],
            "covers": {"class": {"key": "cover[class]", "section": "cover", "elements": [
                {"type": "photo", "box": [0, 0, 10, 10], "photo": photo, "crop": [0, 0, 10, 10]},
                {"type": "text", "box": [0, 0, 10, 4], "text": "Выпуск", "hidden": False},
                {"type": "text", "box": [0, 0, 1, 1], "text": "скрыть", "hidden": True},
            ]}},
            "shared_spreads": {"shared": {"key": "shared", "section": "students", "elements": []}},
            "variant_spreads": {},
        }
        token, _pins = self.link()
        blocked = self.client.get(f"/client-api/{token}/layout")
        self.assertEqual(blocked.status_code, 409)
        from album_factory import server as s
        with s.db() as con:
            con.execute("INSERT INTO order_layouts VALUES (?,?,?,?,?)", (
                self.order, "{}", json.dumps(document), "[]", s.now()))
        self.client.post(f"/api/orders/{self.order}/layout/publish")
        with s.db() as con:
            con.execute("UPDATE order_layouts SET document=? WHERE order_id=?", (
                json.dumps({"revision": "draft", "variants": []}), self.order))
        view = self.client.get(f"/client-api/{token}/layout").json()
        self.assertEqual(view["revision"], "rev-pub")
        self.assertEqual(view["variants"][0]["name"], "11А")
        self.assertEqual(len(view["variants"][0]["spreads"]), 2)
        texts = [item.get("text") for item in view["variants"][0]["spreads"][0]["elements"]]
        self.assertIn("Выпуск", texts)
        self.assertNotIn("скрыть", texts)
        self.assertNotIn("issues", view)
        self.assertNotIn("overrides", view)
        cover = view["variants"][0]["spreads"][0]["elements"][0]
        self.assertEqual(cover["width"], 10)
        self.assertEqual(self.client.get(f"/client-api/{token}/layout/photos/{photo}/thumb").status_code, 200)
        self.assertEqual(self.client.get(f"/client-api/{token}/layout/photos/{outsider}/thumb").status_code, 404)
        detail = self.client.get(f"/client-api/{token}").json()
        self.assertTrue(detail["layout_published"])

    def test_print_spec_is_not_a_printer_signoff(self):
        spec = self.client.get("/api/print-spec").json()
        self.assertFalse(spec["confirmed_by_printer"])


if __name__ == "__main__":
    unittest.main()
