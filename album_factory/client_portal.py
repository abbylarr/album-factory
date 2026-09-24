"""Order-scoped client links and durable portrait selections for the local pilot."""
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import secrets


class Selection(BaseModel):
    photo_id: str
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    quote: str = Field(default='', max_length=300)


def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS client_links (
      order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
      token TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS client_selections (
      person_id TEXT PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
      photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
      first_name TEXT NOT NULL, last_name TEXT NOT NULL, quote TEXT NOT NULL);
    ''')


def progress_by_order(con, order_id=None):
    """Count only saved, still-valid client selections; no token exposure."""
    where = 'WHERE o.id=?' if order_id is not None else ''
    rows = con.execute(f"""SELECT o.id, l.order_id IS NOT NULL AS enabled,
        COUNT(p.id) AS total,
        SUM(CASE WHEN f.id IS NOT NULL AND trim(s.first_name)!='' AND trim(s.last_name)!='' THEN 1 ELSE 0 END) AS completed
        FROM orders o LEFT JOIN client_links l ON l.order_id=o.id
        LEFT JOIN persons p ON p.order_id=o.id
        LEFT JOIN client_selections s ON s.person_id=p.id
        LEFT JOIN photos f ON f.id=s.photo_id AND f.person_id=p.id AND f.order_id=o.id AND f.status='ready'
        {where} GROUP BY o.id,l.order_id""", (order_id,) if order_id is not None else ()).fetchall()
    result = {}
    for row in rows:
        total, completed = row['total'], row['completed'] or 0
        status = 'not_opened' if not row['enabled'] else 'complete' if total and completed==total else 'in_progress' if completed else 'waiting'
        labels = dict(not_opened='Кабинет ещё не открыт', waiting='Ожидаем заполнение',
                      in_progress='Клиенты заполняют', complete='Все участники заполнили')
        result[row['id']] = dict(enabled=bool(row['enabled']), status=status, label=labels[status],
                                total=total, completed=completed, remaining=total-completed,
                                percent=round(100*completed/total) if total else 0)
    return result


def install(app, s):
    def order_for(con, token):
        row = con.execute('SELECT o.* FROM orders o JOIN client_links l ON l.order_id=o.id WHERE l.token=?', (token,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Ссылка на заказ не найдена')
        return row

    @app.post('/api/orders/{order_id}/client-link')
    def link(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            con.execute('INSERT OR IGNORE INTO client_links VALUES (?,?)', (order_id, secrets.token_urlsafe(32)))
            token = con.execute('SELECT token FROM client_links WHERE order_id=?', (order_id,)).fetchone()[0]
        return {'url': '/client/' + token}

    @app.get('/client/{token}')
    def page(token: str):
        return FileResponse(s.ROOT / 'web/client.html')

    @app.get('/client-api/{token}')
    def detail(token: str):
        with s.db() as con:
            order = order_for(con, token)
            people = [dict(r) for r in con.execute('''SELECT p.id,p.name,s.photo_id,s.first_name,s.last_name,s.quote
                FROM persons p LEFT JOIN client_selections s ON s.person_id=p.id
                AND EXISTS (SELECT 1 FROM photos f WHERE f.id=s.photo_id AND f.person_id=p.id AND f.status='ready')
                WHERE p.order_id=? ORDER BY p.created_at,p.id''', (order['id'],))]
            photos = [dict(r) for r in con.execute("SELECT id,person_id FROM photos WHERE order_id=? AND person_id IS NOT NULL AND status='ready' ORDER BY created_at,id", (order['id'],))]
            return {'school': order['school'], 'class_name': order['class_name'], 'persons': people, 'photos': photos,
                    'completed': sum(bool(p['photo_id']) for p in people), 'stage': 'selection'}

    @app.put('/client-api/{token}/persons/{person_id}')
    def select(token: str, person_id: str, payload: Selection):
        first, last = payload.first_name.strip(), payload.last_name.strip()
        if not first or not last:
            raise HTTPException(422, 'Укажите имя и фамилию')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            order = order_for(con, token)
            photo = con.execute("SELECT id FROM photos WHERE id=? AND order_id=? AND person_id=? AND status='ready'", (payload.photo_id, order['id'], person_id)).fetchone()
            if photo is None:
                raise HTTPException(409, 'Фотография больше не доступна для этой персоны. Обновите страницу.')
            con.execute('INSERT OR REPLACE INTO client_selections VALUES (?,?,?,?,?)', (person_id, payload.photo_id, first, last, payload.quote.strip()))
            con.execute('UPDATE persons SET name=? WHERE id=?', (first + ' ' + last, person_id))
        return {'ok': True}

    @app.get('/client-api/{token}/photos/{photo_id}/{variant}')
    def photo(token: str, photo_id: str, variant: str):
        with s.db() as con:
            order = order_for(con, token)
            if not con.execute("SELECT id FROM photos WHERE id=? AND order_id=? AND person_id IS NOT NULL AND status='ready'", (photo_id, order['id'])).fetchone():
                raise HTTPException(404, 'Фотография не найдена')
        return s.media(photo_id, variant)
