"""Confirm the actual national products, fields, lookup values and row registry."""
import arcpy
import json,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from collections import Counter
from WellConstraintAttributes import configure,apply

ROOT=Path(__file__).resolve().parents[1]


def validate(root=ROOT):
    root=Path(root);config=json.loads((root/'Json/Config/Workflow.json').read_text());profile=config['profile']
    fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text());lookup=configure(root)
    expected_names=[f['fieldName'] for f in fields]
    report=json.loads((root/'Json/Config/LatestPortableOutput.json').read_text())
    gdb=root/'Gdb'/profile/'Output/EnverusGuggWellRecord.gdb'
    if Path(report['geodatabase']).resolve()!=gdb.resolve():raise RuntimeError('Final well report points to a different geodatabase')
    state=sqlite3.connect(root/'Sqlite'/profile/'Cache/Processed.sqlite')
    try:
        if dict(state.execute('SELECT * FROM ProductMeta')).get('initialized')!='1':raise RuntimeError('Well GIS initialization is incomplete')
        registry=dict(state.execute('SELECT Dataset,count(*) FROM Managed GROUP BY Dataset'))
    finally:state.close()
    checks={}
    with arcpy.EnvManager(workspace=str(gdb)):
        if set(arcpy.ListFeatureClasses())!={'EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg'} or arcpy.ListTables():raise RuntimeError('Final GDB contains unexpected or unfinished products')
    for name in ['EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg']:
        path=str(gdb/name);actual=arcpy.ListFields(path);user=[f for f in actual if f.type not in ['OID','Geometry'] and f.name not in ['Shape_Length','Shape_Area']]
        if [f.name for f in user]!=expected_names:raise RuntimeError('Incorrect field order: '+name)
        by_name={f.name:f for f in user}
        for field in fields:
            observed=by_name[field['fieldName']]
            if observed.aliasName!=field['alias']:raise RuntimeError('Incorrect alias: '+name+'.'+field['fieldName'])
            if field['exportType']=='TEXT' and observed.length<(field.get('textLength') or 254):raise RuntimeError('Text width is too short')
            if observed.type in ['Blob','Raster','GUID','GlobalID','TimestampOffset','DateOnly','TimeOnly','BigInteger']:raise RuntimeError('Unsupported delivery field type')
        if by_name['WellConstr'].length!=1:raise RuntimeError('WellConstr must remain one character')
        count=int(arcpy.management.GetCount(path)[0])
        if count!=registry.get(name) or count!=report['counts'].get(name):raise RuntimeError('Feature count mismatch: '+name)
        statuses=Counter();constraints=Counter()
        with arcpy.da.SearchCursor(path,['EnvStatus','Trajectory','WellConstr','WelCnsStat']) as rows:
            for status,trajectory,flag,label in rows:
                expected=apply(dict(EnvStatus=status,Trajectory=trajectory,WellConstr=flag),lookup)
                if flag!=expected['WellConstr'] or label!=expected['WelCnsStat']:raise RuntimeError('Invalid constraint attributes in '+name)
                statuses[label or '<NULL>']+=1;constraints[flag]+=1
        checks[name]=dict(count=count,fields=len(user),statusCounts=dict(statuses),constraintCounts=dict(constraints))
        print('Validated '+name+': '+str(count)+' features',flush=True)
    context=json.loads((root/'Json'/profile/'Context/LatestContextRun.json').read_text())
    if context['status']!='Complete':raise RuntimeError('One or more enabled context datasets failed')
    context_counts={}
    for layer in context['layers']:
        if layer['status']=='Disabled':continue
        item=layer['build'];count=int(arcpy.management.GetCount(item['featureClass'])[0])
        if count!=item['features']:raise RuntimeError('Context count mismatch: '+layer['dataset'])
        context_counts[layer['dataset']]=count
    result=dict(status='Complete',completed=datetime.now(timezone.utc).isoformat(),geodatabase=str(gdb),wells=checks,context=context_counts,validation=dict(passed=True,fieldOrder=True,aliases=True,registryCounts=True,trajectoryWhitelist=True,statusLookup=True),agolPublished=False)
    report['validation'].update(result['validation']);report['nationalValidation']=result
    (root/'Json/Config/LatestPortableOutput.json').write_text(json.dumps(report,indent=2))
    (root/'Json/Config/LatestNationalRebuild.json').write_text(json.dumps(result,indent=2))
    return result


if __name__=='__main__':print(json.dumps(validate(),indent=2))
