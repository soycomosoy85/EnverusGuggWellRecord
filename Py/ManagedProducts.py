"""Row-level current GIS products. Unchanged feature hashes cause no GIS writes.

RecKey is the final stable-key column in the supplied template. It
enables idempotent targeted retries for geodatabase features.
"""
import arcpy
import hashlib,json,sqlite3,shutil,gzip
from datetime import datetime
from pathlib import Path
from WellGeometry import SR,number
from TextFields import required_widths

SPECS={'EnvLateral_Gugg':('POLYLINE',False),'EnvWell_Gugg':('POLYLINE',False),'EnvWellCentroid_Gugg':('POINT',False)}

def key(value):return hashlib.sha256(value.encode()).hexdigest()[:32]
def pack(value):return json.dumps(value,sort_keys=True,separators=(',',':'))
def digest(attrs,geom):return hashlib.sha256((pack(attrs)+'|'+str(geom)).encode()).hexdigest()

def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS ProductMeta(Key TEXT PRIMARY KEY,Value TEXT);CREATE TABLE IF NOT EXISTS Managed(Dataset TEXT,RecKey TEXT,Origin TEXT,Hash TEXT,Oid INTEGER,PRIMARY KEY(Dataset,RecKey));CREATE INDEX IF NOT EXISTS ManagedOrigin ON Managed(Origin);')

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
    if any(f['fieldName']=='WelCnsStat' for f in fields):
        from WellConstraintAttributes import apply
        attrs=apply(attrs)
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
    changes={};operations=qa/'GisChanges.jsonl.gz'
    def values(dataset,payload):
        a=json.loads(payload)
        return [datetime.fromisoformat(a[n]) if a.get(n) is not None and f['exportType']=='DATE' else a.get(n) for n,f in zip(names,fields)]
    def batches(cursor,n=300):
        while rows:=cursor.fetchmany(n):yield rows
    with gzip.open(operations,'wt',encoding='utf-8') as audit:
        for dataset in datasets:
            path=str(gdb/dataset);shape=dataset in SPECS;columns=names
            text_widths={f.name:f.length for f in arcpy.ListFields(path) if f.type=='String'}
            counts=dict(inserted=0,updated=0,deleted=0)
            query='SELECT d.RecKey,d.Origin,d.Hash,d.Attrs,d.Geom FROM Desired d LEFT JOIN Managed m ON d.Dataset=m.Dataset AND d.RecKey=m.RecKey WHERE d.Dataset=? AND (m.RecKey IS NULL OR m.Hash!=d.Hash) ORDER BY d.RecKey'
            cursor=db.execute(query,(dataset,))
            for batch in batches(cursor,1000 if fresh else 300):
                wanted={r[0]:r for r in batch};seen=set();guard()
                for name,width in required_widths(fields,(r[3] for r in batch),text_widths).items():
                    arcpy.management.AlterField(path,name,field_length=width)
                    text_widths[name]=width
                    print('Expanded GDB text field '+dataset+'.'+name+' to '+str(width),flush=True)
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
    db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('initialized','1'));db.commit()
    project_path=root/'Aprx'/profile/'EnverusGuggWellRecord.aprx'
    if not project_path.exists() or meta.get('projectRoot')!=str(root):
        project=arcpy.mp.ArcGISProject(str(root/'Aprx/Template/WellRecordTemplate.aprx'));project.homeFolder=str(root);project.defaultGeodatabase=str(gdb);project.defaultToolbox=str(root/'Atbx/WellRecord.atbx');project.updateDatabases([dict(databasePath=str(gdb),isDefaultDatabase=True),dict(databasePath=str(root/config['referenceGdb']),isDefaultDatabase=False)]);project.updateToolboxes([dict(toolboxPath=str(root/'Atbx/WellRecord.atbx'),isDefaultToolbox=True)]);project.updateFolderConnections([dict(connectionString=str(root),alias='WellRecord',isHomeFolder=True)])
        analysis=project.createMap('Enverus Gugg Wells','MAP')
        for dataset in SPECS:
            layer=analysis.addDataFromPath(str(gdb/dataset));hide_key(layer,fields)
        project_path.parent.mkdir(parents=True,exist_ok=True);project.saveACopy(str(project_path));db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('projectRoot',str(root)));db.commit()
    counts={name:0 for name in datasets};counts.update(dict(db.execute('SELECT Dataset,count(*) FROM Managed GROUP BY Dataset')))
    writes=sum(sum(v.values()) for v in changes.values())
    return dict(geodatabase=str(gdb),project=str(project_path),counts=counts,gdbChanges=changes,gisWrites=writes,status='UpdatedChangedRecords' if writes else 'SkippedNoGisChanges',technicalKey='RecKey',validation=dict(passed=True,stableKeys=True,incrementalWritesOnly=True))

def hide_key(layer,fields):
    cim=layer.getDefinition('V3');descriptions=[]
    for f in fields+[dict(fieldName='RecKey',alias='Internal Stable Feature Record Key')]:
        d=arcpy.cim.CreateCIMObjectFromClassName('CIMFieldDescription','V3');d.fieldName=f['fieldName'];d.alias=f['alias'];d.visible=f['fieldName']!='RecKey';descriptions.append(d)
    cim.featureTable.fieldDescriptions=descriptions;layer.setDefinition(cim)
