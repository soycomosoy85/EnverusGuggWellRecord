"""Incremental cache with an atomic successful-run watermark and exit reconciliation.

Only a thin eligible identifier inventory is read in full on refresh. Full well
payloads are fetched for changed wellbores; survey-only changes also trigger a
complete replacement of that bore's cached survey, including station deletions.
"""
import json,os,sqlite3,shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from pathlib import Path
from Identity import record_id,survey_key,origin
from WellScope import STATUS_FILTER,EXCLUDED_STATUS_FILTER,excluded
from ProcessLock import ProcessLock
from SourceContent import content,same_surveys,survey_version

INVENTORY='API_UWI,API_UWI_Unformatted,API_UWI_12_Unformatted,API_UWI_14_Unformatted,Country,WellID,CompletionID,UpdatedDate,ENVWellStatus'
STATION_FIELDS='API_UWI_12_Unformatted,StationNumber,CoordinateSource,MeasuredDepth_FT,Longitude,Latitude,SubseaElevation_FT,Inclination_DEG,UpdatedDate,DeletedDate'
HEADER_FIELDS='API_UWI_12_Unformatted,CoordinateSource,WellID,UpdatedDate,DeletedDate'
META_FIELDS='API_UWI_12_Unformatted,UpdatedDate,DeletedDate'

def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS Wells(Id TEXT PRIMARY KEY,Api TEXT,Origin TEXT,Updated TEXT,Payload TEXT);CREATE INDEX IF NOT EXISTS WellApi ON Wells(Api);CREATE INDEX IF NOT EXISTS WellOrigin ON Wells(Origin);CREATE TABLE IF NOT EXISTS Headers(Api TEXT,Seq INTEGER,Payload TEXT,PRIMARY KEY(Api,Seq));CREATE TABLE IF NOT EXISTS Stations(Api TEXT,Seq INTEGER,Payload TEXT,PRIMARY KEY(Api,Seq));CREATE TABLE IF NOT EXISTS BoreVersions(Api TEXT PRIMARY KEY,Version TEXT);CREATE TABLE IF NOT EXISTS Meta(Key TEXT PRIMARY KEY,Value TEXT);CREATE TABLE IF NOT EXISTS DirtyOrigins(Origin TEXT PRIMARY KEY);')
def chunks(cursor,size):
    while True:
        batch=cursor.fetchmany(size)
        if not batch:return
        yield [r[0] for r in batch]
def well_pages(api,params,include_null=True):
    # SQL NOT IN excludes NULL as well as the named values. Use a separate
    # disjoint server request rather than silently losing unknown-status wells.
    for status in ([STATUS_FILTER,'null'] if include_null else [STATUS_FILTER]):
        yield from api.pages('wells',dict(params,envwellstatus=status))
