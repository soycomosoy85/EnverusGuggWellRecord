"""Incrementally recompute cached geometries; export complete country-safe products."""
import arcpy
import hashlib,itertools,json,sqlite3,shutil
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from Identity import record_id,origin,survey_key,normalize
from WellGeometry import SR,FT_PER_M,number,measurement_sr,survey_lateral,trim_fallback
from GuggEnrichment import References
from Selection import choose
from WellRecordCalculations import calculate_spacing

def fingerprint(folder):
    h=hashlib.sha256()
    for p in sorted(Path(folder).rglob('*')):
        if p.is_file() and '__pycache__' not in p.parts and not p.name.lower().endswith(('.lock','.pyc')):
            h.update(p.name.encode());h.update(p.read_bytes())
    return h.hexdigest()
def compute(well,ident,headers,stations,schema,refs,config):
    a={};flags=set();geom=geom3=None
    if well.get('ENVWellStatus') is None:flags.add('UnknownWellStatus')
    for f in schema['fields']:
        v=well.get(f['directApiField'])
        if f['exportType']=='DATE' and v:
            try:
                if isinstance(v,str) and len(v)==7:v=v+'-01';flags.add('SourceMonthDate')
                v=datetime.fromisoformat(v.replace('Z','+00:00')).date().isoformat()
            except (ValueError,TypeError):v=None;flags.add('InvalidDate')
        elif f['exportType']=='TEXT':v=None if v is None else str(v)
        elif f['exportType'] not in ['DATE','TEXT']:v=number(v)
        a[f['fieldName']]=v
    a.update(WellKey=hashlib.sha256(ident.encode()).hexdigest()[:32],EnvWellId=str(well.get('WellID')) if well.get('WellID') is not None else None,Api12=survey_key(well),WellConstr='N')
    refs.nomenclature(well,a,flags)
    source_kinds={str(h.get('CoordinateSource') or '').upper() for h in headers}
    if not a['Api12']:flags.add('MissingSurveyLookup')
    # Choose measurement SR from the actual path when possible, including Alaska.
    sample=next((r for r in stations if number(r.get('Longitude')) is not None and number(r.get('Latitude')) is not None),None)
    x=number((sample or {}).get('Longitude')) if sample else number(well.get('Longitude'))
    y=number((sample or {}).get('Latitude')) if sample else number(well.get('Latitude'))
    seed=arcpy.PointGeometry(arcpy.Point(x,y),SR) if x is not None and y is not None and -180<=x<=180 and -90<=y<=90 else None
    sr=measurement_sr(seed) if seed else None
    for kind in ['ACTUAL','PLANNED']:
        if kind=='PLANNED' and well.get('StateProvince') not in config['plannedSurveyStates']:continue
        if kind not in source_kinds or sr is None:continue
        local=[];result=survey_lateral(stations,well,local,sr,source_kind=kind);flags.update(local)
        if result:
            geom,geom3,method,top,bottom=result;a.update(GeomSrc='ActualSurvey' if kind=='ACTUAL' else 'PlannedSurvey',SurveySrc=kind,TrimMethod=method.replace('Pilot','Estimate'),TrimTopFt=top,TrimBotFt=bottom)
            if kind=='PLANNED':flags.add('PlannedGeometry')
            break
    if geom is None and well.get('LateralLine'):
        try:
            raw=arcpy.FromWKT(well['LateralLine'],SR);sr=measurement_sr(raw)
            if raw.projectAs(sr).length>.01:
                # Explicit XY only: source fallback elevation is not known.
                raw=arcpy.Polyline(arcpy.Array([arcpy.Array([arcpy.Point(p.X,p.Y) for p in part if p]) for part in raw]),SR)
                geom,method,details=trim_fallback(raw,a,sr);a.update(GeomSrc='EnverusLateral',TrimMethod=method,SurveySrc='|'.join(sorted(source_kinds)) or 'NONE')
                flags.add('FallbackZUnavailable')
                if method=='ToeBackLengthEstimate':flags.add('ToeBackXYEstimate')
                else:flags.update(['AllocationReview',method])
        except (ValueError,RuntimeError,TypeError):flags.add('InvalidFallbackGeometry')
    if geom is not None:
        refs.assign(geom,a,flags,sr);layer='Line'
    else:
        flags.add('NoUsableLateral');a.update(GeomSrc='PointOnly' if seed else 'NoLocation',SurveySrc='|'.join(sorted(source_kinds)) or 'NONE',TrimMethod='NoLateral')
        # Point proxy must be the source SHL, not the first survey station.
        x,y=number(well.get('Longitude')),number(well.get('Latitude'))
        geom=arcpy.PointGeometry(arcpy.Point(x,y),SR) if x is not None and y is not None and -180<=x<=180 and -90<=y<=90 else None
        layer='Point' if geom else 'NoLocation'
        if not geom:a['GeomSrc']='NoLocation';flags.add('NoPointCoordinates')
        if geom is not None and hasattr(refs,'assign_gis_basin'):refs.assign_gis_basin(geom,a,flags,sr)
        calc=calculate_spacing(None);a.update(Spacing_Ft=None,DA_Ft=None)
    a['QaStatus']='|'.join(sorted(flags)) or 'OK'
    return layer,a,geom.JSON if geom else None,geom3.JSON if geom3 else None

