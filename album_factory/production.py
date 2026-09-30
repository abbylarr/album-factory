"""Frozen publication sources and real, atomic production exports."""
import base64
from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from fastapi import HTTPException
from PIL import Image

from .layout_engine import LayoutError, ReportLabMeasurer
from .layout_render import render_variant, export_print_files

VERSION = 1


def init(con):
    con.execute('CREATE TABLE IF NOT EXISTS publication_sources (order_id TEXT PRIMARY KEY, revision TEXT NOT NULL, source TEXT NOT NULL)')
    con.execute('CREATE TABLE IF NOT EXISTS production_layouts (order_id TEXT PRIMARY KEY, source TEXT NOT NULL)')


def locked(con, order):
    from .order_stages import STAGES
    return order['stage'] in STAGES[5:] or con.execute('SELECT 1 FROM authorizations WHERE order_id=?', (order['id'],)).fetchone() is not None


def require_editable(con, order):
    if locked(con, order):
        raise HTTPException(409, 'Заказ отправлен в печать. Макет зафиксирован и доступен только для просмотра')


def save_publication_source(con, server, order_id, revision):
    from .layout_workspace import read_layout, order_edition
    layout = read_layout(con, order_id)
    source = {'document': layout['document'], 'snapshot': layout['snapshot'], 'edition': order_edition(con, order_id, server.ROOT)}
    con.execute('INSERT OR REPLACE INTO publication_sources VALUES (?,?,?)', (order_id, revision, json.dumps(source, ensure_ascii=False)))


def _mapping(document, summary, gift_owner):
    variants = {v['owner']: v for v in document.get('variants') or []}
    rows = []
    for row in summary['allocations']:
        if not row['paid'] + row['gift']:
            continue
        if row['key'] == 'gift':
            owner = gift_owner or ('teacher_variant' if 'teacher_variant' in variants else None)
            if owner not in variants:
                raise HTTPException(409, 'Выберите опубликованный альбом для подарка учителю перед отправкой в печать')
        else:
            owner = next((key for key in ('student:'+row['key'], row['key']) if key in variants), None)
            if owner is None:
                raise HTTPException(409, 'В опубликованном макете нет альбома получателя: ' + row['label'])
        if not variants[owner].get('sequence'):
            raise HTTPException(409, 'Вариант альбома пуст: ' + variants[owner].get('name', owner))
        rows.append({**row, 'owner': owner})
    if not rows:
        raise HTTPException(409, 'Тираж пуст. Распределите экземпляры перед печатью')
    if any(i.get('level') == 'error' for i in document.get('issues') or []):
        raise HTTPException(409, 'В опубликованном макете есть ошибки')
    return rows


def freeze(con, server, order_id, summary, gift_owner=None):
    row = con.execute('SELECT source FROM production_layouts WHERE order_id=?', (order_id,)).fetchone()
    if row:
        return json.loads(row['source'])
    publication = con.execute('SELECT revision,document FROM publications WHERE order_id=?', (order_id,)).fetchone()
    if publication is None:
        raise HTTPException(409, 'Не найдена опубликованная редакция для производства')
    source_row = con.execute('SELECT source FROM publication_sources WHERE order_id=? AND revision=?', (order_id, publication['revision'])).fetchone()
    if source_row is None:
        # Legacy orders can only recover sources when the draft is exactly that publication.
        from .layout_workspace import read_layout
        layout = read_layout(con, order_id)
        if layout['document'] != json.loads(publication['document']):
            raise HTTPException(409, 'Не сохранены ресурсы опубликованной редакции. Рабочий макет отличается; требуется восстановление публикации')
        save_publication_source(con, server, order_id, publication['revision'])
        source_row = con.execute('SELECT source FROM publication_sources WHERE order_id=?', (order_id,)).fetchone()
    source = json.loads(source_row['source'])
    source['allocations'] = _mapping(source['document'], summary, gift_owner)
    from .mvp import publication_photo_ids
    from .layout_workspace import font_bundle
    # Copy only referenced assets; arbitrary snapshot paths never become download paths.
    folder = Path(server.DATA)/'production'/order_id/summary['hash']
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = deepcopy(source['snapshot'])
    snapshot['photos'] = {}
    assets = {}
    for photo_id in sorted(publication_photo_ids(source['document'])):
        path = Path(server.DATA)/'photos'/(photo_id+'.jpg')
        if not path.is_file():
            raise HTTPException(409, 'Фотография опубликованного макета недоступна: '+photo_id)
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        dest = folder/(digest+'.jpg')
        dest.write_bytes(content)
        with Image.open(dest) as image:
            width, height = image.size
        snapshot['photos'][photo_id] = {'path': str(dest), 'width': width, 'height': height}
        assets[photo_id] = digest
    source['order_id'] = order_id
    source['snapshot'] = snapshot
    font_ids = {'main'}
    for groups in (source['document'].get('covers', {}), source['document'].get('shared_spreads', {}), *(source['document'].get('variant_spreads') or {}).values()):
        for spread in groups.values():
            font_ids.update(e.get('font') or 'main' for e in spread.get('elements') or [] if e.get('type') == 'text')
    fonts = font_bundle(source['edition'])
    if font_ids - fonts.keys():
        raise HTTPException(409, 'Шрифт опубликованного макета недоступен')
    source['fonts'] = {key: base64.b64encode(fonts[key] if isinstance(fonts[key], bytes) else Path(fonts[key]).read_bytes()).decode()
                       for key in font_ids if key in fonts}
    source['assets'] = assets
    source['production_hash'] = summary['hash']
    source['layout_hash'] = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    con.execute('INSERT INTO production_layouts VALUES (?,?)', (order_id, json.dumps(source, ensure_ascii=False)))
    return source


