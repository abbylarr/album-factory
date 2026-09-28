"""One pipeline stage per order. Actions move it forward; the photographer moves print → delivery → archive by hand."""
from datetime import datetime, timezone

from fastapi import HTTPException

STAGES = ('new', 'photos', 'forms', 'layout', 'approval', 'print', 'delivery', 'archive')
MANUAL = {('print', 'delivery'), ('delivery', 'archive'), ('delivery', 'print'), ('archive', 'delivery')}
LEGACY = {'planned': 'new', 'scheduled': 'new', 'upload': 'photos'}
WORKFLOW = {'selection': 'forms', 'layout': 'approval', 'client_approved': 'approval', 'production_allowed': 'print'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def migrate(con):
    """Map the old four-value stage (plus the MVP workflow) onto the pipeline once."""
    if 'stage_at' not in {r['name'] for r in con.execute('PRAGMA table_info(orders)')}:
        con.execute("ALTER TABLE orders ADD COLUMN stage_at TEXT NOT NULL DEFAULT ''")
        con.execute('UPDATE orders SET stage_at=created_at')
    rows = con.execute(f"""SELECT o.id, o.stage, t.workflow FROM orders o LEFT JOIN order_terms t ON t.order_id=o.id
        WHERE o.stage IN ({','.join('?' for _ in LEGACY)})""", tuple(LEGACY)).fetchall()
    for row in rows:
        stage = LEGACY[row['stage']]
        later = WORKFLOW.get(row['workflow'])
        if later and STAGES.index(later) > STAGES.index(stage):
            stage = later
        con.execute('UPDATE orders SET stage=? WHERE id=?', (stage, row['id']))


def set_stage(con, order_id, stage):
    """Enter `stage`; the time is kept so the UI can tell how long an order waits."""
    con.execute('UPDATE orders SET stage=?, stage_at=? WHERE id=? AND stage<>?', (stage, _now(), order_id, stage))


def advance(con, order_id, stage):
    """Move forward to `stage`; an order already further along keeps its stage."""
    earlier = STAGES[:STAGES.index(stage)]
    con.execute(f"UPDATE orders SET stage=?, stage_at=? WHERE id=? AND stage IN ({','.join('?' for _ in earlier)})",
                (stage, _now(), order_id, *earlier))


def reopen_layout(con, order_id):
    """Layout work (re)starts; not allowed once the order went to print."""
    row = con.execute('SELECT stage FROM orders WHERE id=?', (order_id,)).fetchone()
    if row and row['stage'] in STAGES[STAGES.index('print'):]:
        raise HTTPException(409, 'Заказ уже отправлен в печать')
    set_stage(con, order_id, 'layout')


def move(con, order_id, stage):
    row = con.execute('SELECT stage FROM orders WHERE id=?', (order_id,)).fetchone()
    if (row['stage'], stage) not in MANUAL:
        raise HTTPException(409, 'Этот переход выполняется действием на странице заказа')
    set_stage(con, order_id, stage)
