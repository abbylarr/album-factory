"""Order-scoped client links and durable portrait selections for the local pilot."""
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import json
import secrets

from . import mvp, order_stages


DEFAULT_TEMPLATES = {
    'class': ('Здравствуйте! Фотографии для выпускного альбома {класс} готовы.\n\n'
              'Откройте ссылку: {ссылка}\nКод входа: {код_входа}\n\n'
              'Каждый выбирает свой портрет, пишет имя, фамилию и, если хочется, цитату. '
              'Пожалуйста, заполните анкету в ближайшие дни.'),
    'manager': ('Здравствуйте! Анкеты для альбома {класс} открыты.\n\n'
                'Ссылка для класса: {ссылка}\nКод входа (для всех): {код_входа}\n'
                'Код управления (только для вас): {код_управления}\n\n'
                'Код управления понадобится, чтобы согласовать макет и тираж. Не пересылайте его в общий чат.'),
}


class Template(BaseModel):
    body: str = Field(default='', max_length=2000)


class Selection(BaseModel):
    photo_id: str
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    quote: str = Field(default='', max_length=300)


class NameFix(BaseModel):
    person_id: str
    first_name: str = Field(min_length=1, max_length=50)
    last_name: str = Field(min_length=1, max_length=50)
    comment: str = Field(default='', max_length=1000)


class SpreadFix(BaseModel):
    variant: str | None = None
    index: int = Field(ge=0)
    comment: str = Field(min_length=1, max_length=1000)


class PhotosLink(BaseModel):
    url: str = Field(default='', max_length=500)


