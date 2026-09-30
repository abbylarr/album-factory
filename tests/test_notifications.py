"""Notifications: the class finishing forms, sending corrections, and background processing reach the photographer once."""
import unittest
import test_client_portal
import test_server_v2
from album_factory import server as s, notifications


class NotificationTests(unittest.TestCase):
    setUp = test_server_v2.V2Tests.setUp
    photo = test_server_v2.V2Tests.photo
    publish = test_client_portal.LayoutCorrectionTests.publish

    def feed(self):
        return self.client.get('/api/notifications').json()

    def kinds(self):
        return [(n['kind'], n['count'], n['read']) for n in self.feed()['items']]

    def test_forms_complete_once_then_corrections_join_until_read(self):
        a, b = self.photo(person='a'), self.photo(person='b')
        data = self.client.post(f'/api/orders/{self.order}/client-link').json()
        base = '/client-api/' + data['url'].rsplit('/', 1)[1]
        self.client.post(base + '/enter', json={'pin': data['entry_pin']})
        self.client.put(base + '/persons/a', json=dict(photo_id=a, first_name='Анна', last_name='Иванова'))
        self.assertEqual(self.feed(), {'items': [], 'unread': 0}, 'one form of two is not news')
        self.client.put(base + '/persons/b', json=dict(photo_id=b, first_name='Борис', last_name='Иванов'))
        self.client.put(base + '/persons/b', json=dict(photo_id=b, first_name='Борис', last_name='Иванов', quote='Ещё'))
        feed = self.feed()
        self.assertEqual((self.kinds(), feed['unread']), ([('forms_complete', 1, False)], 1))
        self.assertEqual((feed['items'][0]['school'], feed['items'][0]['class_name']), ('Тест', '9Б'))

        self.client.post(base + '/manage', json={'pin': data['manage_pin']})
        self.publish('rev-1')
        first = self.client.post(base + '/corrections/spread', json=dict(variant='class', index=0, comment='Фото')).json()['id']
        self.client.post(base + '/corrections/spread', json=dict(variant='class', index=1, comment='Текст'))
        self.assertEqual(self.kinds()[0], ('corrections', 2, False))
        self.client.delete(base + '/corrections/' + first)
        self.assertEqual(self.kinds()[0], ('corrections', 1, False))

        self.assertEqual(self.client.post('/api/notifications/read').status_code, 200)
        self.assertEqual(self.feed()['unread'], 0)
        self.client.post(base + '/corrections/spread', json=dict(variant='class', index=0, comment='Снова'))
        self.assertEqual(self.kinds()[0], ('corrections', 1, False), 'after reading, a new correction is a new notification')
        one = self.feed()['items'][0]['id']
        self.assertEqual(self.client.post(f'/api/notifications/{one}/read').status_code, 200)
        self.assertEqual(self.client.post('/api/notifications/missing/read').status_code, 404)
        self.assertEqual(self.feed()['unread'], 0)

    def test_processing_done_and_order_deletion(self):
        self.photo(status='pending')
        with s.db() as con:
            notifications.photos_check(con, self.order)
        self.assertEqual(self.feed()['items'], [], 'still processing')
        with s.db() as con:
            con.execute("UPDATE photos SET status='ready', uncertain=1 WHERE order_id=?", (self.order,))
            notifications.photos_check(con, self.order)
            notifications.emit(con, self.order, 'approved')
        items = self.feed()['items']
        self.assertEqual(sorted(n['kind'] for n in items), ['approved', 'photos_ready'])
        self.assertEqual(next(n for n in items if n['kind'] == 'photos_ready')['review_count'], 1)
        self.client.delete(f'/api/orders/{self.order}')
        self.assertEqual(self.feed(), {'items': [], 'unread': 0})


if __name__ == '__main__':
    unittest.main()