def sync(api,path,config,well_fields,now=None):
    if not Path(path).exists() and not config.get('_testSerial'):
        from BaselineCache import baseline
        with ProcessLock(Path(path).with_suffix('.lock')):return baseline(api,path,config,well_fields)
    start=now or datetime.now(timezone.utc);stamp=start.strftime('%Y%m%dT%H%M%SZ');path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    staging=path.with_name('Pending'+stamp+'.sqlite');lock=path.with_suffix('.lock')
    held=ProcessLock(lock);held.__enter__()
    db=None;previous=None
    try:
        db=sqlite3.connect(staging)
        initialize(db)
        incremental=path.exists()
        if incremental:
            # Stage only metadata and changed payloads, not a second copy of a
            # potentially very large North America station cache.
            old=sqlite3.connect(path)
            db.executemany('INSERT INTO Meta VALUES(?,?)',old.execute('SELECT Key,Value FROM Meta'))
            db.executemany('INSERT INTO Wells VALUES(?,?,?,?,NULL)',old.execute('SELECT Id,Api,Origin,Updated FROM Wells'))
            old.close();db.commit()
        saved=dict(db.execute('SELECT Key,Value FROM Meta'));baseline='watermark' not in saved
        signature=json.dumps(config.get('apiFilters',{}),sort_keys=True)
        if saved.get('scope') and saved['scope']!=signature:raise RuntimeError('Scope changed: use a new profile/cache or explicitly rebuild a baseline')
        db.execute('DROP TABLE IF EXISTS Inventory');db.execute('CREATE TABLE Inventory(Id TEXT PRIMARY KEY,Api TEXT,Origin TEXT,Updated TEXT,Payload TEXT)')
        common=dict(config.get('apiFilters',{}),deleteddate='null',envwellstatus=STATUS_FILTER)
        null_count=api.count('wells',dict(common,envwellstatus='null'))
        expected=api.count('wells',common)+null_count
        # No silent dropping of null-status records through NOT IN SQL semantics.
        all_params={k:v for k,v in common.items() if k!='envwellstatus'}
        all_count=api.count('wells',all_params);excluded_count=api.count('wells',dict(all_params,envwellstatus=EXCLUDED_STATUS_FILTER))
        if all_count-excluded_count!=expected:raise RuntimeError('Status-filter count mismatch, possibly null statuses; no cache published')
        progress=0
        for page in well_pages(api,dict(common,fields=INVENTORY),include_null=null_count>0):
            db.executemany('INSERT INTO Inventory VALUES(?,?,?,?,?)',[(record_id(w),survey_key(w),origin(w),w.get('UpdatedDate'),json.dumps(w,separators=(',',':'))) for w in page])
            progress+=len(page)
            if progress%100000==0:print('Eligible identifier inventory '+format(progress,',')+'/'+format(expected,','),flush=True)
        inventory_count=db.execute('SELECT count(*) FROM Inventory').fetchone()[0]
        if inventory_count!=expected:raise RuntimeError('Inventory count changed during read; retry before committing a cache')
        db.execute('CREATE INDEX InventoryApi ON Inventory(Api)')
        removed=db.execute('SELECT count(*) FROM Wells WHERE Id NOT IN(SELECT Id FROM Inventory)').fetchone()[0]
        previous_count=db.execute('SELECT count(*) FROM Wells').fetchone()[0]
        if previous_count and removed/previous_count>config.get('maximumAutomaticRemovalFraction',0.05):raise RuntimeError('Unexpectedly large membership removal; previous cache/watermark preserved. Check entitlement/scope before changing the removal threshold.')
        db.execute('DELETE FROM Wells WHERE Id NOT IN(SELECT Id FROM Inventory)')
        db.execute('CREATE TEMP TABLE ChangedIds AS SELECT i.Id FROM Inventory i LEFT JOIN Wells w ON i.Id=w.Id WHERE w.Id IS NULL OR i.Updated IS NULL OR i.Updated!=w.Updated')
        changed_count=db.execute('SELECT count(*) FROM ChangedIds').fetchone()[0]
        db.execute('CREATE TEMP TABLE Dirty(Api TEXT PRIMARY KEY)');db.execute("INSERT OR IGNORE INTO Dirty SELECT DISTINCT Api FROM Inventory WHERE Id IN(SELECT Id FROM ChangedIds) AND Api!=''")
        def allowed(ids):
            # Separate read connection is not needed: this check is on the main
            # acquisition thread. Worker transports receive a fixed batch allowlist.
            return db.execute('SELECT count(DISTINCT Api) FROM Inventory WHERE Api IN('+','.join('?' for _ in ids)+')',ids).fetchone()[0]==len(set(ids))
        api.allow=allowed
        downloaded=0
        def store(page):
            nonlocal downloaded
            for w in page:
                key=record_id(w)
                if excluded(w.get('ENVWellStatus')) or not db.execute('SELECT 1 FROM Inventory WHERE Id=?',(key,)).fetchone():raise RuntimeError('Source membership changed while fetching well details; retry')
                db.execute('INSERT OR REPLACE INTO Wells VALUES(?,?,?,?,?)',(key,survey_key(w),origin(w),w.get('UpdatedDate'),json.dumps(w,separators=(',',':'))));downloaded+=1
            if downloaded and downloaded%100000==0:print('Full well payloads acquired '+format(downloaded,','),flush=True)
        fields=','.join(sorted(set(well_fields)|set(INVENTORY.split(','))|{'DeletedDate','LateralLine','ENVRegion','CoordinateSource'}))
        if baseline:
            for page in well_pages(api,dict(common,fields=fields),include_null=null_count>0):store(page)
        else:
            for batch in chunks(db.execute("SELECT DISTINCT i.Api FROM Inventory i JOIN ChangedIds c ON i.Id=c.Id WHERE i.Api!='' ORDER BY i.Api"),config['surveyBatchSize']):
                for page in well_pages(api,dict(common,api_uwi_12_unformatted='in('+','.join(batch)+')',fields=fields),include_null=null_count>0):store(page)
            # Preserve wells lacking a bore lookup instead of imposing a US API12.
            for ident,payload in db.execute("SELECT i.Id,i.Payload FROM Inventory i JOIN ChangedIds c ON c.Id=i.Id WHERE i.Api='' "):
                w=json.loads(payload);uwi=w.get('API_UWI_Unformatted')
                if not uwi:raise RuntimeError('Changed well without a queryable UWI; no cache published')
                for page in well_pages(api,dict(common,api_uwi_unformatted=uwi,fields=fields),include_null=null_count>0):store(page)
        missing=db.execute('SELECT count(*) FROM Inventory i LEFT JOIN Wells w ON i.Id=w.Id WHERE w.Id IS NULL OR (i.Updated IS NOT NULL AND w.Updated<i.Updated) OR (i.Id IN(SELECT Id FROM ChangedIds) AND w.Payload IS NULL)').fetchone()[0]
        if missing:raise RuntimeError('Missing changed well payloads; no cache published')
        if not baseline and not config.get('forceSurveyRefresh',False):
            since=(datetime.fromisoformat(saved['watermark'])-timedelta(days=config['lookbackDays'])).date().isoformat()
            for dataset in ['header-directional-surveys','full-directional-surveys']:
                for date_field in ['updateddate','deleteddate']:
                    params={date_field:'ge('+since+')','fields':META_FIELDS}
                    if config['surveyChangeScan']=='GlobalMetadata':scans=[params]
                    else:scans=(dict(params,api_uwi_12_unformatted='in('+','.join(batch)+')') for batch in chunks(db.execute("SELECT DISTINCT Api FROM Inventory WHERE Api!='' ORDER BY Api"),config['surveyBatchSize']))
                    # Query deletion time separately: DeletedDate can advance
                    # without UpdatedDate advancing on the tombstone.
                    for scan in scans:
                        for page in api.pages(dataset,scan,metadata=True):
                            for row in page:
                                bore=str(row.get('API_UWI_12_Unformatted') or '')
                                if db.execute('SELECT 1 FROM Inventory WHERE Api=? LIMIT 1',(bore,)).fetchone():db.execute('INSERT OR IGNORE INTO Dirty VALUES(?)',(bore,))
        else:db.execute("INSERT OR IGNORE INTO Dirty SELECT DISTINCT Api FROM Inventory WHERE Api!=''")
        dirty=db.execute('SELECT count(*) FROM Dirty').fetchone()[0];db.commit()
        # Keep memory bounded even for a multi-million-well baseline. Worker
        # transports use only a fixed eligible batch, never the full subscription.
        from EnverusApi import Api
        def fetch(batch):
            worker=api if config.get('_testSerial') else Api(token=api.token)
            worker.allow=lambda ids:set(ids)<=set(batch)
            params=dict(deleteddate='null',api_uwi_12_unformatted='in('+','.join(batch)+')')
            result={a:{'Headers':[],'Stations':[]} for a in batch}
            for dataset,table,projection in [('header-directional-surveys','Headers',HEADER_FIELDS),('full-directional-surveys','Stations',STATION_FIELDS)]:
                for page in worker.pages(dataset,dict(params,fields=projection)):
                    for row in page:
                        bore=str(row.get('API_UWI_12_Unformatted'))
                        if bore not in result:raise RuntimeError('Survey bore scope failed')
                        result[bore][table].append(row)
            if not config.get('_testSerial'):api.token=worker.token
            return result
        completed=0;survey_content_changed=0
        if incremental:previous=sqlite3.connect('file:'+path.as_posix()+'?mode=ro',uri=True)
        for window in chunks(db.execute('SELECT Api FROM Dirty ORDER BY Api'),config['surveyBatchSize']*config['workers']):
            batches=[window[i:i+config['surveyBatchSize']] for i in range(0,len(window),config['surveyBatchSize'])]
            if config.get('_testSerial'):results=map(fetch,batches)
            else:
                pool=ThreadPoolExecutor(max_workers=config['workers']);results=pool.map(fetch,batches)
            try:
                for result in results:
                    for bore,tables in result.items():
                        completed+=1
                        if previous is not None and same_surveys(previous,bore,tables):continue
                        survey_content_changed+=1
                        for table,rows in tables.items():
                            db.execute('DELETE FROM '+table+' WHERE Api=?',(bore,));db.executemany('INSERT INTO '+table+' VALUES(?,?,?)',[(bore,i,json.dumps(r,separators=(',',':'))) for i,r in enumerate(rows)])
                        db.execute('INSERT OR REPLACE INTO BoreVersions VALUES(?,?)',(bore,survey_version(tables)))
                    db.commit()
            finally:
                if not config.get('_testSerial'):pool.shutdown(wait=True)
            print('Survey wellbores refreshed '+str(completed)+'/'+str(dirty),flush=True)
        for table in ['Headers','Stations','BoreVersions']:db.execute('DELETE FROM '+table+' WHERE Api NOT IN(SELECT DISTINCT Api FROM Wells)')
        if previous is not None:previous.close();previous=None
        report=dict(started=start.isoformat(),baseline=baseline,eligibleWells=inventory_count,unknownStatusWells=null_count,changedWellRecords=changed_count,fullWellPayloadsDownloaded=downloaded,removedFromScope=removed,surveyWellboresRefreshed=dirty,surveyContentChanged=survey_content_changed,metadataMode=config['surveyChangeScan'])
        db.executemany('INSERT OR REPLACE INTO Meta VALUES(?,?)',[('watermark',start.isoformat()),('scope',signature),('lastSync',json.dumps(report))]);db.execute('DROP TABLE Inventory');db.commit();db.close();db=None
        if not incremental:os.replace(staging,path)
        else:
            target=sqlite3.connect(path)
            try:
                initialize(target);target.execute('ATTACH DATABASE ? AS delta',(str(staging),));target.execute('BEGIN IMMEDIATE')
                target.create_function('well_content',1,content,deterministic=True)
                # Retain the payload used by the geometry signature when only
                # source timestamps/key ordering changed. Updated still advances
                # independently, so the next inventory does not fetch it again.
                target.execute('UPDATE delta.Wells SET Payload=(SELECT w.Payload FROM main.Wells w WHERE w.Id=delta.Wells.Id) WHERE Payload IS NOT NULL AND EXISTS(SELECT 1 FROM main.Wells w WHERE w.Id=delta.Wells.Id AND well_content(w.Payload)=well_content(delta.Wells.Payload))')
                report['wellContentChanged']=target.execute('SELECT count(*) FROM delta.Wells d LEFT JOIN Wells w ON w.Id=d.Id WHERE d.Payload IS NOT NULL AND (w.Id IS NULL OR w.Payload!=d.Payload)').fetchone()[0]
                target.execute('UPDATE delta.Meta SET Value=? WHERE Key=?',(json.dumps(report),'lastSync'))
                target.execute('INSERT OR IGNORE INTO DirtyOrigins SELECT Origin FROM Wells WHERE Id NOT IN(SELECT Id FROM delta.Wells)')
                target.execute('INSERT OR IGNORE INTO DirtyOrigins SELECT w.Origin FROM Wells w JOIN delta.Wells d ON w.Id=d.Id WHERE d.Payload IS NOT NULL AND w.Payload!=d.Payload')
                target.execute('INSERT OR IGNORE INTO DirtyOrigins SELECT d.Origin FROM delta.Wells d LEFT JOIN Wells w ON w.Id=d.Id WHERE d.Payload IS NOT NULL AND (w.Id IS NULL OR w.Payload!=d.Payload)')
                target.execute('DELETE FROM Wells WHERE Id NOT IN(SELECT Id FROM delta.Wells)')
                target.execute('INSERT OR REPLACE INTO Wells SELECT * FROM delta.Wells WHERE Payload IS NOT NULL')
                target.execute('INSERT OR IGNORE INTO DirtyOrigins SELECT w.Origin FROM Wells w JOIN delta.BoreVersions b ON w.Api=b.Api')
                for table in ['Headers','Stations']:
                    target.execute('DELETE FROM '+table+' WHERE Api IN(SELECT Api FROM delta.BoreVersions)')
                    target.execute('INSERT INTO '+table+' SELECT * FROM delta.'+table)
                    target.execute('DELETE FROM '+table+' WHERE Api NOT IN(SELECT DISTINCT Api FROM Wells)')
                target.execute('INSERT OR REPLACE INTO BoreVersions SELECT * FROM delta.BoreVersions')
                target.execute('DELETE FROM BoreVersions WHERE Api NOT IN(SELECT DISTINCT Api FROM Wells)')
                target.execute('INSERT OR REPLACE INTO Meta SELECT * FROM delta.Meta');target.commit()
            except Exception:target.rollback();raise
            finally:target.close()
        return report
    finally:
        if previous is not None:previous.close()
        if db is not None:db.close()
        if staging.exists():staging.unlink()
        held.__exit__(None,None,None)
