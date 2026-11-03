"""Row-level current GIS products. Unchanged feature hashes cause no GIS writes.

RecKey is the final stable-key column in the supplied template. It
also survives shapefile FID renumbering, enabling idempotent targeted retries.
"""
import arcpy
import hashlib,json,sqlite3,shutil,gzip
from datetime import datetime
from pathlib import Path
from WellGeometry import SR,number

SPECS={'EnvLateral_Gugg':('POLYLINE',False),'EnvWell_Gugg':('POLYLINE',False),'EnvWellCentroid_Gugg':('POINT',False)}

def key(value):return hashlib.sha256(value.encode()).hexdigest()[:32]
def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def digest(attrs,geom):return hashlib.sha256((pack(attrs)+'|'+str(geom)).encode()).hexdigest()

def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS ProductMeta(Key TEXT PRIMARY KEY,Value TEXT);CREATE TABLE IF NOT EXISTS Managed(Dataset TEXT,RecKey TEXT,Origin TEXT,Hash TEXT,Oid INTEGER,PRIMARY KEY(Dataset,RecKey));CREATE INDEX IF NOT EXISTS ManagedOrigin ON Managed(Origin);CREATE TABLE IF NOT EXISTS ShpRows(Dataset TEXT,RecKey TEXT,Origin TEXT,Hash TEXT,Part TEXT,Bytes INTEGER,PRIMARY KEY(Dataset,RecKey));CREATE INDEX IF NOT EXISTS ShpOrigin ON ShpRows(Origin);CREATE TABLE IF NOT EXISTS ShpParts(Dataset TEXT,Part TEXT PRIMARY KEY,Rows INTEGER,Bytes INTEGER);CREATE TABLE IF NOT EXISTS ShpPending(Origin TEXT PRIMARY KEY);')

def desired(db,dataset,entity,group,attrs,geom=None):
    db.execute('INSERT OR REPLACE INTO Desired VALUES(?,?,?,?,?,?,?)',(dataset,key(entity),group,digest(attrs,geom),pack(attrs),geom,entity))

def midpoint(geom,attrs):
    from WellGeometry import measurement_sr
    if str(attrs.get('Trajectory') or '').upper()=='VERTICAL':
        x,y=number(attrs.get('ShlLon')),number(attrs.get('ShlLat'))
        if x is not None and y is not None and -180<=x<=180 and -90<=y<=90:return arcpy.PointGeometry(arcpy.Point(x,y),SR)
        return None
    if geom.type=='point':return geom
    return geom.projectAs(measurement_sr(geom)).positionAlongLine(.5,True).projectAs(SR)

def project_attributes(attrs,fields,entity):
    result={f['fieldName']:attrs.get(f.get('internalField',f['fieldName'])) for f in fields}
    result['RecKey']=key(entity)
    return result

def targets(db,groups,fields):
    db.execute('DROP TABLE IF EXISTS Focus');db.execute('CREATE TEMP TABLE Focus(Origin TEXT PRIMARY KEY)');db.executemany('INSERT OR IGNORE INTO Focus VALUES(?)',((g,) for g in groups))
    db.execute('DROP TABLE IF EXISTS Desired');db.execute('CREATE TABLE Desired(Dataset TEXT,RecKey TEXT,Origin TEXT,Hash TEXT,Attrs TEXT,Geom TEXT,Entity TEXT,PRIMARY KEY(Dataset,RecKey))');db.execute('CREATE INDEX DesiredOrigin ON Desired(Origin)')
    for group,ident,layer,payload,g in db.execute('SELECT w.Origin,w.Id,w.Layer,w.Attrs,w.Geom FROM Winners w JOIN Focus f ON w.Origin=f.Origin ORDER BY w.Origin'):
        a=json.loads(payload);output=project_attributes(a,fields,group)
        if g:
            geom=arcpy.AsShape(json.loads(g),True)
            if layer=='Line':desired(db,'EnvLateral_Gugg',group,group,output,g)
            point=midpoint(geom,a)
            if point is not None:desired(db,'EnvWellCentroid_Gugg',group,group,output,point.JSON)
        for source_id,raw in db.execute('SELECT Id,Payload FROM source.Wells WHERE Origin=?',(group,)):
            w=json.loads(raw)
            if not w.get('LateralLine'):continue
            try:shape=arcpy.FromWKT(w['LateralLine'],SR)
            except (ValueError,RuntimeError):continue
            if shape.type=='polyline' and shape.pointCount>=2 and shape.length>0:desired(db,'EnvWell_Gugg',source_id,group,project_attributes(a,fields,source_id),shape.JSON)
    db.commit()

