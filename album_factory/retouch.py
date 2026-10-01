"""Durable retouch workflow; a retouched file replaces the photo's full-size JPEG, its identity never changes."""
from pathlib import Path
import asyncio
import json
import re
import tempfile
import zipfile

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask
from PIL import Image


def init(con):
    con.executescript('''
    CREATE TABLE IF NOT EXISTS portrait_choice_sources (
      person_id TEXT PRIMARY KEY REFERENCES persons(id) ON DELETE CASCADE,
      photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, source TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS photo_retouch (
      photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
      version TEXT NOT NULL, filename TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS retouch_settings (
      order_id TEXT PRIMARY KEY REFERENCES orders(id) ON DELETE CASCADE,
      mode TEXT NOT NULL DEFAULT 'asis');
    ''')


def chosen(con, order_id, shoot_id=None):
    return [dict(r) for r in con.execute('''SELECT f.*, p.name, r.version AS retouch_version
        FROM client_selections c JOIN persons p ON p.id=c.person_id
        JOIN photos f ON f.id=c.photo_id AND f.person_id=p.id AND f.order_id=p.order_id
        LEFT JOIN shoots s ON s.id=f.shoot_id LEFT JOIN photo_retouch r ON r.photo_id=f.id
        WHERE p.order_id=? AND f.status='ready' AND COALESCE(s.kind,'portrait')='portrait'
        AND (? IS NULL OR f.shoot_id=?) ORDER BY p.created_at,p.id''', (order_id, shoot_id, shoot_id))]


def progress(con, order_id):
    photos = chosen(con, order_id)
    mode = con.execute('SELECT mode FROM retouch_settings WHERE order_id=?', (order_id,)).fetchone()
    return {'mode': mode[0] if mode else 'asis', 'total': len(photos),
            'done': sum(bool(p['retouch_version']) for p in photos),
            'remaining': [{'id': p['id'], 'name': p['name'], 'filename': p['filename']} for p in photos if not p['retouch_version']]}


def basename(name):
    name = Path(name.replace('\\', '/')).stem.split(' — ')[-1]
    return re.sub(r'(-Edit(-\d+)?|-\d+| copy( \d+)?| \(\d+\))+$', '', name, flags=re.I).strip().casefold()


def match(con, order_id, filename, shoot_id=None):
    photos = chosen(con, order_id, shoot_id)
    stem = Path(filename.replace('\\', '/')).stem.split(' — ')[-1].casefold()
    # An exact camera filename wins before stripping export suffixes.
    matches = [p for p in photos if Path(p['filename']).stem.casefold() == stem]
    if not matches:
        matches = [p for p in photos if Path(p['filename']).stem.casefold() == basename(filename)]
    if len(matches) > 1:
        return None, 'ambiguous'
    if matches:
        return matches[0], None
    other = con.execute('SELECT filename FROM photos WHERE order_id=? AND (? IS NULL OR shoot_id=?)',
                        (order_id, shoot_id, shoot_id))
    return None, 'not_chosen' if any(Path(r[0]).stem.casefold() in {stem, basename(filename)} for r in other) else 'unknown'


def update_layout(con, s, order_id, photo_id, version, size):
    row = con.execute('SELECT snapshot,document FROM order_layouts WHERE order_id=?', (order_id,)).fetchone()
    if not row:
        return
    snapshot, document = json.loads(row['snapshot']), json.loads(row['document'])
    old = dict(snapshot['photos'].get(photo_id, {}))
    if photo_id in snapshot['photos']:
        snapshot['photos'][photo_id].update(width=size[0], height=size[1], version=version)
    # Preserve all layout edits and crops while invalidating previews and reviews.
    def visit(value):
        if isinstance(value, dict):
            if value.get('photo') == photo_id or value.get('photo_id') == photo_id:
                value['asset_version'] = version
                width, height = value.get('width') or old.get('width'), value.get('height') or old.get('height')
                if width and height:
                    crop = value.get('crop')
                    if crop and len(crop) == 4:
                        value['crop'] = [crop[0]*size[0]/width, crop[1]*size[1]/height,
                                         crop[2]*size[0]/width, crop[3]*size[1]/height]
                    value['width'], value['height'] = size
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(document)
    document['revision'] = s.uid()
    con.execute('UPDATE order_layouts SET snapshot=?,document=?,generated_at=? WHERE order_id=?',
                (json.dumps(snapshot), json.dumps(document), s.now(), order_id))
    from . import order_stages
    order_stages.reopen_layout(con, order_id)


