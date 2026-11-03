"""Resumable projection expansion; fetch new header fields without surveys."""
import hashlib,json,sqlite3,shutil
from pathlib import Path
from SourceCache import INVENTORY
from Identity import record_id
from WellScope import excluded,STATUS_FILTER

def ensure_fields(api,cache,config,required):
    cache=Path(cache);db=sqlite3.connect(cache,timeout=180)
    try:
        meta=dict(db.execute('SELECT * FROM Meta'))
        if 'headerFields' in meta:known=set(json.loads(meta['headerFields']))
        elif 'baselineDefinition' in meta:known=set(json.loads(meta['baselineDefinition']).get('fields','').split(','))
        else:
            row=db.execute('SELECT Payload FROM Wells LIMIT 1').fetchone();known=set(json.loads(row[0])) if row else set()
        missing=set(required)-known
        if not missing:
            db.execute('INSERT OR REPLACE INTO Meta VALUES(?,?)',('headerFields',json.dumps(sorted(known))));db.commit()
            return dict(status='NoNewHeaderFields',fieldsAdded=[])
        definition=hashlib.sha256(json.dumps([sorted(required),config.get('apiFilters',{})],sort_keys=True).encode()).hexdigest()
        db.execute('CREATE TABLE IF NOT EXISTS HeaderExpansion(Name TEXT PRIMARY KEY,NextUrl TEXT,Complete INTEGER,Rows INTEGER)');db.commit()
        total=0
        for stream,status in [('Included',STATUS_FILTER),('Unknown','null')]:
            name=definition+stream;saved=db.execute('SELECT NextUrl,Complete,Rows FROM HeaderExpansion WHERE Name=?',(name,)).fetchone()
            if saved and saved[1]:total+=saved[2];continue
            rows=saved[2] if saved else 0
            params=dict(config.get('apiFilters',{}),deleteddate='null',envwellstatus=status,fields=','.join(sorted(missing|set(INVENTORY.split(',')))))
            def commit_page(page,next_url):
                nonlocal rows
                if shutil.disk_usage(cache.parent).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; new header-field backfill checkpoint preserved')
                for item in page:
                    if excluded(item.get('ENVWellStatus')):raise RuntimeError('Excluded status in header backfill')
                    ident=record_id(item);prior=db.execute('SELECT Origin,Payload FROM Wells WHERE Id=?',(ident,)).fetchone()
                    if not prior:continue
                    payload=json.loads(prior[1]);payload.update({k:item.get(k) for k in missing})
                    db.execute('UPDATE Wells SET Payload=? WHERE Id=?',(json.dumps(payload,separators=(',',':')),ident));db.execute('INSERT OR IGNORE INTO DirtyOrigins VALUES(?)',(prior[0],))
                rows+=len(page);db.execute('INSERT OR REPLACE INTO HeaderExpansion VALUES(?,?,?,?)',(name,next_url,int(not next_url),rows));db.commit();print('New header fields backfilled '+str(rows),flush=True)
            for page in api.pages('wells',params,start_url=saved[0] if saved else None,checkpoint=commit_page):pass
            total+=rows
        db.execute('INSERT OR REPLACE INTO Meta VALUES(?,?)',('headerFields',json.dumps(sorted(known|set(required)))));db.commit()
        return dict(status='HeaderFieldsExpanded',fieldsAdded=sorted(missing),rowsRead=total,surveyDownloads=0)
    finally:db.close()
