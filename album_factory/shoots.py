"""Shoot storage and an additive migration for existing portrait orders."""
import uuid
from datetime import datetime, timezone


def create(con, order_id, kind, title):
    shoot_id = uuid.uuid4().hex
    con.execute('INSERT INTO shoots VALUES (?,?,?,?,?)',
                (shoot_id, order_id, kind, title, datetime.now(timezone.utc).isoformat()))
    return shoot_id


def default_portrait(con, order_id):
    row = con.execute("SELECT id FROM shoots WHERE order_id=? AND kind='portrait' ORDER BY created_at,id LIMIT 1", (order_id,)).fetchone()
    return row['id'] if row else create(con, order_id, 'portrait', 'Портреты')


def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS shoots (
        id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
        kind TEXT NOT NULL CHECK(kind IN ('portrait','general')),
        title TEXT NOT NULL, created_at TEXT NOT NULL)""")
    if 'shoot_id' not in {r['name'] for r in con.execute('PRAGMA table_info(photos)')}:
        con.execute('ALTER TABLE photos ADD COLUMN shoot_id TEXT REFERENCES shoots(id)')
    for row in con.execute('SELECT DISTINCT order_id FROM photos WHERE shoot_id IS NULL').fetchall():
        shoot_id = default_portrait(con, row['order_id'])
        con.execute('UPDATE photos SET shoot_id=? WHERE order_id=? AND shoot_id IS NULL', (shoot_id, row['order_id']))
    con.execute('CREATE INDEX IF NOT EXISTS photos_shoot_status ON photos(shoot_id,status)')
