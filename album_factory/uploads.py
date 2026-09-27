"""Resumable upload sessions. Bytes stay in a ``.partial`` file until finish checks them."""
import hashlib
import sqlite3
from pathlib import Path

_COLUMNS = (
    "id", "order_id", "shoot_id", "filename", "sha256", "size", "received", "created_at",
)


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS upload_parts (
        id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        shoot_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        received INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )""")
    con.commit()


def _session(row):
    if row is None:
        return None
    if isinstance(row, sqlite3.Row):
        return {name: row[name] for name in _COLUMNS}
    return dict(zip(_COLUMNS, row))


def _fetch(con, upload_id):
    return _session(con.execute("SELECT * FROM upload_parts WHERE id=?", (upload_id,)).fetchone())


def partial_path(data_dir, upload_id) -> Path:
    return Path(data_dir) / "uploads" / f"{upload_id}.partial"


def start(con, upload_id, order_id, shoot_id, filename, size, sha256, now):
    init(con)
    con.execute(
        """INSERT INTO upload_parts
           (id, order_id, shoot_id, filename, sha256, size, received, created_at)
           VALUES (?,?,?,?,?,?,0,?)
           ON CONFLICT(id) DO NOTHING""",
        (upload_id, order_id, shoot_id, filename, sha256, int(size), now),
    )
    con.commit()
    return _fetch(con, upload_id)


def write_chunk(con, data_dir, upload_id, offset, data):
    row = _fetch(con, upload_id)
    if row is None:
        raise ValueError("Сессия загрузки не найдена")
    if offset != row["received"]:
        raise ValueError("Смещение не совпадает с уже принятым объёмом")
    chunk = bytes(data)
    received = offset + len(chunk)
    if received > row["size"]:
        raise ValueError("Фрагмент выходит за объявленный размер")
    path = partial_path(data_dir, upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("r+b" if path.exists() else "wb") as handle:
        handle.seek(offset)
        handle.write(chunk)
        handle.flush()
    con.execute("UPDATE upload_parts SET received=? WHERE id=?", (received, upload_id))
    con.commit()
    return received


def finish(con, data_dir, upload_id) -> bytes:
    row = _fetch(con, upload_id)
    if row is None:
        raise ValueError("Сессия загрузки не найдена")
    if row["received"] != row["size"]:
        raise ValueError("Загрузка ещё не полная")
    path = partial_path(data_dir, upload_id)
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise ValueError("Файл загрузки не найден") from exc
    if len(body) != row["size"]:
        raise ValueError("Размер файла не совпадает с сессией")
    digest = hashlib.sha256(body).hexdigest()
    if digest != str(row["sha256"]).lower():
        raise ValueError("Контрольная сумма не совпадает")
    return body