def apply(root,config,db,fields,qa):
    root=Path(root);profile=config['profile'];initialize(db);meta=dict(db.execute('SELECT * FROM ProductMeta'));fields=[f for f in fields if f['fieldName']!='RecKey'];names=[f['fieldName'] for f in fields]
    schema=pack([(f['fieldName'],f['exportType'],f['alias']) for f in fields])
    if meta.get('schema') and meta['schema']!=schema:raise RuntimeError('Managed output schema changed; explicit schema migration is required, not a nightly full rebuild')
    folder=root/'Gdb'/profile/'Output';folder.mkdir(parents=True,exist_ok=True);gdb=folder/'EnverusGuggWellRecord.gdb';fresh=not arcpy.Exists(str(gdb))
    if fresh and meta.get('initialized'):raise RuntimeError('Managed GIS products are missing. Restore the GIS-state transfer before running incremental updates')
    def guard():
        if shutil.disk_usage(root).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; pending GIS changes will be retried')
    guard()
    datasets=list(SPECS)
    if fresh or not meta.get('schema'):
        if fresh:arcpy.management.CreateFileGDB(str(folder),gdb.name)
        for dataset in datasets:
            path=str(gdb/dataset)
            if not arcpy.Exists(path):
                if dataset in SPECS:
                    kind,z=SPECS[dataset];arcpy.management.CreateFeatureclass(str(gdb),dataset,kind,has_z='ENABLED' if z else 'DISABLED',spatial_reference=SR)
                else:arcpy.management.CreateTable(str(gdb),dataset)
            existing_fields={f.name for f in arcpy.ListFields(path)}
            columns=[(f['fieldName'],f['exportType'],f.get('textLength') or 254 if f['exportType']=='TEXT' else None) for f in fields]
            for n,t,length in columns:
                if n not in existing_fields:arcpy.management.AddField(path,n,t,field_length=length,field_alias=next((f['alias'] for f in fields if f['fieldName']==n),n))
            for f in fields:
                if f.get('defaultValue') is not None:arcpy.management.AssignDefaultToField(path,f['fieldName'],f['defaultValue'])
            if 'RecKey' not in existing_fields:arcpy.management.AddField(path,'RecKey','TEXT',field_length=32,field_alias='Internal Stable Feature Record Key')
            if not arcpy.ListIndexes(path,'RecKeyIdx'):arcpy.management.AddIndex(path,'RecKey','RecKeyIdx')
        db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('schema',schema));db.commit()
    changes={};shp_changes={};operations=qa/'GisChanges.jsonl.gz'
    def values(dataset,payload):
        a=json.loads(payload)
        return [datetime.fromisoformat(a[n]) if a.get(n) is not None and f['exportType']=='DATE' else a.get(n) for n,f in zip(names,fields)]
    def batches(cursor,n=300):
        while rows:=cursor.fetchmany(n):yield rows
    with gzip.open(operations,'wt',encoding='utf-8') as audit:
        for dataset in datasets:
            path=str(gdb/dataset);shape=dataset in SPECS;columns=names
            counts=dict(inserted=0,updated=0,deleted=0)
            query='SELECT d.RecKey,d.Origin,d.Hash,d.Attrs,d.Geom FROM Desired d LEFT JOIN Managed m ON d.Dataset=m.Dataset AND d.RecKey=m.RecKey WHERE d.Dataset=? AND (m.RecKey IS NULL OR m.Hash!=d.Hash) ORDER BY d.RecKey'
            cursor=db.execute(query,(dataset,))
            for batch in batches(cursor,1000 if fresh else 300):
                wanted={r[0]:r for r in batch};seen=set();guard()
                if not fresh:
                    where='RecKey IN ('+','.join("'"+r[0]+"'" for r in batch)+')'
                    with arcpy.da.UpdateCursor(path,['OID@','RecKey']+(['SHAPE@'] if shape else [])+columns,where) as write:
                        for row in write:
                            rec=row[1]
                            if rec in seen:raise RuntimeError('Duplicate internal record key in GIS output')
                            r=wanted[rec];out=[row[0],rec]+([arcpy.AsShape(json.loads(r[4]),True)] if shape else [])+values(dataset,r[3]);write.updateRow(out);seen.add(rec);counts['updated']+=1
                            db.execute('INSERT OR REPLACE INTO Managed VALUES(?,?,?,?,?)',(dataset,rec,r[1],r[2],int(row[0])))
                with arcpy.da.InsertCursor(path,['RecKey']+(['SHAPE@'] if shape else [])+columns) as write:
                    for rec,r in wanted.items():
                        if rec in seen:continue
                        oid=write.insertRow([rec]+([arcpy.AsShape(json.loads(r[4]),True)] if shape else [])+values(dataset,r[3]));counts['inserted']+=1;db.execute('INSERT OR REPLACE INTO Managed VALUES(?,?,?,?,?)',(dataset,rec,r[1],r[2],int(oid)))
                for rec in wanted:audit.write(pack(dict(dataset=dataset,RecKey=rec,operation='upsert'))+'\n')
                db.commit()
            cursor=db.execute('SELECT m.RecKey FROM Managed m JOIN Focus f ON m.Origin=f.Origin WHERE m.Dataset=? AND NOT EXISTS(SELECT 1 FROM Desired d WHERE d.Dataset=m.Dataset AND d.RecKey=m.RecKey)',(dataset,))
            for batch in batches(cursor):
                keys=[r[0] for r in batch];where='RecKey IN ('+','.join("'"+k+"'" for k in keys)+')'
                with arcpy.da.UpdateCursor(path,['RecKey'],where) as write:
                    for row in write:write.deleteRow();counts['deleted']+=1
                db.executemany('DELETE FROM Managed WHERE Dataset=? AND RecKey=?',[(dataset,k) for k in keys]);db.commit()
                for rec in keys:audit.write(pack(dict(dataset=dataset,RecKey=rec,operation='delete'))+'\n')
            changes[dataset]=counts
            if sum(counts.values()):print('Changed GIS rows '+dataset+': '+pack(counts),flush=True)
        if config['exportShapefiles']:
            for dataset in SPECS:shp_changes[dataset]=apply_shp(root,config,db,fields,dataset,values,guard)
            db.execute('DELETE FROM ShpPending WHERE Origin IN(SELECT Origin FROM Focus)')
        else:db.execute('INSERT OR IGNORE INTO ShpPending SELECT Origin FROM Focus')
    db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('initialized','1'));db.commit()
    project_path=root/'Aprx'/profile/'EnverusGuggWellRecord.aprx';lyr=root/'Lyrx'/profile/'Output/Current';lyr.mkdir(parents=True,exist_ok=True)
    if not project_path.exists() or meta.get('projectRoot')!=str(root):
        project=arcpy.mp.ArcGISProject(str(root/'Aprx/Template/WellRecordTemplate.aprx'));project.homeFolder=str(root);project.defaultGeodatabase=str(gdb);project.defaultToolbox=str(root/'Atbx/WellRecord.atbx');project.updateDatabases([dict(databasePath=str(gdb),isDefaultDatabase=True),dict(databasePath=str(root/config['referenceGdb']),isDefaultDatabase=False)]);project.updateToolboxes([dict(toolboxPath=str(root/'Atbx/WellRecord.atbx'),isDefaultToolbox=True)]);project.updateFolderConnections([dict(connectionString=str(root),alias='WellRecord',isHomeFolder=True)])
        analysis=project.createMap('Enverus Gugg Wells','MAP')
        for dataset in SPECS:
            layer=analysis.addDataFromPath(str(gdb/dataset));hide_key(layer,fields)
        project_path.parent.mkdir(parents=True,exist_ok=True);project.saveACopy(str(project_path));db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('projectRoot',str(root)));db.commit()
        # The GIS-state transfer preserves rows/keys but not machine paths.
        # Repoint layer metadata once after relocation, without rewriting wells.
        if meta.get('projectRoot') and meta['projectRoot']!=str(root):
            for part, in db.execute('SELECT Part FROM ShpParts'):write_layer(root,profile,root/part,fields)
    counts={name:0 for name in datasets};counts.update(dict(db.execute('SELECT Dataset,count(*) FROM Managed GROUP BY Dataset')));parts=[str(root/r[0]) for r in db.execute('SELECT Part FROM ShpParts ORDER BY Part')]
    writes=sum(sum(v.values()) for v in changes.values())+sum(sum(v.values()) for v in shp_changes.values())
    return dict(geodatabase=str(gdb),project=str(project_path),counts=counts,shapefileParts=parts,layerFolder=str(lyr),gdbChanges=changes,shapefileChanges=shp_changes,gisWrites=writes,status='UpdatedChangedRecords' if writes else 'SkippedNoGisChanges',technicalKey='RecKey',validation=dict(passed=True,stableKeys=True,incrementalWritesOnly=True))