def read(con, order_id):
    row = con.execute('SELECT source FROM production_layouts WHERE order_id=?', (order_id,)).fetchone()
    return json.loads(row['source']) if row else None


def measurer(source):
    return ReportLabMeasurer({key: base64.b64decode(value) for key, value in source['fonts'].items()})


@contextmanager
def export_lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _valid(folder, manifest, source):
    if not isinstance(manifest, dict) or manifest.get('version') != VERSION or manifest.get('layout_hash') != source['layout_hash']:
        return False
    for name, digest in manifest.get('checksums', {}).items():
        path = folder/name
        if Path(name).name != name or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            return False
    return bool(manifest.get('checksums'))


def export(server, order_id, source):
    folder = Path(server.DATA)/'exports'/order_id
    with export_lock(folder):
        manifest_path = folder/'manifest.json'
        try:
            cached = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            cached = None
        target = folder/source['layout_hash']
        if _valid(target, cached, source):
            return cached
        try:
            with tempfile.TemporaryDirectory(prefix='.build-', dir=folder) as work:
                staging = Path(work)
                for photo_id, digest in source['assets'].items():
                    path = Path(source['snapshot']['photos'][photo_id]['path'])
                    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                        raise HTTPException(409, 'Повреждены сохранённые ресурсы производственной редакции: '+photo_id)
                renderer = measurer(source)
                files, rendered = [], {}
                for index, row in enumerate(source['allocations'], 1):
                    slug = re.sub(r'[^\w-]+', '_', row['label']).strip('_')[:60] or 'album'
                    name = f'{index:03d}-{slug}.pdf'
                    jpeg = name[:-4]+'-jpeg.zip'
                    owner = row['owner']
                    if owner not in rendered:
                        render_variant(source['document'], owner, source['snapshot'], server.DATA, renderer, staging/name)
                        export_print_files(source['document'], owner, source['snapshot'], server.DATA, renderer, staging/jpeg)
                        rendered[owner] = (name, jpeg)
                    else:
                        for src, dst in zip(rendered[owner], (name, jpeg)):
                            shutil.copyfile(staging/src, staging/dst)
                    files.append({'name': name, 'jpeg_name': jpeg, 'recipient_key': row['key'], 'label': row['label'], 'owner': owner,
                                  'copies_paid': row['paid'], 'copies_gift': row['gift']})
                checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in staging.iterdir()}
                manifest = {'version': VERSION, 'production_hash': source['production_hash'], 'layout_hash': source['layout_hash'],
                            'revision': source['document']['revision'], 'files': files,
                            'total': sum(row['copies_paid']+row['copies_gift'] for row in files),
                            'checksums': checksums, 'bundle_name': 'print-bundle.zip', 'print': source['document'].get('print') or {'dpi': 300, 'files': 'spreads'},
                            'limitations': ['RGB/sRGB; не PDF/X, без согласованного с типографией ICC-профиля и вылетов']}
                (staging/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                with zipfile.ZipFile(staging/'print-bundle.zip', 'w', zipfile.ZIP_STORED) as archive:
                    for path in sorted(staging.iterdir()):
                        if path.name != 'print-bundle.zip':
                            archive.write(path, path.name)
                manifest['checksums']['print-bundle.zip'] = hashlib.sha256((staging/'print-bundle.zip').read_bytes()).hexdigest()
                target.mkdir(exist_ok=True)
                for path in staging.iterdir():
                    path.replace(target/path.name)
                partial = folder/'manifest.json.part'
                partial.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
                partial.replace(manifest_path)
                return manifest
        except (OSError, ValueError, KeyError, LayoutError) as exc:
            raise HTTPException(409, 'Не удалось подготовить печатный комплект: '+str(exc)) from exc
