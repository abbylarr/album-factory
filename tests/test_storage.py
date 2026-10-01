"""One full-size JPEG per photo, unchosen portraits shrink to thumbnails; retention dates are calendar days."""
import json
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from album_factory import server as s, shoots
from album_factory.storage import retention_deadline, warn_days
import test_client_portal
import test_server_v2


def jpeg(size=(60, 40), orientation=None, fmt='JPEG'):
    out = BytesIO()
    image = Image.new('RGB', size, 'red')
    image.paste((0, 0, 255), (0, 0, size[0] // 2, size[1]))
    exif = Image.Exif()
    exif[0x0132] = '2026:05:20 10:30:00'
    if orientation:
        exif[0x0112] = orientation
    image.save(out, fmt, **({'exif': exif.tobytes()} if fmt == 'JPEG' else {}))
    return out.getvalue()


class UploadFilesTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp

    def files(self, photo_id):
        return sorted(p.name for p in (s.DATA / 'photos').iterdir() if p.name.startswith(photo_id))

    def test_upright_jpeg_is_stored_byte_for_byte_next_to_thumb(self):
        body = jpeg()
        s.prepare_photo_files(body, 'up')
        self.assertEqual(self.files('up'), ['up.jpg', 'up.thumb.jpg'])
        self.assertEqual((s.DATA / 'photos' / 'up.jpg').read_bytes(), body)

    def test_rotated_jpeg_is_stored_once_upright_with_camera_data(self):
        s.prepare_photo_files(jpeg(orientation=6), 'rot')
        self.assertEqual(self.files('rot'), ['rot.jpg', 'rot.thumb.jpg'])
        with Image.open(s.DATA / 'photos' / 'rot.jpg') as image:
            self.assertEqual(image.size, (40, 60))
            exif = image.getexif()
            self.assertEqual(exif.get(0x0112), 1)
            self.assertEqual(exif.get(0x0132), '2026:05:20 10:30:00')
        with Image.open(s.DATA / 'photos' / 'rot.thumb.jpg') as thumb:
            self.assertGreater(thumb.height, thumb.width)

    def test_png_becomes_the_only_jpeg(self):
        s.prepare_photo_files(jpeg(fmt='PNG'), 'png')
        self.assertEqual(self.files('png'), ['png.jpg', 'png.thumb.jpg'])
        with Image.open(s.DATA / 'photos' / 'png.jpg') as image:
            self.assertEqual(image.format, 'JPEG')


class ShrinkTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def frames(self, n=3, person='person'):
        ids = [self.photo(person=person) for _ in range(n)]
        with s.db() as con:
            shoot = shoots.default_portrait(con, self.order)
            for i, photo in enumerate(ids):
                con.execute('UPDATE photos SET shoot_id=?,filename=? WHERE id=?', (shoot, f'DSC{i:05}.jpg', photo))
        return ids

    def full(self, photo):
        return (s.DATA / 'photos' / (photo + '.jpg')).is_file()

    def thumb(self, photo):
        return (s.DATA / 'photos' / (photo + '.thumb.jpg')).is_file()

    def test_photographer_choice_keeps_only_the_chosen_full_file(self):
        first, second, third = self.frames()
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/persons/person/choice', json={'photo_id': second}).status_code, 200)
        self.assertEqual([self.full(p) for p in (first, second, third)], [False, True, False])
        self.assertTrue(all(self.thumb(p) for p in (first, second, third)))

    def test_client_choice_shrinks_the_other_frames(self):
        first, second = self.frames(2)
        base = test_client_portal.ClientPortalTests.link(self)
        response = self.client.put(base + '/persons/person', json={'photo_id': first, 'first_name': 'Анна', 'last_name': 'Иванова', 'quote': ''})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.full(first))
        self.assertFalse(self.full(second))

    def test_frames_placed_in_the_published_layout_stay_full(self):
        first, second = self.frames(2)
        document = {'revision': 'r', 'issues': [], 'covers': {}, 'variants': [],
                    'shared_spreads': {'one': {'elements': [{'type': 'photo', 'photo': first}]}}}
        with s.db() as con:
            con.execute('INSERT INTO publications VALUES (?,?,?,?)', (self.order, 'r', json.dumps(document), s.now()))
        self.assertEqual(self.client.put(f'/api/orders/{self.order}/persons/person/choice', json={'photo_id': second}).status_code, 200)
        self.assertTrue(self.full(first))

    def test_archive_lists_chosen_frames_without_full_file(self):
        first, second = self.frames(2)
        other = self.frames(1, person='other')[0]
        self.client.put(f'/api/orders/{self.order}/persons/person/choice', json={'photo_id': first})
        self.client.put(f'/api/orders/{self.order}/persons/other/choice', json={'photo_id': other})
        with s.db() as con:  # the choice moved to a frame that had already shrunk
            con.execute('UPDATE client_selections SET photo_id=? WHERE person_id=?', (second, 'person'))
        response = self.client.get(f'/api/orders/{self.order}/chosen/archive?names=false')
        self.assertEqual(response.status_code, 200, response.text)
        with zipfile.ZipFile(BytesIO(response.content)) as z:
            self.assertEqual(sorted(z.namelist()), ['DSC00000.jpg', 'Нет в архиве.txt'])
            self.assertIn('DSC00001.jpg', z.read('Нет в архиве.txt').decode())


class QuoteTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo

    def test_photographer_edits_quote_without_touching_the_name(self):
        photo = self.photo()
        url = f'/api/orders/{self.order}/persons/person'
        self.assertEqual(self.client.patch(url, json={'quote': 'Без выбора'}).status_code, 409)
        self.client.put(url + '/choice', json={'photo_id': photo})
        self.assertEqual(self.client.patch(url, json={'quote': '  Вперёд!  '}).status_code, 200)
        person = self.client.get(f'/api/orders/{self.order}').json()['persons'][0]
        self.assertEqual((person['quote'], person['name']), ('Вперёд!', 'Имя'))
        self.assertEqual(self.client.patch(url, json={'quote': 'x' * 301}).status_code, 422)


class RetentionTests(unittest.TestCase):
    def test_retention_warns_inside_fourteen_days(self):
        created = datetime(2026, 1, 1, 15, 0, tzinfo=timezone.utc)
        self.assertEqual(retention_deadline(created.isoformat()), "2026-04-01")
        now = datetime.now(timezone.utc)
        soon = warn_days((now - timedelta(days=80)).isoformat())
        later = warn_days((now - timedelta(days=70)).isoformat())
        self.assertTrue(soon["warn"])
        self.assertFalse(later["warn"])
        self.assertEqual(soon["delete_on"], retention_deadline((now - timedelta(days=80)).isoformat()))


if __name__ == "__main__":
    unittest.main()
