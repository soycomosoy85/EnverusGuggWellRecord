"""Apply the existing cancelled/expired-permit rule to cached vendor spellings."""
import json,sqlite3
from pathlib import Path
from ProcessLock import ProcessLock
from WellScope import EXCLUDED_STATUS_VALUES

ROOT=Path(__file__).resolve().parents[1]


def reconcile(cache):
    db=sqlite3.connect(cache)
    try:
        rows=db.execute("SELECT Id,Origin,json_extract(Payload,'$.ENVWellStatus') FROM Wells WHERE upper(trim(json_extract(Payload,'$.ENVWellStatus'))) IN ("+','.join('?' for _ in EXCLUDED_STATUS_VALUES)+')',EXCLUDED_STATUS_VALUES).fetchall()
        db.executemany('INSERT OR IGNORE INTO DirtyOrigins VALUES(?)',[(r[1],) for r in rows])
        db.executemany('DELETE FROM Wells WHERE Id=?',[(r[0],) for r in rows]);db.commit()
        return dict(removedFromScope=len(rows),sourceStatuses=sorted({r[2] for r in rows}),excludedStatuses=list(EXCLUDED_STATUS_VALUES),apiDownloads=0)
    finally:db.close()


if __name__=='__main__':
    config=json.loads((ROOT/'Json/Config/Workflow.json').read_text());base=ROOT/'Sqlite'/config['profile']/'Cache'
    with ProcessLock(base/'Workflow.lock'):print(json.dumps(reconcile(base/'EnverusCache.sqlite'),indent=2))