def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS client_links (
      order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
      token TEXT UNIQUE NOT NULL);
    CREATE TABLE IF NOT EXISTS client_selections (
      person_id TEXT PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
      photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
      first_name TEXT NOT NULL, last_name TEXT NOT NULL, quote TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS layout_corrections (
      id TEXT PRIMARY KEY, order_id TEXT NOT NULL, revision TEXT NOT NULL, kind TEXT NOT NULL,
      person_id TEXT, old_name TEXT NOT NULL DEFAULT '', new_name TEXT NOT NULL DEFAULT '',
      variant TEXT NOT NULL DEFAULT '', spread_key TEXT NOT NULL DEFAULT '', spread_label TEXT NOT NULL DEFAULT '',
      comment TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS client_extras (
      order_id TEXT PRIMARY KEY, photos_url TEXT NOT NULL DEFAULT '');
    ''')


def forget(con, order_id):
    con.execute('DELETE FROM layout_corrections WHERE order_id=?', (order_id,))
    con.execute('DELETE FROM client_extras WHERE order_id=?', (order_id,))


def open_corrections(con, order_id):
    """Requests the class sent for the currently published layout and the photographer has not closed."""
    return [dict(r) for r in con.execute('''SELECT c.id,c.kind,c.person_id,c.old_name,c.new_name,c.variant,c.spread_label,
        c.comment,c.created_at FROM layout_corrections c JOIN publications p ON p.order_id=c.order_id AND p.revision=c.revision
        WHERE c.order_id=? AND c.status='open' ORDER BY c.created_at,c.id''', (order_id,))]


def open_counts(con):
    return dict(con.execute('''SELECT c.order_id, COUNT(*) FROM layout_corrections c
        JOIN publications p ON p.order_id=c.order_id AND p.revision=c.revision
        WHERE c.status='open' GROUP BY c.order_id''').fetchall())


def client_stage(con, order):
    """What the class sees: selection → waiting for layout → approval → print → delivery → done."""
    stage = order['stage']
    published = con.execute('SELECT 1 FROM publications WHERE order_id=?', (order['id'],)).fetchone() is not None
    if stage in ('new', 'photos', 'forms'):
        return 'selection'
    if stage == 'layout':
        return 'updating' if published else 'layout'
    if stage == 'approval':
        approved = con.execute('''SELECT 1 FROM approvals a JOIN publications p ON p.order_id=a.order_id
            WHERE a.order_id=? AND a.approved_at>=p.published_at''', (order['id'],)).fetchone()
        return 'approved' if approved else 'approval'
    return stage


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

    def access(con, order_id, token):
        entry, manage = mvp.stored_pins(con, order_id)
        issued = con.execute('SELECT 1 FROM order_pins WHERE order_id=?', (order_id,)).fetchone() is not None
        return {'url': '/client/' + token if token else None, 'entry_pin': entry, 'manage_pin': manage,
                'pins_set': issued, 'pins_lost': issued and entry is None}

    @app.post('/api/orders/{order_id}/client-link')
    def link(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            con.execute('INSERT OR IGNORE INTO client_links VALUES (?,?)', (order_id, secrets.token_urlsafe(32)))
            token = con.execute('SELECT token FROM client_links WHERE order_id=?', (order_id,)).fetchone()[0]
            mvp.issue_pins(con, order_id)
            order_stages.advance(con, order_id, 'forms')
            return access(con, order_id, token)

    @app.get('/api/orders/{order_id}/client-link')
    def current_link(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            row = con.execute('SELECT token FROM client_links WHERE order_id=?', (order_id,)).fetchone()
            return access(con, order_id, row[0] if row else None)

    @app.post('/api/orders/{order_id}/client-codes/reset')
    def reset_codes(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            row = con.execute('SELECT token FROM client_links WHERE order_id=?', (order_id,)).fetchone()
            if row is None:
                raise HTTPException(409, 'Сначала отправьте анкеты классу')
            mvp.reset_pins(con, order_id)
            return access(con, order_id, row[0])

    @app.get('/api/message-templates')
    def templates():
        with s.db() as con:
            saved = dict(con.execute('SELECT kind, body FROM message_templates WHERE studio_id=?', (mvp._studio(),)).fetchall())
        return {kind: {'body': saved.get(kind, text), 'custom': kind in saved, 'default': text} for kind, text in DEFAULT_TEMPLATES.items()}

    @app.put('/api/message-templates/{kind}')
    def save_template(kind: str, payload: Template):
        if kind not in DEFAULT_TEMPLATES:
            raise HTTPException(404, 'Неизвестный шаблон')
        body = payload.body.strip()
        with s.db() as con:
            if body and body != DEFAULT_TEMPLATES[kind]:
                con.execute('INSERT OR REPLACE INTO message_templates VALUES (?,?,?)', (mvp._studio(), kind, body))
            else:
                con.execute('DELETE FROM message_templates WHERE studio_id=? AND kind=?', (mvp._studio(), kind))
        return {'body': body or DEFAULT_TEMPLATES[kind], 'custom': bool(body) and body != DEFAULT_TEMPLATES[kind]}

    @app.get('/client/{token}')
    def page(token: str):
        return FileResponse(s.ROOT / 'web/client.html')

    @app.get('/client-api/{token}')
    def detail(token: str, request: Request):
        with s.db() as con:
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'entry')
            people = [dict(r) for r in con.execute('''SELECT p.id,p.name,s.photo_id,s.first_name,s.last_name,s.quote,
                l.person_id IS NOT NULL AS photo_locked, IFNULL(l.submitted,0) AS submitted
                FROM persons p LEFT JOIN client_selections s ON s.person_id=p.id
                AND EXISTS (SELECT 1 FROM photos f WHERE f.id=s.photo_id AND f.person_id=p.id AND f.status='ready')
                LEFT JOIN selection_state l ON l.person_id=p.id
                WHERE p.order_id=? ORDER BY p.created_at,p.id''', (order['id'],))]
            for person in people:
                person['photo_locked'] = bool(person['photo_locked'])
                person['submitted'] = bool(person['submitted'])
            photos = [dict(r) for r in con.execute("SELECT id,person_id FROM photos WHERE order_id=? AND person_id IS NOT NULL AND status='ready' ORDER BY created_at,id", (order['id'],))]
            published = con.execute("SELECT 1 FROM publications WHERE order_id=?", (order['id'],)).fetchone()
            extras = con.execute('SELECT photos_url FROM client_extras WHERE order_id=?', (order['id'],)).fetchone()
            delivery = con.execute('SELECT mode,carrier,address FROM deliveries WHERE order_id=?', (order['id'],)).fetchone()
            return {'school': order['school'], 'class_name': order['class_name'], 'persons': people, 'photos': photos,
                    'completed': sum(bool(p['photo_id']) for p in people), 'quote_limit': mvp.quote_limit(con, order['id']),
                    'layout_published': published is not None, 'stage': client_stage(con, order),
                    'manager': mvp.has_level(con, request, order['id'], 'manage'),
                    'photos_url': extras['photos_url'] if extras else '',
                    'delivery': dict(delivery) if delivery and delivery['mode'] else None,
                    'corrections': open_corrections(con, order['id'])}

    @app.put('/client-api/{token}/persons/{person_id}')
    def select(token: str, person_id: str, payload: Selection, request: Request):
        first, last = payload.first_name.strip(), payload.last_name.strip()
        if not first or not last:
            raise HTTPException(422, 'Укажите имя и фамилию')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'entry')
            quote = payload.quote.strip()
            limit = mvp.quote_limit(con, order['id'])
            if len(quote) > limit:
                raise HTTPException(422, f'Цитата не длиннее {limit} символов')
            state = con.execute('SELECT photo_id, submitted FROM selection_state WHERE person_id=?', (person_id,)).fetchone()
            if state and state['submitted']:
                raise HTTPException(409, 'Анкета уже отправлена')
            if state and state['photo_id'] != payload.photo_id:
                raise HTTPException(409, 'Портрет уже выбран. Изменить его может фотограф.')
            photo = con.execute("SELECT id FROM photos WHERE id=? AND order_id=? AND person_id=? AND status='ready'", (payload.photo_id, order['id'], person_id)).fetchone()
            if photo is None:
                raise HTTPException(409, 'Фотография больше не доступна для этой персоны. Обновите страницу.')
            con.execute('INSERT OR REPLACE INTO client_selections VALUES (?,?,?,?,?)', (person_id, payload.photo_id, first, last, quote))
            con.execute('UPDATE persons SET name=? WHERE id=?', (first + ' ' + last, person_id))
            con.execute('''INSERT INTO selection_state (person_id, photo_id, submitted) VALUES (?,?,0)
                ON CONFLICT(person_id) DO UPDATE SET photo_id=excluded.photo_id WHERE submitted=0''', (person_id, payload.photo_id))
        return {'ok': True}

    @app.get('/client-api/{token}/photos/{photo_id}/{variant}')
    def photo(token: str, photo_id: str, variant: str, request: Request):
        with s.db() as con:
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'entry')
            if not con.execute("SELECT id FROM photos WHERE id=? AND order_id=? AND person_id IS NOT NULL AND status='ready'", (photo_id, order['id'])).fetchone():
                raise HTTPException(404, 'Фотография не найдена')
        return s.media(photo_id, variant)

    def published_view(con, order_id):
        row = con.execute('SELECT revision, document FROM publications WHERE order_id=?', (order_id,)).fetchone()
        if row is None:
            raise HTTPException(409, 'Макет ещё не опубликован')
        return row['revision'], mvp.client_layout_view(json.loads(row['document']))

    def require_review(con, order):
        if client_stage(con, order) != 'approval':
            raise HTTPException(409, 'Сейчас макет нельзя изменить: он не на согласовании')

    @app.post('/client-api/{token}/corrections/name', status_code=201)
    def fix_name(token: str, payload: NameFix, request: Request):
        first, last = payload.first_name.strip(), payload.last_name.strip()
        if not first or not last:
            raise HTTPException(422, 'Укажите имя и фамилию')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'manage')
            require_review(con, order)
            revision, _view = published_view(con, order['id'])
            person = con.execute('''SELECT p.id, COALESCE(NULLIF(trim(c.first_name||' '||c.last_name),''), p.name) AS name
                FROM persons p LEFT JOIN client_selections c ON c.person_id=p.id WHERE p.id=? AND p.order_id=?''',
                (payload.person_id, order['id'])).fetchone()
            if person is None:
                raise HTTPException(404, 'Участник не найден')
            new_name = first + ' ' + last
            if new_name == person['name'] and not payload.comment.strip():
                raise HTTPException(422, 'Имя не изменилось')
            # The corrected name is kept so the next layout build already uses it.
            con.execute('UPDATE client_selections SET first_name=?, last_name=? WHERE person_id=?', (first, last, person['id']))
            con.execute('UPDATE persons SET name=? WHERE id=?', (new_name, person['id']))
            fix_id = s.uid()
            con.execute('''INSERT INTO layout_corrections (id,order_id,revision,kind,person_id,old_name,new_name,comment,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''', (fix_id, order['id'], revision, 'name', person['id'], person['name'] or '',
                new_name, payload.comment.strip(), s.now()))
        return {'id': fix_id}

    @app.post('/client-api/{token}/corrections/spread', status_code=201)
    def fix_spread(token: str, payload: SpreadFix, request: Request):
        comment = payload.comment.strip()
        if not comment:
            raise HTTPException(422, 'Опишите, что нужно исправить')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'manage')
            require_review(con, order)
            revision, view = published_view(con, order['id'])
            variant = next((v for v in view['variants'] if v['owner'] == payload.variant), None)
            if variant is None or payload.index >= len(variant['spreads']):
                raise HTTPException(404, 'Разворот не найден')
            spread = variant['spreads'][payload.index]
            fix_id = s.uid()
            con.execute('''INSERT INTO layout_corrections (id,order_id,revision,kind,variant,spread_key,spread_label,comment,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)''', (fix_id, order['id'], revision, 'spread', variant['name'], str(spread.get('key') or ''),
                f"Разворот {payload.index + 1} из {len(variant['spreads'])}", comment, s.now()))
        return {'id': fix_id}

    @app.delete('/client-api/{token}/corrections/{fix_id}')
    def withdraw(token: str, fix_id: str, request: Request):
        with s.db() as con:
            order = order_for(con, token)
            mvp.require_level(con, request, order['id'], 'manage')
            gone = con.execute("DELETE FROM layout_corrections WHERE id=? AND order_id=? AND status='open'", (fix_id, order['id'])).rowcount
            if not gone:
                raise HTTPException(404, 'Правка не найдена')
        return {'ok': True}

    @app.post('/client-api/{token}/manage/logout')
    def leave_manage(token: str, request: Request):
        from fastapi.responses import JSONResponse
        cookie = request.cookies.get('album_manage')
        with s.db() as con:
            order = order_for(con, token)
            if cookie:
                con.execute('DELETE FROM class_sessions WHERE token_hash=? AND order_id=?', (mvp.token_hash(cookie), order['id']))
        response = JSONResponse({'ok': True})
        response.delete_cookie('album_manage', path='/')
        return response

    @app.get('/api/orders/{order_id}/corrections')
    def corrections(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            return open_corrections(con, order_id)

    @app.post('/api/orders/{order_id}/corrections/{fix_id}/resolve')
    def resolve(order_id: str, fix_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            if not con.execute("UPDATE layout_corrections SET status='resolved' WHERE id=? AND order_id=?", (fix_id, order_id)).rowcount:
                raise HTTPException(404, 'Правка не найдена')
        return {'ok': True}

    @app.put('/api/orders/{order_id}/photos-link')
    def photos_link(order_id: str, payload: PhotosLink):
        url = payload.url.strip()
        if url and not url.startswith(('https://', 'http://')):
            raise HTTPException(422, 'Ссылка должна начинаться с https://')
        with s.db() as con:
            s.require_order(con, order_id)
            con.execute('INSERT INTO client_extras VALUES (?,?) ON CONFLICT(order_id) DO UPDATE SET photos_url=excluded.photos_url', (order_id, url))
        return {'url': url}

    @app.get('/api/orders/{order_id}/photos-link')
    def current_photos_link(order_id: str):
        with s.db() as con:
            s.require_order(con, order_id)
            row = con.execute('SELECT photos_url FROM client_extras WHERE order_id=?', (order_id,)).fetchone()
        return {'url': row['photos_url'] if row else ''}
