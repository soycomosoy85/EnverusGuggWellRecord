"""Final cached-attribute surface-hole layer; no API, survey, or Gugg recalculation."""
import json,sqlite3
from pathlib import Path
import arcpy
from WellGeometry import SR,number
import ManagedProducts as managed

NAME='EnvSH_Gugg'

def ensure_defaults(path,fields):
    wanted=[f for f in fields if f.get('defaultValue') is not None]
    if not wanted:return
    values=next(iter(arcpy.da.ListSubtypes(path).values()))['FieldValues']
    for f in wanted:
        if values[f['fieldName']][0]!=f['defaultValue']:arcpy.management.AssignDefaultToField(path,f['fieldName'],f['defaultValue'])

def ensure_project(report,fields):
    project=arcpy.mp.ArcGISProject(report['project'])
    if not any(layer.name==NAME for m in project.listMaps() for layer in m.listLayers()):
        m=project.listMaps()[0];layer=m.addDataFromPath(str(Path(report['geodatabase'])/NAME));managed.hide_key(layer,[f for f in fields if f['fieldName']!='RecKey']);project.save()
    del project

def initialize(db):
    db.executescript('CREATE TABLE IF NOT EXISTS SurfacePending(Origin TEXT PRIMARY KEY);CREATE TABLE IF NOT EXISTS SurfaceMeta(Key TEXT PRIMARY KEY,Value TEXT);')

def capture_pending(root,config,cache):
    path=Path(root)/'Sqlite'/config['profile']/'Cache/Processed.sqlite';path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);source=sqlite3.connect('file:'+Path(cache).as_posix()+'?mode=ro',uri=True)
    try:
        initialize(db)
        if source.execute("SELECT 1 FROM sqlite_master WHERE name='DirtyOrigins'").fetchone():db.executemany('INSERT OR IGNORE INTO SurfacePending VALUES(?)',source.execute('SELECT Origin FROM DirtyOrigins'))
        db.commit()
    finally:source.close();db.close()

def sync_surface(root,config,report):
    root=Path(root);db=sqlite3.connect(root/'Sqlite'/config['profile']/'Cache/Processed.sqlite')
    try:
        initialize(db);meta=dict(db.execute('SELECT * FROM SurfaceMeta'));pending=db.execute('SELECT count(*) FROM SurfacePending').fetchone()[0]
        # First population reads existing selected attributes only. Broader main
        # output changes also propagate their selected attributes, without
        # recomputing a single directional-survey or polygon assignment here.
        if not meta.get('initialized') or not arcpy.Exists(str(Path(report['geodatabase'])/NAME)) or report.get('affectedOrigins',0)>pending:
            db.execute('INSERT OR IGNORE INTO SurfacePending SELECT Origin FROM Winners')
            db.execute('INSERT OR IGNORE INTO SurfacePending SELECT Origin FROM Managed WHERE Dataset=?',(NAME,));db.commit()
        pending=db.execute('SELECT count(*) FROM SurfacePending').fetchone()[0]
        fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
        if any(f['fieldName']=='WelCnsStat' for f in fields):
            from WellConstraintAttributes import configure
            configure(root)
        if not pending and meta.get('initialized'):
            if meta.get('projectRoot')!=str(root):
                ensure_project(report,fields);db.execute('INSERT OR REPLACE INTO SurfaceMeta VALUES(?,?)',('projectRoot',str(root)));db.commit()
            report.setdefault('counts',{})[NAME]=int(meta['count']);report.setdefault('surfaceHoleChanges',dict(inserted=0,updated=0,deleted=0));return report
        db.execute('DROP TABLE IF EXISTS Focus');db.execute('CREATE TEMP TABLE Focus(Origin TEXT PRIMARY KEY)');db.execute('INSERT INTO Focus SELECT Origin FROM SurfacePending')
        db.execute('DROP TABLE IF EXISTS Desired');db.execute('CREATE TABLE Desired(Dataset TEXT,RecKey TEXT,Origin TEXT,Hash TEXT,Attrs TEXT,Geom TEXT,Entity TEXT,PRIMARY KEY(Dataset,RecKey))');db.execute('CREATE INDEX DesiredOrigin ON Desired(Origin)')
        skipped=0
        for group,payload in db.execute('SELECT w.Origin,w.Attrs FROM Winners w JOIN Focus f ON w.Origin=f.Origin'):
            attrs=json.loads(payload);x,y=number(attrs.get('ShlLon')),number(attrs.get('ShlLat'))
            if x is None or y is None or not (-180<=x<=180 and -90<=y<=90):skipped+=1;continue
            point=arcpy.PointGeometry(arcpy.Point(x,y),SR)
            managed.desired(db,NAME,group,group,managed.project_attributes(attrs,fields,group),point.JSON)
        db.commit();gdb=Path(report['geodatabase']);path=str(gdb/NAME)
        if not arcpy.Exists(path):
            arcpy.management.CreateFeatureclass(str(gdb),NAME,'POINT',spatial_reference=SR)
        existing={f.name for f in arcpy.ListFields(path)}
        for f in fields:
            if f['fieldName'] not in existing:arcpy.management.AddField(path,f['fieldName'],f['exportType'],field_length=f.get('textLength'),field_alias=f['alias'])
        ensure_defaults(path,fields)
        if not arcpy.ListIndexes(path,'RecKeyIdx'):arcpy.management.AddIndex(path,'RecKey','RecKeyIdx')
        qa=Path(report['qaFolder'])/'SurfaceHoles';qa.mkdir(parents=True,exist_ok=True)
        previous=managed.SPECS
        try:
            managed.SPECS={NAME:('POINT',False)}
            result=managed.apply(root,config,db,fields,qa)
        finally:managed.SPECS=previous
        ensure_project(report,fields)
        db.execute('DELETE FROM SurfacePending');count=db.execute('SELECT count(*) FROM Managed WHERE Dataset=?',(NAME,)).fetchone()[0]
        db.executemany('INSERT OR REPLACE INTO SurfaceMeta VALUES(?,?)',[('initialized','1'),('count',str(count)),('projectRoot',str(root))]);db.commit()
        report.setdefault('counts',{})[NAME]=count;report.setdefault('gdbChanges',{}).update(result['gdbChanges']);report['gisWrites']=report.get('gisWrites',0)+result['gisWrites'];report['surfaceHoleChanges']=result['gdbChanges'][NAME];report['surfaceHoleMissingCoordinatesInBatch']=skipped
        if result['gisWrites']:report['status']='UpdatedChangedRecords'
        (qa/'SurfaceHoleReport.json').write_text(json.dumps(dict(count=count,missingCoordinatesInBatch=skipped,changes=result['gdbChanges'][NAME],gisWrites=result['gisWrites']),indent=2))
        return report
    finally:db.close()
