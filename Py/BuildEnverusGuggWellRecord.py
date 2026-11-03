"""Portable CLI. The installation root is derived from this file, never a username."""
import argparse,json,os,sys
from pathlib import Path
from ProcessLock import ProcessLock,BusyError
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['validate','probe','sync','build','run','test','migrate']);parser.add_argument('--config',default='Json/Config/Workflow.json');parser.add_argument('--require-cache',action='store_true');args=parser.parse_args()
    config=json.loads((ROOT/args.config).read_text())
    if config['profile']!=Path(config['profile']).name or config['profile'] in ['.','..']:raise RuntimeError('Profile must be a simple folder name')
    if args.action=='test':
        import unittest
        suite=unittest.defaultTestLoader.discover(str(ROOT/'Py'),pattern='Test*.py');result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful():raise SystemExit(1)
        return
    if args.action=='validate':
        import arcpy
        refs=ROOT/config['referenceGdb'];datasets=['GUGG_Nomenclature','GUGG_TCAs','GUGG_FluidWindows']
        missing=[name for name in datasets if not arcpy.Exists(str(refs/name))]
        if missing:raise RuntimeError('Missing Gugg reference datasets: '+','.join(missing))
        if not (ROOT/'Aprx/Template/WellRecordTemplate.aprx').exists():raise RuntimeError('Missing blank ArcGIS project template')
        report=dict(arcgis=arcpy.GetInstallInfo()['Version'],license=arcpy.ProductInfo(),references={n:int(arcpy.management.GetCount(str(refs/n))[0]) for n in datasets},localCredentialsConfigured=(ROOT/'Xml/LocalCredentials/EnverusV3.xml').exists(),root=str(ROOT))
        print(json.dumps(report,indent=2));return
    if args.action=='probe':
        from EnverusApi import Api
        from WellScope import STATUS_FILTER
        api=Api();common=dict(config.get('apiFilters',{}),deleteddate='null',envwellstatus=STATUS_FILTER)
        def included(params):return api.count('wells',params)+api.count('wells',dict(params,envwellstatus='null'))
        report=dict(eligibleWells=included(common),US=included(dict(common,country='US')),Canada=included(dict(common,country='CA')),Alaska=included(dict(common,stateprovince='AK')),unknownStatusWells=api.count('wells',dict(common,envwellstatus='null')))
        print(json.dumps(report,indent=2));return
    folder=ROOT/'Sqlite'/config['profile']/'Cache';folder.mkdir(parents=True,exist_ok=True);cache=folder/'EnverusCache.sqlite';lock=folder/'Workflow.lock'
    held=ProcessLock(lock);held.__enter__()
    try:
        if args.action=='migrate':
            from MigrateProducts import migrate
            print(json.dumps(migrate(ROOT,config),indent=2));return
        if args.require_cache:
            import sqlite3
            if (folder/'ImportInProgress.json').exists():print('Waiting for GIS/cache import to finish; no updates started');raise SystemExit(76)
            if not cache.exists():print('Waiting for a completed/imported baseline; no API download started');raise SystemExit(76)
            check=sqlite3.connect('file:'+cache.as_posix()+'?mode=ro',uri=True)
            try:watermark=dict(check.execute('SELECT Key,Value FROM Meta')).get('watermark')
            finally:check.close()
            if not watermark:print('Cache has no successful watermark; no API download started');raise SystemExit(76)
        if args.action in ['sync','run']:
            from EnverusApi import Api
            from SourceCache import sync
            schema=json.loads((ROOT/'Json/Config/HeaderSchema.json').read_text());api=Api();required={f['directApiField'] for f in schema['fields']}
            report=sync(api,cache,config,required)
            from HeaderBackfill import ensure_fields
            report['headerExpansion']=ensure_fields(api,cache,config,required)
            qa=ROOT/'Json'/config['profile']/'Output'/'Qa';qa.mkdir(parents=True,exist_ok=True);(qa/'LatestSync.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
        if args.action in ['build','run']:
            if not cache.exists():raise RuntimeError('Run sync first: no source baseline is present')
            if args.require_cache:
                # Nightly jobs must never silently initialize national GIS.
                # A source-only transfer can still sync while awaiting the
                # explicit first build or a complete GIS-state import.
                state=folder/'Processed.sqlite';initialized=False
                if state.exists():
                    check=sqlite3.connect('file:'+state.as_posix()+'?mode=ro',uri=True)
                    try:
                        if check.execute("SELECT 1 FROM sqlite_master WHERE name='ProductMeta'").fetchone():initialized=dict(check.execute('SELECT * FROM ProductMeta')).get('initialized')=='1'
                    finally:check.close()
                if not initialized or not (ROOT/'Gdb'/config['profile']/'Output/EnverusGuggWellRecord.gdb').exists():
                    print('Source sync is available; waiting for initial GIS build or GIS-state import. No full GIS rebuild started.');raise SystemExit(77)
            import sqlite3
            check=sqlite3.connect('file:'+cache.as_posix()+'?mode=ro',uri=True)
            try:source_meta=dict(check.execute('SELECT * FROM Meta'))
            finally:check.close()
            required={f['directApiField'] for f in json.loads((ROOT/'Json/Config/HeaderSchema.json').read_text())['fields']}
            known=set(json.loads(source_meta.get('headerFields','[]')))
            if not known and source_meta.get('baselineDefinition'):known=set(json.loads(source_meta['baselineDefinition']).get('fields','').split(','))
            if not required<=known:raise RuntimeError('New template header fields are not in the source cache. Run sync to backfill them before building.')
            from BuildProducts import build
            from SurfaceHoles import capture_pending,sync_surface
            capture_pending(ROOT,config,cache)
            report=sync_surface(ROOT,config,build(ROOT,config,cache))
            (ROOT/'Json/Config/LatestPortableOutput.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report,indent=2))
    finally:held.__exit__(None,None,None)

if __name__=='__main__':
    try:main()
    except BusyError as error:print(str(error));raise SystemExit(75)
