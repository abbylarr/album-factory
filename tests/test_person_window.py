"""The photographer's person window: re-pick a portrait for a student and correct the name."""
import unittest
from album_factory import server as s
import test_audit_fixes
import test_server_v2


class PersonWindowTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo
    link = test_audit_fixes.AuditFixTests.link

    def person(self):
        return next(p for p in self.client.get(f'/api/orders/{self.order}').json()['persons'] if p['id'] == 'person')

    def choose(self, photo):
        return self.client.put(f'/api/orders/{self.order}/persons/person/choice', json={'photo_id': photo})

    def test_photographer_picks_for_a_student_who_did_not(self):
        a = self.photo()
        self.assertEqual(self.choose(a).status_code, 200)
        self.assertEqual(self.person()['selected_photo_id'], a)

    def test_repick_keeps_student_name_and_quote(self):
        a, b = self.photo(), self.photo()
        base, _ = self.link()
        self.assertEqual(self.client.put(base+'/persons/person', json={'photo_id': a, 'first_name': 'Анна', 'last_name': 'Иванова', 'quote': 'Спасибо!'}).status_code, 200)
        self.assertEqual(self.client.post(base+'/persons/person/submit').status_code, 200)
        self.assertEqual(self.choose(b).status_code, 200)
        person = self.person()
        self.assertEqual((person['selected_photo_id'], person['quote']), (b, 'Спасибо!'))
        with s.db() as con:
            row = con.execute('SELECT first_name,last_name FROM client_selections WHERE person_id=?', ('person',)).fetchone()
            self.assertEqual(tuple(row), ('Анна', 'Иванова'))
            self.assertEqual(con.execute('SELECT photo_id FROM selection_state WHERE person_id=?', ('person',)).fetchone()[0], b)

    def test_frame_of_another_person_is_refused(self):
        a = self.photo()
        with s.db() as con:
            con.execute("INSERT INTO persons VALUES ('other',?,'',?)", (self.order, s.now()))
            con.execute("UPDATE photos SET person_id='other' WHERE id=?", (a,))
        self.assertEqual(self.choose(a).status_code, 409)

    def test_split_name_corrects_the_form_too(self):
        a = self.photo()
        base, _ = self.link()
        self.client.put(base+'/persons/person', json={'photo_id': a, 'first_name': 'Анна', 'last_name': 'Иванова'})
        self.assertEqual(self.client.patch(f'/api/orders/{self.order}/persons/person', json={'first_name': 'Анна', 'last_name': 'Петрова'}).status_code, 200)
        self.assertEqual(self.person()['name'], 'Анна Петрова')
        with s.db() as con:
            self.assertEqual(con.execute('SELECT last_name FROM client_selections WHERE person_id=?', ('person',)).fetchone()[0], 'Петрова')


if __name__ == '__main__':
    unittest.main()
