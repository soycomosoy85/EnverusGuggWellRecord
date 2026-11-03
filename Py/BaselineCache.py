"""Resumable first acquisition: page commits and per-bore survey checkpoints."""
import json,os,sqlite3,shutil
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from Identity import record_id,origin,survey_key
from SourceCache import initialize,INVENTORY,HEADER_FIELDS,STATION_FIELDS
from WellScope import STATUS_FILTER,excluded

def baseline(api,path,config,well_fields):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);pending=path.with_name('BaselinePending.sqlite');progress_path=path.parent/'BaselineStatus.json'
    db=sqlite3.connect(pending,timeout=180);initialize(db)
    db.executescript('CREATE TABLE IF NOT EXISTS Acquisition(Name TEXT PRIMARY KEY,NextUrl TEXT,Pages INTEGER,Rows INTEGER,Complete INTEGER);CREATE TABLE IF NOT EXISTS Inventory(Id TEXT PRIMARY KEY,Api TEXT,Origin TEXT,Updated TEXT);CREATE TABLE IF NOT EXISTS CompletedBores(Api TEXT PRIMARY KEY);')
    meta=dict(db.execute('SELECT Key,Value FROM Meta'));start=meta.get('baselineStarted',datetime.now(timezone.utc).isoformat());scope=json.dumps(config.get('apiFilters',{}),sort_keys=True)
    fields=','.join(sorted(set(well_fields)|set(INVENTORY.split(','))|{'DeletedDate','LateralLine','ENVRegion','CoordinateSource'}))
    definition=json.dumps(dict(scope=scope,fields=fields),sort_keys=True)
    if meta.get('baselineDefinition') and meta['baselineDefinition']!=definition:raise RuntimeError('Baseline definition changed; resume with its original scope/fields')
    db.executemany('INSERT OR REPLACE INTO Meta VALUES(?,?)',[('baselineStarted',start),('baselineDefinition',definition)]);db.commit()
    report=dict(started=start,status='Running',resumable=True,phase='Inventory',cache=str(path),pendingCache=str(pending))
    def status(**values):
        report.update(values);report['updated']=datetime.now(timezone.utc).isoformat();temp=progress_path.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2));os.replace(temp,progress_path);print(json.dumps(values),flush=True)
    def disk_guard():
        if shutil.disk_usage(path.parent).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Free disk below configured reserve; baseline checkpoint preserved')
    common=dict(config.get('apiFilters',{}),deleteddate='null')
    def acquire(name,params,table):
        saved=db.execute('SELECT NextUrl,Pages,Rows,Complete FROM Acquisition WHERE Name=?',(name,)).fetchone()
        if saved and saved[3]:return
        pages,rows=(saved[1],saved[2]) if saved else (0,0)
        def commit(data,next_url):
            nonlocal pages,rows
            disk_guard()
            with db:
                for w in data:
                    if excluded(w.get('ENVWellStatus')):raise RuntimeError('Excluded well received')
                    ident=record_id(w);bore=survey_key(w)
                    db.execute('INSERT OR REPLACE INTO Inventory VALUES(?,?,?,?)',(ident,bore,origin(w),w.get('UpdatedDate')))
                    if table=='Wells':db.execute('INSERT OR REPLACE INTO Wells VALUES(?,?,?,?,?)',(ident,bore,origin(w),w.get('UpdatedDate'),json.dumps(w,separators=(',',':'))))
                pages+=1;rows+=len(data);db.execute('INSERT OR REPLACE INTO Acquisition VALUES(?,?,?,?,?)',(name,next_url,pages,rows,int(not next_url)))
            status(phase=table,stream=name,pages=pages,rows=rows)
        for _ in api.pages('wells',params,start_url=saved[0] if saved else None,checkpoint=commit):pass
    try:
        disk_guard()
        for label,filter_value in [('Included',STATUS_FILTER),('Unknown','null')]:acquire('Inventory:'+label,dict(common,envwellstatus=filter_value,fields=INVENTORY),'Inventory')
        for label,filter_value in [('Included',STATUS_FILTER),('Unknown','null')]:acquire('Wells:'+label,dict(common,envwellstatus=filter_value,fields=fields),'Wells')
        # A long crawl is not a provider-side snapshot. Resolve inventory members
        # not returned by the detail crawl, and retain new included detail rows.
        db.execute('CREATE INDEX IF NOT EXISTS InventoryApi ON Inventory(Api)');db.commit()
        missing=list(db.execute('SELECT i.Id,i.Api,i.Origin FROM Inventory i LEFT JOIN Wells w ON i.Id=w.Id WHERE w.Id IS NULL'))
        for ident,bore,group in missing:
            params=dict(common,fields=fields)
            if bore:params['api_uwi_12_unformatted']='in('+bore+')'
            else:params['api_uwi_unformatted']=group.split('|',1)[-1]
            for filter_value in [STATUS_FILTER,'null']:
                for page in api.pages('wells',dict(params,envwellstatus=filter_value)):
                    with db:
                        for w in page:
                            key=record_id(w);db.execute('INSERT OR REPLACE INTO Wells VALUES(?,?,?,?,?)',(key,survey_key(w),origin(w),w.get('UpdatedDate'),json.dumps(w,separators=(',',':'))))
            if not db.execute('SELECT 1 FROM Wells WHERE Id=?',(ident,)).fetchone():db.execute('DELETE FROM Inventory WHERE Id=?',(ident,))
        db.commit();total_wells=db.execute('SELECT count(*) FROM Wells').fetchone()[0]
        # Full survey requests are bounded by the included well allowlist.
        total_bores=db.execute("SELECT count(DISTINCT Api) FROM Wells WHERE Api!=''").fetchone()[0]
        finished=db.execute('SELECT count(*) FROM CompletedBores').fetchone()[0];status(phase='Surveys',eligibleWells=total_wells,totalWellbores=total_bores,completedWellbores=finished)
        from EnverusApi import Api
        def fetch(batch):
            worker=api if config.get('_testSerial') else Api(token=api.token);worker.allow=lambda ids:set(ids)<=set(batch)
            result={a:{'Headers':[],'Stations':[]} for a in batch};params=dict(deleteddate='null',api_uwi_12_unformatted='in('+','.join(batch)+')')
            for dataset,table,projection in [('header-directional-surveys','Headers',HEADER_FIELDS),('full-directional-surveys','Stations',STATION_FIELDS)]:
                for page in worker.pages(dataset,dict(params,fields=projection)):
                    for row in page:
                        bore=str(row.get('API_UWI_12_Unformatted'))
                        if bore not in result:raise RuntimeError('Survey filter not honored')
                        result[bore][table].append(row)
            if not config.get('_testSerial'):api.token=worker.token
            return result
        # One worker batch is the retry unit: failed batches are not marked done.
        cursor=db.execute("SELECT DISTINCT w.Api FROM Wells w LEFT JOIN CompletedBores c ON w.Api=c.Api WHERE w.Api!='' AND c.Api IS NULL ORDER BY w.Api")
        with ThreadPoolExecutor(max_workers=config['workers']) as pool:
            while True:
                window=[r[0] for r in cursor.fetchmany(config['surveyBatchSize']*config['workers'])]
                if not window:break
                disk_guard();batches=[window[i:i+config['surveyBatchSize']] for i in range(0,len(window),config['surveyBatchSize'])]
                results=map(fetch,batches) if config.get('_testSerial') else pool.map(fetch,batches)
                for result in results:
                    with db:
                        for bore,tables in result.items():
                            for table,data in tables.items():
                                db.execute('DELETE FROM '+table+' WHERE Api=?',(bore,));db.executemany('INSERT INTO '+table+' VALUES(?,?,?)',[(bore,i,json.dumps(row,separators=(',',':'))) for i,row in enumerate(data)])
                            db.execute('INSERT OR REPLACE INTO BoreVersions VALUES(?,?)',(bore,start));db.execute('INSERT OR REPLACE INTO CompletedBores VALUES(?)',(bore,));finished+=1
                    status(completedWellbores=finished,totalWellbores=total_bores)
        cursor.close()
        if db.execute("SELECT count(DISTINCT w.Api) FROM Wells w LEFT JOIN CompletedBores c ON w.Api=c.Api WHERE w.Api!='' AND c.Api IS NULL").fetchone()[0]:raise RuntimeError('Incomplete survey coverage')
        station_count=db.execute('SELECT count(*) FROM Stations').fetchone()[0];header_count=db.execute('SELECT count(*) FROM Headers').fetchone()[0]
        final=dict(started=start,baseline=True,eligibleWells=total_wells,surveyWellboresRefreshed=finished,surveyHeaders=header_count,surveyStations=station_count,resumedFromCheckpoints=bool(meta),completed=datetime.now(timezone.utc).isoformat())
        db.executemany('INSERT OR REPLACE INTO Meta VALUES(?,?)',[('watermark',start),('scope',scope),('lastSync',json.dumps(final))]);db.commit();db.close();db=None
        if path.exists():raise RuntimeError('Published cache already exists; baseline not overwritten')
        os.replace(pending,path);status(status='Complete',phase='Complete',**final);return final
    except Exception as error:
        status(status='RetryableFailure',errorType=type(error).__name__,message=str(error)[:300]);raise
    finally:
        if db is not None:db.close()
