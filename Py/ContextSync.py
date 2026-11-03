"""Independent transactional caches for non-well Enverus context datasets.

Inventory reconciliation detects records leaving current rosters, including
active rigs. ArcPy is deliberately excluded from this acquisition module so
the cache/change interface can later feed PostgreSQL/PostGIS.
"""
import hashlib,json,sqlite3,shutil
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode,urlparse,urljoin,parse_qsl,urlunparse
from requests.utils import parse_header_links
from EnverusApi import BASE

ALLOWED={'pipelines','facilities','operator-land','active-rigs','transactions'}

def packed(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def identity(row,name):
    value=row.get(name)
    if value is None or isinstance(value,bool) or str(value).strip()=='':raise RuntimeError('Missing context source identifier: '+name)
    if isinstance(value,float) and value.is_integer():return str(int(value))
    return str(value)
def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS Records(Id TEXT PRIMARY KEY,Updated TEXT,Payload TEXT,Hash TEXT);CREATE TABLE IF NOT EXISTS Meta(Key TEXT PRIMARY KEY,Value TEXT);CREATE TABLE IF NOT EXISTS Dirty(Id TEXT PRIMARY KEY);CREATE TABLE IF NOT EXISTS GisState(Id TEXT PRIMARY KEY,Hash TEXT,Oid INTEGER);')

def pages(api,dataset,params):
    if dataset not in ALLOWED:raise RuntimeError('Context dataset is not enabled in the verified allowlist')
    params=dict(params,pagesize=params.get('pagesize',20000));url=BASE+dataset+'?'+urlencode(params)
    while url:
        data,headers=api.request(url)
        if not isinstance(data,list):raise RuntimeError('Unexpected context response schema')
        yield data
        link=next((v for k,v in headers.items() if k.lower()=='link'),'');next_url=next((v['url'] for v in parse_header_links(link) if v.get('rel')=='next'),None)
        if not next_url or not data:break
        url=('https://api.enverus.com'+next_url if next_url.startswith('/v3/') else BASE.rstrip('/')+next_url) if next_url.startswith('/') else urljoin(BASE,next_url)
        parsed=urlparse(url)
        if parsed.netloc!='api.enverus.com' or parsed.path.rstrip('/')!=(urlparse(BASE).path+dataset).rstrip('/'):raise RuntimeError('Context pagination changed endpoint')
        following=dict(parse_qsl(parsed.query))
        for k,v in params.items():
            if k.lower() not in ['offset','cursor','page','skip']:following[k]=v
        url=urlunparse(parsed._replace(query=urlencode(following)))

def sync(api,path,layer,config):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);dataset=layer['dataset'];id_field=layer['idField']
    if dataset not in ALLOWED or not layer.get('enabled',True):raise RuntimeError('Dataset disabled or not allowed')
    started=datetime.now(timezone.utc).isoformat();db=sqlite3.connect(path,timeout=180);initialize(db);db.commit()
    pending=sqlite3.connect(path.with_name(path.stem+'Pending.sqlite'),timeout=180)
    def guard():
        if shutil.disk_usage(path.parent).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; context cache and pending payloads preserved')
    try:
        pending.executescript('CREATE TABLE IF NOT EXISTS Payloads(Id TEXT PRIMARY KEY,Updated TEXT,Payload TEXT,Hash TEXT);DROP TABLE IF EXISTS Inventory;CREATE TABLE Inventory(Id TEXT PRIMARY KEY,Updated TEXT);')
        guard();expected=api.count(dataset,{'deleteddate':'null'})
        for page in pages(api,dataset,dict(deleteddate='null',fields=id_field+',UpdatedDate')):
            guard()
            try:pending.executemany('INSERT INTO Inventory VALUES(?,?)',[(identity(w,id_field),w.get('UpdatedDate')) for w in page])
            except sqlite3.IntegrityError:raise RuntimeError('Context identifier is not unique; no cache changes published') from None
            pending.commit()
        count=pending.execute('SELECT count(*) FROM Inventory').fetchone()[0]
        if count!=expected:raise RuntimeError('Context inventory count changed during scan; retry before publication')
        old=db.execute('SELECT count(*) FROM Records').fetchone()[0]
        pending.execute('ATTACH DATABASE ? AS previous',(str(path),))
        removed=pending.execute('SELECT count(*) FROM previous.Records r WHERE NOT EXISTS(SELECT 1 FROM Inventory i WHERE i.Id=r.Id)').fetchone()[0]
        limit=layer.get('maximumAutomaticRemovalFraction',config.get('maximumAutomaticRemovalFraction',.1))
        if old and removed/old>limit:raise RuntimeError('Context membership removal exceeds configured guard; previous cache preserved')
        pending.execute('DELETE FROM Payloads WHERE Updated IS NULL OR NOT EXISTS(SELECT 1 FROM Inventory i WHERE i.Id=Payloads.Id AND i.Updated IS Payloads.Updated)')
        pending.execute('DROP TABLE IF EXISTS Required');pending.execute('CREATE TABLE Required(Id TEXT PRIMARY KEY)')
        pending.execute('INSERT INTO Required SELECT i.Id FROM Inventory i LEFT JOIN previous.Records r ON i.Id=r.Id WHERE r.Id IS NULL OR i.Updated IS NOT r.Updated OR i.Updated IS NULL');pending.commit()
        changed=pending.execute('SELECT count(*) FROM Required').fetchone()[0];downloaded=0
        def save(page,allowed=None):
            nonlocal downloaded
            guard()
            for row in page:
                ident=identity(row,id_field)
                if allowed is not None and ident not in allowed:raise RuntimeError('Context API ignored identifier filter')
                inventory=pending.execute('SELECT Updated FROM Inventory WHERE Id=?',(ident,)).fetchone()
                if not inventory:continue
                payload=packed(row);pending.execute('INSERT OR REPLACE INTO Payloads VALUES(?,?,?,?)',(ident,row.get('UpdatedDate'),payload,hashlib.sha256(payload.encode()).hexdigest()))
            pending.commit();downloaded+=len(page)
            print(dataset+': full records received '+str(downloaded),flush=True)
        cached=pending.execute('SELECT count(*) FROM Payloads').fetchone()[0]
        if not old and not cached:
            for page in pages(api,dataset,{'deleteddate':'null','pagesize':layer.get('pageSize',2000)}):save(page)
        else:
            while batch:=pending.execute('SELECT r.Id FROM Required r WHERE NOT EXISTS(SELECT 1 FROM Payloads p WHERE p.Id=r.Id) ORDER BY r.Id LIMIT ?',(config.get('batchSize',100),)).fetchall():
                ids={r[0] for r in batch}
                if any(',' in x or '(' in x or ')' in x for x in ids):raise RuntimeError('Context identifier needs a supported query encoding')
                for page in pages(api,dataset,{'deleteddate':'null','pagesize':layer.get('pageSize',2000),id_field.lower():'in('+','.join(sorted(ids))+')'}):save(page,ids)
                if any(not pending.execute('SELECT 1 FROM Payloads WHERE Id=?',(ident,)).fetchone() for ident in ids):raise RuntimeError('Context API did not return requested current identifiers; retry inventory')
        missing=pending.execute('SELECT count(*) FROM Required r JOIN Inventory i ON r.Id=i.Id LEFT JOIN Payloads p ON r.Id=p.Id WHERE p.Id IS NULL OR p.Updated IS NOT i.Updated').fetchone()[0]
        if missing:raise RuntimeError('Context payloads differ from current inventory; retry from saved payloads')
        pending.commit();pending.close();pending=None
        db.execute('ATTACH DATABASE ? AS delta',(str(path.with_name(path.stem+'Pending.sqlite')),));db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO Dirty SELECT Id FROM Records WHERE Id NOT IN(SELECT Id FROM delta.Inventory)')
        db.execute('INSERT OR IGNORE INTO Dirty SELECT p.Id FROM delta.Payloads p JOIN delta.Required q ON p.Id=q.Id LEFT JOIN Records r ON p.Id=r.Id WHERE r.Id IS NULL OR r.Hash!=p.Hash')
        db.execute('DELETE FROM Records WHERE Id NOT IN(SELECT Id FROM delta.Inventory)')
        db.execute('INSERT OR REPLACE INTO Records SELECT p.Id,p.Updated,p.Payload,p.Hash FROM delta.Payloads p JOIN delta.Required q ON p.Id=q.Id')
        db.executemany('INSERT OR REPLACE INTO Meta VALUES(?,?)',[('watermark',started),('dataset',dataset)]);db.commit()
        db.execute('DELETE FROM delta.Payloads');db.commit()
        report=dict(dataset=dataset,status='Complete',liveRecords=count,changedRecords=changed,removedRecords=removed,fullRecordsDownloaded=downloaded,watermark=started)
        return report
    except Exception:
        db.rollback();raise
    finally:
        if pending:pending.close()
        db.close()
