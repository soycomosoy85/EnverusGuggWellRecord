"""Changed-row GDB sink for the independent context caches."""
import hashlib,json,re,sqlite3,shutil
from datetime import datetime
from pathlib import Path
import arcpy
from WellGeometry import SR
from ContextSync import packed

def field_map(names,id_field,hints,samples):
    used={'reckey','srcid'};result=[]
    for name in sorted(names):
        if name.lower().startswith('geom'):continue
        base=re.sub('[^A-Za-z0-9_]','',name)
        if not base or not base[0].isalpha():base='F'+base
        short=base[:10]
        if short.lower() in used:short=base[:5]+hashlib.sha256(name.encode()).hexdigest()[:5]
        if short.lower() in used:raise RuntimeError('Context field mapping collision')
        used.add(short.lower());kind=hints.get(name,{}).get('type')
        values=[row[name] for row in samples if row.get(name) is not None]
        if name==id_field or name.lower().endswith('id'):kind='TEXT'
        elif name.lower().startswith('date') or name.lower().endswith('date'):kind='DATE'
        elif kind not in ['TEXT','DOUBLE','LONG','SHORT','DATE']:
            kind='DOUBLE' if values and all(isinstance(v,(int,float)) and not isinstance(v,bool) for v in values) else 'SHORT' if values and all(isinstance(v,bool) for v in values) else 'TEXT'
        result.append(dict(source=name,fieldName=short,alias=name,exportType=kind,textLength=65535 if kind=='TEXT' else None))
    return result

def encode(row,fields):
    values=[]
    for f in fields:
        value=row.get(f['source']);kind=f['exportType']
        if kind!='TEXT' and isinstance(value,str) and not value.strip():value=None
        if value is not None:
            if kind=='TEXT':
                value=packed(value) if isinstance(value,(dict,list)) else str(value)
                if len(value)>65535:raise RuntimeError('Context text exceeds configured GDB width; full value remains in source cache')
            elif kind=='DATE':value=datetime.fromisoformat(str(value).replace('Z','+00:00')).replace(hour=0,minute=0,second=0,microsecond=0,tzinfo=None)
            elif kind=='SHORT' and isinstance(value,bool):value=int(value)
            elif kind in ['DOUBLE','LONG','SHORT']:value=float(value) if kind=='DOUBLE' else int(value)
        values.append(value)
    return values

def geometry(row,layer):
    fields=layer['geometryFields']
    if len(fields)==2:
        y,x=row.get(fields[0]),row.get(fields[1])
        if x is None or y is None:return None
        x,y=float(x),float(y)
        if not (-180<=x<=180 and -90<=y<=90):return None
        return arcpy.PointGeometry(arcpy.Point(x,y),SR)
    wkt=row.get(fields[0])
    if not wkt:return None
    shape=arcpy.FromWKT(wkt,SR)
    if shape.type.upper()!=layer['geometryType']:raise RuntimeError('Unexpected context geometry type')
    return shape if shape.pointCount else None