def build(root,config,cache_path):
    root=Path(root);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');profile=config['profile'];qa=root/'Json'/profile/'Output'/'Qa'/stamp;qa.mkdir(parents=True)
    if shutil.disk_usage(root).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached before GIS build')
    from SourceCache import initialize as init_source
    from ManagedProducts import initialize as init_products,targets,apply,pack
    writable=sqlite3.connect(cache_path);init_source(writable);writable.commit();writable.close()
    src=sqlite3.connect('file:'+Path(cache_path).as_posix()+'?mode=ro',uri=True)
    processed=root/'Sqlite'/profile/'Cache'/'Processed.sqlite';db=sqlite3.connect(processed)
    db.executescript('CREATE TABLE IF NOT EXISTS Results(Id TEXT PRIMARY KEY,Origin TEXT,Signature TEXT,Layer TEXT,Attrs TEXT,Geom TEXT,Geom3 TEXT);CREATE INDEX IF NOT EXISTS ResultOrigin ON Results(Origin);CREATE TABLE IF NOT EXISTS Winners(Origin TEXT PRIMARY KEY,Id TEXT UNIQUE,Layer TEXT,Attrs TEXT,Geom TEXT,Geom3 TEXT);CREATE TABLE IF NOT EXISTS WinnerStats(Origin TEXT PRIMARY KEY,Kind TEXT);')
    init_products(db);meta=dict(db.execute('SELECT * FROM ProductMeta'));db.execute('ATTACH DATABASE ? AS source',(str(cache_path),))
    schema=json.loads((root/'Json/Config/HeaderSchema.json').read_text());fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
    if any(f['fieldName']=='WelCnsStat' for f in fields):
        from WellConstraintAttributes import configure
        from UpgradeWellAttributes import upgrade_if_needed
        configure(root);upgrade_if_needed(root,config,db,fields)
        meta=dict(db.execute('SELECT * FROM ProductMeta'))
    reference=root/config['referenceGdb'];refs=None
    logic_files=['Identity.py','WellGeometry.py','Selection.py','GuggEnrichment.py','WellRecordCalculations.py','BuildProducts.py','ManagedProducts.py']
    logic_hash=hashlib.sha256(''.join((root/'Py'/n).read_text(encoding='utf-8-sig') for n in logic_files).encode()).hexdigest()
    # A reviewed writer-only repair must not invalidate completed well geometry.
    # Exact hashes ensure any subsequent computation edit still invalidates it.
    from ExportCompatibility import compatible_logic_hash,compatible_rules_hash,geometry_fields
    logic_hash=compatible_logic_hash(logic_hash)
    geometry_config={n:config.get(n) for n in ['plannedSurveyStates','measurement']}
    rules_hash=hashlib.sha256((fingerprint(reference)+logic_hash+json.dumps(geometry_config,sort_keys=True)+arcpy.GetInstallInfo()['Version']+json.dumps(geometry_fields(fields))+json.dumps(schema)).encode()).hexdigest()
    rules_hash=compatible_rules_hash(rules_hash)
    db.execute('CREATE TEMP TABLE BuildFocus(Origin TEXT PRIMARY KEY)')
    full_initialization=not meta.get('initialized') or meta.get('rulesHash')!=rules_hash
    if full_initialization:
        db.execute('INSERT OR IGNORE INTO BuildFocus SELECT DISTINCT Origin FROM source.Wells');db.execute('INSERT OR IGNORE INTO BuildFocus SELECT Origin FROM Winners')
    else:db.execute('INSERT OR IGNORE INTO BuildFocus SELECT Origin FROM source.DirtyOrigins')
    focus_count=db.execute('SELECT count(*) FROM BuildFocus').fetchone()[0]
    def finish(report):
        report.update(run=stamp,qaFolder=str(qa),sourceCache=str(cache_path),referenceFingerprint=fingerprint(reference))
        (qa/'BuildReport.json').write_text(json.dumps(report,indent=2));(root/'Json/Config/LatestPortableOutput.json').write_text(json.dumps(report,indent=2));db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('lastReport',pack(report)));db.commit()
        if refs:refs.projected.cache_clear()
        src.close();db.close();return report
    if not focus_count and meta.get('projectRoot')==str(root) and meta.get('lastReport'):
        report=json.loads(meta['lastReport'])
        if not Path(report['geodatabase']).exists():raise RuntimeError('Managed GIS products are missing; restore them before incremental updates')
        report.update(status='SkippedNoChanges',gisWrites=0,processingCounts=dict(Recomputed=0,Reused=0),affectedOrigins=0,gdbChanges={});return finish(report)
    counts=Counter();last_api=None;headers=[];stations=[];seen=0
    query='SELECT w.Id,w.Api,w.Payload,b.Version FROM source.Wells w JOIN BuildFocus f ON w.Origin=f.Origin LEFT JOIN source.BoreVersions b ON w.Api=b.Api ORDER BY w.Api,w.Id'
    for ident,bore,payload,version in db.execute(query):
        signature=hashlib.sha256((payload+str(version)+rules_hash).encode()).hexdigest();old=db.execute('SELECT Signature FROM Results WHERE Id=?',(ident,)).fetchone()
        if old and old[0]==signature:counts['Reused']+=1;continue
        if refs is None:refs=References(reference)
        well=json.loads(payload)
        if bore!=last_api:
            last_api=bore;headers=[json.loads(p) for p, in src.execute('SELECT Payload FROM Headers WHERE Api=?',(bore,))];stations=[json.loads(p) for p, in src.execute('SELECT Payload FROM Stations WHERE Api=? ORDER BY Seq',(bore,))]
        layer,a,g,g3=compute(well,ident,headers,stations,schema,refs,config)
        db.execute('INSERT OR REPLACE INTO Results VALUES(?,?,?,?,?,?,?)',(ident,origin(well),signature,layer,json.dumps(a,separators=(',',':')),g,g3));counts['Recomputed']+=1;seen+=1
        if seen%1000==0:
            db.commit()
            if shutil.disk_usage(root).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached during local processing')
            print('Local geometries recomputed '+str(seen),flush=True)
    db.commit();db.execute('DELETE FROM Results WHERE Origin IN(SELECT Origin FROM BuildFocus) AND Id NOT IN(SELECT Id FROM source.Wells)');db.commit()
    chosen_sources=Counter(json.loads(meta.get('sourceCounts','{}')));has_stats=bool(meta.get('sourceCounts'));db.execute('CREATE TEMP TABLE NewStats(Origin TEXT PRIMARY KEY,Kind TEXT)')
    for group, in db.execute('SELECT Origin FROM BuildFocus ORDER BY Origin'):
        prior=db.execute('SELECT Kind FROM WinnerStats WHERE Origin=?',(group,)).fetchone()
        if prior and has_stats:chosen_sources[prior[0]]-=1
        candidates=[dict(key=r[0],layer=r[1],a=json.loads(r[2]),payload=r[2],g=r[3],g3=r[4]) for r in db.execute('SELECT Id,Layer,Attrs,Geom,Geom3 FROM Results WHERE Origin=? ORDER BY Id',(group,))]
        if not candidates:db.execute('DELETE FROM Winners WHERE Origin=?',(group,));continue
        winner,rank=choose(candidates);a=winner['a'];chosen_sources[a['GeomSrc']]+=1;db.execute('INSERT INTO NewStats VALUES(?,?)',(group,a['GeomSrc']))
        db.execute('INSERT OR REPLACE INTO Winners VALUES(?,?,?,?,?,?)',(group,winner['key'],winner['layer'],winner['payload'],winner['g'],winner['g3']))
    db.commit()
    targets(db,(r[0] for r in db.execute('SELECT Origin FROM BuildFocus')),fields)
    report=apply(root,config,db,fields,qa)
    db.execute('DELETE FROM WinnerStats WHERE Origin IN(SELECT Origin FROM BuildFocus)');db.execute('INSERT INTO WinnerStats SELECT * FROM NewStats');db.executemany('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',[('rulesHash',rules_hash),('sourceCounts',pack(dict(chosen_sources)))]);db.commit()
    # The queue is acknowledged only after every affected GIS product succeeds.
    ack=sqlite3.connect(cache_path)
    try:
        ack.executemany('DELETE FROM DirtyOrigins WHERE Origin=?',db.execute('SELECT Origin FROM BuildFocus'));ack.commit()
    finally:ack.close()
    report.update(processingCounts=dict(counts),selectedGeometrySources={k:v for k,v in chosen_sources.items() if v},affectedOrigins=focus_count,origins=sum(chosen_sources.values()),includedSourceRecords=src.execute('SELECT count(*) FROM Wells').fetchone()[0],noLocationMapSources=0,noLocationOrigins=chosen_sources.get('NoLocation',0))
    return finish(report)
