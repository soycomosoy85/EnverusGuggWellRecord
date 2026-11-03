"""Prepare a local GIS-basin subset and storage planning report; never upload."""
import hashlib,json,shutil,uuid,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from ProcessLock import ProcessLock,BusyError

WELLS=['EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg']

def prepare(root,config):
    import arcpy
    root=Path(root);profile=config['profile'];output=root/'Json'/profile/'Agol';output.mkdir(parents=True,exist_ok=True)
    scope=config['scope'];basin=root/scope['featureClass'];field=scope['nameField'];well_field=scope['wellFieldName']
    if config.get('publishFullNationalDataset'):raise RuntimeError('National publication is prohibited for this test workflow')
    report=dict(status='WaitingForCompletedProducts',uploaded=False,published=False,scopeFeatureClass=str(basin),wellBasinField=well_field)
    def finish():
        (output/'SubsetSizeReport.json').write_text(json.dumps(report,indent=2));return report
    held=[]
    try:
        for relative in [f'Sqlite/{profile}/Cache/Workflow.lock',f'Sqlite/{profile}/Context/Context.lock']:
            lock=ProcessLock(root/relative);lock.__enter__();held.append(lock)
        context=json.loads((root/'Json/Config/ContextLayers.json').read_text())
        sources=[(name,root/'Gdb'/profile/'Output/EnverusGuggWellRecord.gdb'/name,True) for name in WELLS]
        sources += [(layer['featureClass'],root/'Gdb'/profile/'Output'/context['outputGeodatabase']/layer['featureClass'],False) for layer in context['layers'] if layer.get('enabled')]
        missing=[name for name,path,is_well in sources if not arcpy.Exists(str(path))]
        if missing:report['missingLayers']=missing;return finish()
        state=root/'Sqlite'/profile/'Cache/Processed.sqlite'
        if not state.exists():report['status']='WaitingForCompletedWellBuild';return finish()
        db=sqlite3.connect('file:'+state.as_posix()+'?mode=ro',uri=True)
        try:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            complete='ProductMeta' in tables and dict(db.execute('SELECT * FROM ProductMeta')).get('initialized')=='1' and 'SurfaceMeta' in tables and dict(db.execute('SELECT * FROM SurfaceMeta')).get('initialized')=='1'
            if 'SurfacePending' in tables and db.execute('SELECT count(*) FROM SurfacePending').fetchone()[0]:complete=False
        finally:db.close()
        if not complete:report['status']='WaitingForCompletedWellBuild';return finish()
        cache=root/'Sqlite'/profile/'Cache/EnverusCache.sqlite'
        if not cache.exists():report['status']='WaitingForWellSourceCache';return finish()
        db=sqlite3.connect('file:'+cache.as_posix()+'?mode=ro',uri=True)
        try:dirty=db.execute('SELECT count(*) FROM DirtyOrigins').fetchone()[0]
        finally:db.close()
        if dirty:report.update(status='WaitingForCompletedWellBuild',pendingOrigins=dirty);return finish()
        for layer in context['layers']:
            if not layer.get('enabled'):continue
            cache=root/'Sqlite'/profile/'Context'/(layer['dataset']+'.sqlite')
            if not cache.exists():report.update(status='WaitingForCompletedContextBuild',dataset=layer['dataset']);return finish()
            db=sqlite3.connect('file:'+cache.as_posix()+'?mode=ro',uri=True)
            try:dirty=db.execute('SELECT count(*) FROM Dirty').fetchone()[0]
            finally:db.close()
            if dirty:report.update(status='WaitingForCompletedContextBuild',dataset=layer['dataset'],pendingRows=dirty);return finish()
        for name,path,is_well in sources:
            if is_well and well_field not in {f.name for f in arcpy.ListFields(str(path))}:report.update(status='WaitingForWellBasinAssignment',missingFieldLayer=name);return finish()
        names=sorted({str(value) for value, in arcpy.da.SearchCursor(str(basin),[field]) if value is not None})
        if not names:raise RuntimeError('Empty GIS basin scope; no subset is prepared')
        if config.get('awaitUserQualityControl'):
            report.update(status='AwaitingUserQualityControl',basins=names,sourceLayers=len(sources));return finish()
        signature=hashlib.sha256()
        for value,wkb in arcpy.da.SearchCursor(str(basin),[field,'SHAPE@WKB']):signature.update(str(value).encode());signature.update(bytes(wkb))
        for folder in sorted({p.parent for _,p,_ in sources}):
            for p in sorted(folder.iterdir()):
                if p.is_file() and not p.name.lower().endswith('.lock'):signature.update(str((p.name,p.stat().st_size,p.stat().st_mtime_ns)).encode())
        digest=signature.hexdigest();prior_path=output/'SubsetSizeReport.json'
        if prior_path.exists():
            old=json.loads(prior_path.read_text())
            if old.get('signature')==digest and old.get('stagingGeodatabase') and arcpy.Exists(old['stagingGeodatabase']):old['status']='UnchangedSubset';return old
        if shutil.disk_usage(root).free<20*1024**3:raise RuntimeError('Insufficient disk reserve for publication subset preparation')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');folder=root/'Gdb'/profile/'PublishStaging';folder.mkdir(parents=True,exist_ok=True);gdb=folder/('AgolSubset'+stamp+'.gdb');arcpy.management.CreateFileGDB(str(folder),gdb.name)
        layers=[];estimated=0
        for name,path,is_well in sources:
            view='Scope'+uuid.uuid4().hex[:12]
            try:
                arcpy.management.MakeFeatureLayer(str(path),view)
                if is_well:
                    values=','.join("'"+n.replace("'","''")+"'" for n in names);where=arcpy.AddFieldDelimiters(str(path),well_field)+' IN ('+values+')';arcpy.management.SelectLayerByAttribute(view,'NEW_SELECTION',where)
                else:arcpy.management.SelectLayerByLocation(view,'INTERSECT',str(basin),selection_type='NEW_SELECTION')
                count=int(arcpy.management.GetCount(view)[0]);arcpy.management.CopyFeatures(view,str(gdb/name))
                attrs=[f.name for f in arcpy.ListFields(str(gdb/name)) if f.type not in ['OID','Geometry'] and f.name not in ['Shape_Length','Shape_Area']];sizes=[]
                with arcpy.da.SearchCursor(str(gdb/name),['SHAPE@JSON']+attrs) as cursor:
                    for i,row in enumerate(cursor):
                        if i>=500:break
                        sizes.append(len(json.dumps(dict(geometry=json.loads(row[0]),attributes=dict(zip(attrs,row[1:]))),default=str,separators=(',',':')).encode()))
                estimate=int(count*sum(sizes)/len(sizes)) if sizes else 0;estimated+=estimate
                detail=dict(layer=name,sourceFeatures=int(arcpy.management.GetCount(str(path))[0]),features=count,attributeColumns=len(attrs),sampleRecords=len(sizes),estimatedJsonBytes=estimate,preservedWholeGeometries=True)
                if is_well:
                    from collections import Counter
                    detail['featuresByGisBasin']=dict(Counter(value for value, in arcpy.da.SearchCursor(str(gdb/name),[well_field])))
                layers.append(detail)
            finally:
                if arcpy.Exists(view):arcpy.management.Delete(view)
        size=sum(p.stat().st_size for p in gdb.iterdir() if p.is_file() and not p.name.lower().endswith('.lock'));monthly=estimated/1000000/10*2.4
        report.update(status='ReadyForSizeReview',signature=digest,stagingGeodatabase=str(gdb),basins=names,layers=layers,stagingBytes=size,sampleEstimatedJsonBytes=estimated,hostedStorageCreditsPerMonthPlanningRange=[round(monthly*.5,2),round(monthly*2,2)],estimateCaveat='Sample-based planning range only. Actual hosted feature storage differs from local GDB and JSON sizes; no upload has occurred.',creditRateSource='https://doc.arcgis.com/en/arcgis-online/administer/credits.htm')
        return finish()
    except BusyError:
        report['status']='WaitingForSyncLocks';return finish()
    finally:
        for lock in reversed(held):lock.__exit__(None,None,None)
