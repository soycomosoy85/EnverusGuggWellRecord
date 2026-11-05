"""Add/recalculate constraint attributes without surveys or spatial enrichment.

An ordered copy is needed once because file geodatabases and DBF files append
new fields. Coordinates are copied unchanged and checked by stable-key/WKB
checksums. Subsequent lookup changes update attributes in place.
Call while holding the profile's Workflow.lock.
"""
import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import arcpy
from ProcessLock import ProcessLock
from WellConstraintAttributes import apply, configure, rules_hash

DATASETS=('EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg')


def schema_signature(fields):
    return json.dumps([(f['fieldName'],f['exportType'],f['alias']) for f in fields if f['fieldName']!='RecKey'],sort_keys=True,separators=(',',':'))


def feature_check(path,lookup=None):
    total=0;checksum=0;statuses=Counter();unmapped=Counter()
    columns=['RecKey','SHAPE@WKB']
    if lookup is not None:columns+=['EnvStatus','Trajectory','WellConstr','WelCnsStat']
    with arcpy.da.SearchCursor(str(path),columns) as rows:
        for row in rows:
            total+=1
            checksum=(checksum+int.from_bytes(hashlib.sha256(str(row[0]).encode()+b'\0'+bytes(row[1] or b'')).digest(),'big'))%(1<<256)
            if lookup is not None:
                expected=apply(dict(EnvStatus=row[2],Trajectory=row[3],WellConstr=row[4]),lookup)
                actual=str(row[5] or '').strip() or None
                if row[4]!=expected['WellConstr'] or actual!=expected['WelCnsStat']:
                    raise RuntimeError('Constraint attribute validation failed for '+str(path)+' '+str(row[0]))
                statuses[actual or '<NULL>']+=1
                if actual is None:unmapped[str(row[2] or '<NULL>')]+=1
    return dict(count=total,geometryChecksum=hex(checksum),statusCounts=dict(statuses),unmappedStatuses=dict(unmapped))


def ordered_fields(path,fields):
    existing={f.name:f for f in arcpy.ListFields(str(path))}
    desired=[f['fieldName'] for f in fields if f['fieldName'] in existing]
    actual=[f.name for f in arcpy.ListFields(str(path)) if f.name in desired]
    if actual==desired:return False
    temporary=path.with_name(path.stem+'AttrNew'+path.suffix)
    backup=path.with_name(path.stem+'AttrOld'+path.suffix)
    if arcpy.Exists(str(backup)):
        raise RuntimeError('An earlier ordered-copy backup needs inspection: '+str(backup))
    if arcpy.Exists(str(temporary)):arcpy.management.Delete(str(temporary))
    mappings=arcpy.FieldMappings()
    for name in desired+(['NullCount'] if 'NullCount' in existing else []):
        mapping=arcpy.FieldMap();mapping.addInputField(str(path),name)
        field=mapping.outputField
        field.aliasName=next((f['alias'] for f in fields if f['fieldName']==name),name)
        mapping.outputField=field;mappings.addFieldMap(mapping)
    before=feature_check(path)
    with arcpy.EnvManager(outputCoordinateSystem=arcpy.Describe(str(path)).spatialReference,extent=None):
        arcpy.conversion.ExportFeatures(str(path),str(temporary),field_mapping=mappings)
    after=feature_check(temporary)
    if (before['count'],before['geometryChecksum'])!=(after['count'],after['geometryChecksum']):
        raise RuntimeError('Ordered attribute copy changed feature membership or geometry; original retained: '+str(path))
    arcpy.management.Rename(str(path),str(backup))
    try:arcpy.management.Rename(str(temporary),str(path))
    except Exception:
        arcpy.management.Rename(str(backup),str(path));raise
    arcpy.management.Delete(str(backup))
    return True


def update_feature_class(path,fields,lookup):
    path=Path(path);existing={f.name:f for f in arcpy.ListFields(str(path))}
    if 'WelCnsStat' not in existing:
        arcpy.management.AddField(str(path),'WelCnsStat','TEXT',field_length=6,field_alias='Well Constraint Status')
    is_shp=path.suffix.lower()=='.shp'
    names=[f['fieldName'] for f in fields if f['fieldName']!='RecKey']
    columns=names+(['NullCount'] if is_shp else [])
    idx={n:i for i,n in enumerate(columns)};changed=0
    with arcpy.da.UpdateCursor(str(path),columns) as rows:
        for row in rows:
            attrs={n:row[idx[n]] for n in ['EnvStatus','Trajectory','WellConstr']}
            result=apply(attrs,lookup);new=list(row)
            new[idx['WellConstr']]=result['WellConstr'];new[idx['WelCnsStat']]=result['WelCnsStat'] or ('' if is_shp else None)
            if is_shp:new[idx['NullCount']]=sum(value is None or value=='' or value==-999999999 for value in new[:-1])
            if list(row)!=new:rows.updateRow(new);changed+=1
    copied=ordered_fields(path,fields)
    if not is_shp:
        arcpy.management.AlterField(str(path),'WelCnsStat',new_field_alias='Well Constraint Status')
        if not arcpy.ListIndexes(str(path),'RecKeyIdx'):arcpy.management.AddIndex(str(path),'RecKey','RecKeyIdx')
        arcpy.management.AssignDefaultToField(str(path),'WellConstr','N')
    result=feature_check(path,lookup)
    actual=[f.name for f in arcpy.ListFields(str(path))]
    if actual.index('WelCnsStat')!=actual.index('WellConstr')+1:raise RuntimeError('Constraint status field is out of order: '+str(path))
    result.update(updated=changed,orderedCopy=copied)
    return result