def build(root,path,layer,config):
    root=Path(root);db=sqlite3.connect(path,timeout=180)
    try:
        meta=dict(db.execute('SELECT * FROM Meta'))
        if not meta.get('watermark'):raise RuntimeError('Context source baseline must complete before GIS build')
        folder=root/'Gdb'/config['profile']/'Output';folder.mkdir(parents=True,exist_ok=True);gdb=folder/config['outputGeodatabase']
        if not arcpy.Exists(str(gdb)):arcpy.management.CreateFileGDB(str(folder),gdb.name)
        fc=str(gdb/layer['featureClass']);fresh=not arcpy.Exists(fc)
        if fresh and db.execute('SELECT count(*) FROM GisState').fetchone()[0]:raise RuntimeError('Managed context layer missing; restore it or explicitly reset its GIS state')
        fields_path=root/'Json'/config['profile']/'Context'/(layer['dataset']+'Fields.json');fields_path.parent.mkdir(parents=True,exist_ok=True)
        if fields_path.exists():fields=json.loads(fields_path.read_text())
        else:
            docs=json.loads((root/'Json/ApiSchema'/(layer['dataset']+'Docs.json')).read_text());hints=json.loads((root/'Json/Config/ContextFieldTypes.json').read_text()).get(layer['dataset'],{})
            samples=[json.loads(r[0]) for r in db.execute('SELECT Payload FROM Records LIMIT 1000')]
            fields=field_map({r['name'] for r in docs}|{k for row in samples for k in row},layer['idField'],hints,samples);fields_path.write_text(json.dumps(fields,indent=2))
        if fresh:arcpy.management.CreateFeatureclass(str(gdb),layer['featureClass'],layer['geometryType'],spatial_reference=SR)
        existing={f.name for f in arcpy.ListFields(fc)}
        for f in fields:
            if f['fieldName'] not in existing:arcpy.management.AddField(fc,f['fieldName'],f['exportType'],field_length=f['textLength'],field_alias=f['alias'])
        for name,length in [('SrcId',254),('RecKey',32)]:
            if name not in existing:arcpy.management.AddField(fc,name,'TEXT',field_length=length)
        if not arcpy.ListIndexes(fc,'RecKeyIdx'):arcpy.management.AddIndex(fc,'RecKey','RecKeyIdx')
        if fresh:db.execute('INSERT OR IGNORE INTO Dirty SELECT Id FROM Records');db.commit()
        changes=dict(inserted=0,updated=0,deleted=0,missingGeometry=0);columns=[f['fieldName'] for f in fields]
        while batch:=db.execute('SELECT d.Id,r.Payload,s.Hash FROM Dirty d LEFT JOIN Records r ON d.Id=r.Id LEFT JOIN GisState s ON d.Id=s.Id ORDER BY d.Id LIMIT 500').fetchall():
            if shutil.disk_usage(root).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; context GIS dirty queue remains')
            desired={};retired={};ack=[]
            for ident,payload,prior_hash in batch:
                rec=hashlib.sha256((layer['dataset']+'|'+ident).encode()).hexdigest()[:32];ack.append((ident,))
                if payload is None:retired[rec]=ident;continue
                row=json.loads(payload)
                try:shape=geometry(row,layer)
                except (RuntimeError,ValueError,TypeError):shape=None
                if shape is None:retired[rec]=ident;changes['missingGeometry']+=1;continue
                vals=encode(row,fields);digest=hashlib.sha256(packed([[v.isoformat() if isinstance(v,datetime) else v for v in vals],shape.JSON]).encode()).hexdigest()
                if digest!=prior_hash:desired[rec]=(ident,digest,shape,vals)
            keys=set(desired)|set(retired);found=set()
            if keys:
                where='RecKey IN ('+','.join("'"+k+"'" for k in keys)+')'
                with arcpy.da.UpdateCursor(fc,['OID@','RecKey','SrcId','SHAPE@']+columns,where) as write:
                    for row in write:
                        rec=row[1]
                        if rec in retired:write.deleteRow();changes['deleted']+=1;continue
                        ident,digest,shape,vals=desired[rec];write.updateRow([row[0],rec,ident,shape]+vals);found.add(rec);changes['updated']+=1;db.execute('INSERT OR REPLACE INTO GisState VALUES(?,?,?)',(ident,digest,int(row[0])))
                with arcpy.da.InsertCursor(fc,['RecKey','SrcId','SHAPE@']+columns) as write:
                    for rec,(ident,digest,shape,vals) in desired.items():
                        if rec in found:continue
                        oid=write.insertRow([rec,ident,shape]+vals);db.execute('INSERT OR REPLACE INTO GisState VALUES(?,?,?)',(ident,digest,int(oid)));changes['inserted']+=1
            db.executemany('DELETE FROM GisState WHERE Id=?',[(ident,) for ident in retired.values()]);db.executemany('DELETE FROM Dirty WHERE Id=?',ack);db.commit()
        return dict(dataset=layer['dataset'],featureClass=fc,features=db.execute('SELECT count(*) FROM GisState').fetchone()[0],changes=changes,gisWrites=sum(changes[k] for k in ['inserted','updated','deleted']),fieldDictionary=str(fields_path))
    finally:db.close()