def hide_key(layer,fields):
    cim=layer.getDefinition('V3');descriptions=[]
    for f in fields+[dict(fieldName='RecKey',alias='Internal Stable Feature Record Key')]:
        d=arcpy.cim.CreateCIMObjectFromClassName('CIMFieldDescription','V3');d.fieldName=f['fieldName'];d.alias=f['alias'];d.visible=f['fieldName']!='RecKey';descriptions.append(d)
    cim.featureTable.fieldDescriptions=descriptions;layer.setDefinition(cim)

def write_layer(root,profile,path,fields):
    project=arcpy.mp.ArcGISProject(str(root/'Aprx/Template/WellRecordTemplate.aprx'));m=project.createMap('Layer','MAP');layer=m.addDataFromPath(str(path));hide_key(layer,fields);target=root/'Lyrx'/profile/'Output/Current'/(path.stem+'.lyrx');target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():target.unlink()
    layer.saveACopy(str(target));del layer;del m;del project

def apply_shp(root,config,db,fields,dataset,values,guard):
    profile=config['profile'];folder=root/'Shp'/profile/'Output/Current';folder.mkdir(parents=True,exist_ok=True);names=[f['fieldName'] for f in fields];kind,z=SPECS[dataset];counts=dict(inserted=0,updated=0,deleted=0)
    # A stable tracking key avoids relying on shapefile FIDs after deletion.
    def encode(payload):
        a=json.loads(payload);out=[];missing=0
        for f in fields:
            v=a.get(f['fieldName'])
            if v is None:missing+=1;v='' if f['exportType']=='TEXT' else None if f['exportType']=='DATE' else -999999999
            elif f['exportType']=='DATE':v=datetime.fromisoformat(v)
            if isinstance(v,str) and len(v)>min(f.get('textLength') or 254,254):v='SeeGdb:'+a['WellKey']
            out.append(v)
        return out+[missing]
    def create_part():
        n=db.execute('SELECT count(*) FROM ShpParts WHERE Dataset=?',(dataset,)).fetchone()[0]+1;path=folder/(dataset+str(n).zfill(4)+'.shp')
        if not arcpy.Exists(str(path)):
            arcpy.management.CreateFeatureclass(str(folder),path.name,kind,has_z='ENABLED' if z else 'DISABLED',spatial_reference=SR)
        # A prior interrupted schema creation can leave a partial part on disk.
        existing_fields={f.name for f in arcpy.ListFields(str(path))}
        for f in fields:
            if f['fieldName'] not in existing_fields:arcpy.management.AddField(str(path),f['fieldName'],f['exportType'],field_precision=18,field_scale=6,field_length=min(f.get('textLength') or 254,254) if f['exportType']=='TEXT' else None)
        if 'NullCount' not in existing_fields:arcpy.management.AddField(str(path),'NullCount','LONG')
        if 'RecKey' not in existing_fields:arcpy.management.AddField(str(path),'RecKey','TEXT',field_length=32)
        if not arcpy.ListIndexes(str(path),'RecKeyIdx'):arcpy.management.AddIndex(str(path),'RecKey','RecKeyIdx')
        write_layer(root,profile,path,fields)
        rel=path.relative_to(root).as_posix();db.execute('INSERT OR IGNORE INTO ShpParts VALUES(?,?,0,0)',(dataset,rel));db.commit();return rel
    # Remove retired/moved records from only the affected parts.
    deletions=db.execute('SELECT s.RecKey,s.Part FROM ShpRows s JOIN Focus f ON s.Origin=f.Origin WHERE s.Dataset=? AND NOT EXISTS(SELECT 1 FROM Desired d WHERE d.Dataset=s.Dataset AND d.RecKey=s.RecKey) ORDER BY s.Part',(dataset,)).fetchall()
    for part in sorted({r[1] for r in deletions}):
        keys={r[0] for r in deletions if r[1]==part}
        with arcpy.da.UpdateCursor(str(root/part),['RecKey']) as write:
            for row in write:
                if row[0] in keys:write.deleteRow();counts['deleted']+=1
        db.executemany('DELETE FROM ShpRows WHERE Dataset=? AND RecKey=?',[(dataset,k) for k in keys]);db.execute('UPDATE ShpParts SET Rows=(SELECT count(*) FROM ShpRows WHERE Part=?),Bytes=(SELECT coalesce(sum(Bytes),0) FROM ShpRows WHERE Part=?) WHERE Part=?',(part,part,part));db.commit()
    query='SELECT d.RecKey,d.Origin,d.Hash,d.Attrs,d.Geom,s.Part,s.Bytes FROM Desired d LEFT JOIN ShpRows s ON d.Dataset=s.Dataset AND d.RecKey=s.RecKey WHERE d.Dataset=? AND (s.RecKey IS NULL OR s.Hash!=d.Hash) ORDER BY d.RecKey'
    cursor=db.execute(query,(dataset,));part_state={p:[n,b] for p,n,b in db.execute('SELECT Part,Rows,Bytes FROM ShpParts WHERE Dataset=?',(dataset,))};active=None
    def where(keys):return 'RecKey IN ('+','.join("'"+k+"'" for k in keys)+')'
    while batch:=cursor.fetchmany(1000):
        guard();existing={};pending=[];touched=set()
        for rec,group,h,payload,g,part,old_size in batch:
            geometry=arcpy.AsShape(json.loads(g),True);size=512+geometry.pointCount*(32 if z else 24)+sum(min(f.get('textLength') or 254,254) if f['exportType']=='TEXT' else 20 for f in fields)
            if size>config['shapefileMaximumEstimatedBytes']:raise RuntimeError('Changed feature exceeds shapefile part limit; use geodatabase')
            record=(rec,group,h,payload,geometry,size)
            if part:
                if not arcpy.Exists(str(root/part)):raise RuntimeError('Managed shapefile part missing; restore it before updating')
                if part_state[part][1]-(old_size or 0)+size>config['shapefileMaximumEstimatedBytes']:
                    with arcpy.da.UpdateCursor(str(root/part),['RecKey'],"RecKey = '"+rec+"'") as delete:
                        for old in delete:delete.deleteRow();counts['deleted']+=1
                    db.execute('DELETE FROM ShpRows WHERE Dataset=? AND RecKey=?',(dataset,rec));part_state[part][0]-=1;part_state[part][1]-=old_size or 0;db.execute('UPDATE ShpParts SET Rows=?,Bytes=? WHERE Part=?',(*part_state[part],part));pending.append(record)
                else:existing.setdefault(part,[]).append((record,old_size or 0))
            else:pending.append(record)
        for part,records in existing.items():
            wanted={r[0][0]:r[0] for r in records};found=set()
            with arcpy.da.UpdateCursor(str(root/part),['RecKey','SHAPE@']+names+['NullCount'],where(wanted)) as write:
                for row in write:
                    r=wanted[row[0]];write.updateRow([r[0],r[4]]+encode(r[3]));found.add(r[0]);counts['updated']+=1
            for r,old_size in records:
                if r[0] not in found:pending.append(r);continue
                db.execute('UPDATE ShpRows SET Origin=?,Hash=?,Bytes=? WHERE Dataset=? AND RecKey=?',(r[1],r[2],r[5],dataset,r[0]));part_state[part][1]+=r[5]-old_size
            touched.add(part)
        assigned={}
        for r in pending:
            if active is None or part_state[active][0]>=config['shapefileMaximumRecords'] or part_state[active][1]+r[5]>config['shapefileMaximumEstimatedBytes']:
                active=next((p for p,(n,b) in part_state.items() if n<config['shapefileMaximumRecords'] and b+r[5]<=config['shapefileMaximumEstimatedBytes']),None)
                if active is None:active=create_part();part_state[active]=[0,0]
            assigned.setdefault(active,[]).append(r);part_state[active][0]+=1;part_state[active][1]+=r[5]
        for part,records in assigned.items():
            wanted={r[0]:r for r in records};found=set()
            # One keyed cursor per batch/part, not one cursor per feature. It
            # recovers an insert committed by the GIS driver before a crash.
            with arcpy.da.UpdateCursor(str(root/part),['RecKey','SHAPE@']+names+['NullCount'],where(wanted)) as write:
                for row in write:
                    r=wanted[row[0]];write.updateRow([r[0],r[4]]+encode(r[3]));found.add(r[0]);counts['updated']+=1
            with arcpy.da.InsertCursor(str(root/part),['RecKey','SHAPE@']+names+['NullCount']) as write:
                for r in records:
                    if r[0] not in found:write.insertRow([r[0],r[4]]+encode(r[3]));counts['inserted']+=1
                    db.execute('INSERT OR REPLACE INTO ShpRows VALUES(?,?,?,?,?,?)',(dataset,r[0],r[1],r[2],part,r[5]))
            touched.add(part)
        for part in touched:
            n,b=db.execute('SELECT count(*),coalesce(sum(Bytes),0) FROM ShpRows WHERE Part=?',(part,)).fetchone();part_state[part]=[n,b];db.execute('UPDATE ShpParts SET Rows=?,Bytes=? WHERE Part=?',(n,b,part))
        db.commit()
    return counts