def upgrade_if_needed(root,config,db,fields,force=False):
    from ManagedProducts import hide_key,write_layer
    root=Path(root);meta=dict(db.execute('SELECT * FROM ProductMeta'))
    if not any(f['fieldName']=='WelCnsStat' for f in fields):return None
    signature=schema_signature(fields);revision=rules_hash(root)
    if not meta.get('schema'):
        db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('constraintAttributeRulesHash',revision));db.commit();return None
    if not force and meta.get('constraintAttributeRulesHash')==revision and meta['schema']==signature:return None
    previous=schema_signature([f for f in fields if f['fieldName']!='WelCnsStat'])
    if meta['schema'] not in [signature,previous]:raise RuntimeError('Unsupported schema change; constraint upgrade handles only WelCnsStat')
    profile=config['profile'];gdb=root/'Gdb'/profile/'Output/EnverusGuggWellRecord.gdb'
    if not arcpy.Exists(str(gdb)):raise RuntimeError('Constraint upgrade requires the existing managed GDB')
    qa=root/'Json'/profile/'Output/Qa';qa.mkdir(parents=True,exist_ok=True)
    state_path=qa/'ConstraintAttributeUpgrade.json'
    report=dict(status='Running',started=datetime.now(timezone.utc).isoformat(),geodatabase=str(gdb),geometryRecomputations=0,spatialJoins=0,apiDownloads=0,features={},shapefiles={},validation=dict(passed=False))
    state_path.write_text(json.dumps(report,indent=2));lookup=configure(root)
    try:
        for dataset in DATASETS:
            path=gdb/dataset
            if not arcpy.Exists(str(path)):continue
            print('Updating constraint attributes '+dataset,flush=True)
            report['features'][dataset]=update_feature_class(path,fields,lookup)
            with arcpy.da.SearchCursor(str(path),['OID@','RecKey']) as rows:
                db.executemany('UPDATE Managed SET Oid=? WHERE Dataset=? AND RecKey=?',((oid,dataset,key) for oid,key in rows))
            db.commit();state_path.write_text(json.dumps(report,indent=2))
        if config.get('exportShapefiles',True) and db.execute("SELECT 1 FROM sqlite_master WHERE name='ShpParts'").fetchone():
            for relative, in db.execute('SELECT Part FROM ShpParts ORDER BY Part').fetchall():
                path=root/relative
                if not arcpy.Exists(str(path)):raise RuntimeError('Managed shapefile is missing: '+str(path))
                print('Updating constraint attributes '+path.name,flush=True)
                report['shapefiles'][relative]=update_feature_class(path,fields,lookup)
                write_layer(root,profile,path,[f for f in fields if f['fieldName']!='RecKey'])
                state_path.write_text(json.dumps(report,indent=2))
        project_path=root/'Aprx'/profile/'EnverusGuggWellRecord.aprx'
        if project_path.exists():
            project=arcpy.mp.ArcGISProject(str(project_path))
            for m in project.listMaps():
                for layer in m.listLayers():
                    if layer.isFeatureLayer and layer.name in DATASETS:hide_key(layer,[f for f in fields if f['fieldName']!='RecKey'])
            project.save();del project
        report.update(status='Complete',completed=datetime.now(timezone.utc).isoformat(),validation=dict(passed=True,unchangedGeometry=True,fieldOrder=True,trajectoryWhitelist=True,statusLookup=True))
        db.executemany('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',[('schema',signature),('constraintAttributeRulesHash',revision)])
        final_path=root/'Json/Config/LatestPortableOutput.json'
        if final_path.exists():
            final=json.loads(final_path.read_text());final['constraintAttributeUpgrade']=report
            final.setdefault('validation',{})['constraintAttributes']=True
            final_path.write_text(json.dumps(final,indent=2))
            if meta.get('lastReport'):
                cached=json.loads(meta['lastReport']);cached['constraintAttributeUpgrade']=report
                db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('lastReport',json.dumps(cached)))
        db.commit()
    except Exception as error:
        report.update(status='NeedsAttention',error=str(error));raise
    finally:state_path.write_text(json.dumps(report,indent=2))
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));args=parser.parse_args()
    root=Path(args.root).resolve();config=json.loads((root/'Json/Config/Workflow.json').read_text());fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
    base=root/'Sqlite'/config['profile']/'Cache'
    with ProcessLock(base/'Workflow.lock'):
        db=sqlite3.connect(base/'Processed.sqlite')
        try:print(json.dumps(upgrade_if_needed(root,config,db,fields),indent=2),flush=True)
        finally:db.close()


if __name__=='__main__':main()
