"""Explicit schema migration preserving source surveys and existing deliveries."""
import json,sqlite3
from datetime import datetime,timezone
from pathlib import Path

def migrate(root,config):
    root=Path(root);cache=root/'Sqlite'/config['profile']/'Cache';source=cache/'EnverusCache.sqlite';state=cache/'Processed.sqlite'
    if not source.exists():raise RuntimeError('Import or sync the source cache before migration')
    db=sqlite3.connect(source)
    try:metadata=dict(db.execute('SELECT * FROM Meta'))
    finally:db.close()
    required={f['directApiField'] for f in json.loads((root/'Json/Config/HeaderSchema.json').read_text())['fields']}
    if not required<=set(json.loads(metadata.get('headerFields','[]'))):raise RuntimeError('Run sync with the new template first; new header fields must be backfilled before product migration')
    if not state.exists():return dict(status='InitialBuildRequired')
    db=sqlite3.connect(state)
    try:
        names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'ProductMeta' not in names:return dict(status='InitialBuildRequired')
        meta=dict(db.execute('SELECT * FROM ProductMeta'))
        if meta.get('deliveryContract')=='ThreeProductsV2':return dict(status='AlreadyMigrated')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        db.execute('BEGIN IMMEDIATE')
        for table in ['ProductMeta','Managed','ShpRows','ShpParts','ShpPending']:
            if table in names:db.execute('ALTER TABLE '+table+' RENAME TO '+table+'Previous'+stamp)
        for index in ['ManagedOrigin','ShpOrigin']:
            db.execute('DROP INDEX IF EXISTS '+index)
        from ManagedProducts import initialize
        initialize(db);db.execute("INSERT INTO ProductMeta VALUES('deliveryContract','ThreeProductsV2')");db.commit()
        return dict(status='ReadyForThreeProductBuild',sourceCachePreserved=True,oldOutputsPreserved=True,nextAction='build')
    finally:db.close()