class Mode(BaseModel):
    mode: str


def install(app, s):
    @app.put('/api/orders/{order_id}/retouch')
    def set_mode(order_id: str, payload: Mode):
        if payload.mode not in {'asis', 'retouch'}:
            raise HTTPException(422, 'Выберите, будете ли ретушировать портреты')
        with s.db() as con:
            con.execute('BEGIN IMMEDIATE')
            from .production import require_editable
            require_editable(con, s.require_order(con, order_id))
            con.execute('INSERT INTO retouch_settings VALUES (?,?) ON CONFLICT(order_id) DO UPDATE SET mode=excluded.mode', (order_id, payload.mode))
        return {'ok': True}

    @app.get('/api/orders/{order_id}/chosen/archive')
    def archive(order_id: str, shoot_id: str | None = None, todo: bool = False, names: bool = True):
        temp_path = None
        try:
            with s.db() as con:
                s.require_order(con, order_id)
                photos = [p for p in chosen(con, order_id, shoot_id) if not todo or not p['retouch_version']]
                if not photos:
                    raise HTTPException(409, 'Нет выбранных фотографий для выгрузки')
                # A choice changed after the other frames shrank has only a thumbnail left.
                missing = [p for p in photos if not (s.DATA / 'photos' / (p['id']+'.jpg')).is_file()]
                photos = [p for p in photos if p not in missing]
                if not photos:
                    raise HTTPException(409, 'Полных файлов нет — возьмите кадры из своего архива')
                with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                    temp_path = Path(tmp.name)
                used = set()
                base = lambda p: Path(p['filename'].replace('\\', '/')).name
                with zipfile.ZipFile(temp_path, 'w', compression=zipfile.ZIP_STORED) as z:
                    for p in photos:
                        filename = base(p)
                        label = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', p['name']).strip(' .')
                        entry = f'{label} — {filename}' if names and label else filename
                        if entry in used:
                            entry = f"{p['id'][:8]}/{entry}"
                        used.add(entry)
                        z.write(s.DATA / 'photos' / (p['id']+'.jpg'), entry)
                    if missing:
                        z.writestr('Нет в архиве.txt', 'Этих кадров нет в полном размере, возьмите их из своего архива:\n'
                                   + ''.join(f"{p['name']} — {base(p)}\n" for p in missing))
            return FileResponse(temp_path, media_type='application/zip', filename='chosen-portraits.zip',
                                background=BackgroundTask(temp_path.unlink, missing_ok=True))
        except Exception:
            if temp_path:
                temp_path.unlink(missing_ok=True)
            raise

    @app.post('/api/orders/{order_id}/retouched')
    async def upload(order_id: str, request: Request, filename: str, shoot_id: str | None = None):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > s.MAX_BYTES:
                raise HTTPException(413, 'Файл больше 30 МБ')
        # Decode into temporary derivatives before touching any existing photo.
        temp_id = s.uid()
        await asyncio.get_running_loop().run_in_executor(s.image_executor, s.prepare_photo_files, bytes(body), temp_id)
        suffixes = ['.jpg', '.thumb.jpg']
        backups = {}
        try:
            with s.upload_lock, s.db() as con:
                con.execute('BEGIN IMMEDIATE')
                from .production import require_editable
                require_editable(con, s.require_order(con, order_id))
                photo, reason = match(con, order_id, filename, shoot_id)
                if reason:
                    return {'status': reason, 'filename': filename}
                photo_id = photo['id']
                with Image.open(s.DATA / 'photos' / (temp_id+'.jpg')) as image:
                    size = image.size
                version = s.uid()
                for suffix in suffixes:
                    target = s.DATA / 'photos' / (photo_id+suffix)
                    backups[target] = target.read_bytes() if target.exists() else None
                    (s.DATA / 'photos' / (temp_id+suffix)).replace(target)
                con.execute('INSERT INTO photo_retouch VALUES (?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET version=excluded.version,filename=excluded.filename,updated_at=excluded.updated_at',
                            (photo_id, version, Path(filename).name, s.now()))
                update_layout(con, s, order_id, photo_id, version, size)
            return {'status': 'replaced', 'filename': filename, 'photo_id': photo_id}
        except Exception:
            for path, data in backups.items():
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_bytes(data)
            raise
        finally:
            for suffix in suffixes:
                (s.DATA / 'photos' / (temp_id+suffix)).unlink(missing_ok=True)
