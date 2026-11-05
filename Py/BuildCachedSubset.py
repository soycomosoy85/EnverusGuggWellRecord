"""Build an isolated TX/NM delivery from the existing account cache, without API calls.

Acquisition and national processing remain unchanged. Source and cached geometry
snapshots are made under the national workflow lock; the independent subset then
builds under its own lock. Re-running resumes the prepared subset.
"""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from ProcessLock import ProcessLock
from SourceCache import initialize

ROOT = Path(__file__).resolve().parents[1]


def prepare(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output or output in source.parents:
        raise ValueError('The custom run must have its own output root')
    config = json.loads((source/'Json/Config/Workflow.json').read_text())
    source_base = source/'Sqlite'/config['profile']/'Cache'
    base = output/'Sqlite/TexasNewMexico/Cache'
    base.mkdir(parents=True, exist_ok=True)
    cache, processed = base/'EnverusCache.sqlite', base/'Processed.sqlite'
    marker = base/'SubsetPrepared.json'
    if marker.exists():
        return json.loads((output/'Json/Config/Workflow.json').read_text())
    if cache.exists() or processed.exists():
        raise RuntimeError('An incomplete subset already exists; inspect it before replacing files')
    with ProcessLock(source_base/'Workflow.lock'):
        for name in ['Py', 'Aprx/Template', 'Atbx', 'Gdb/Reference']:
            shutil.copytree(source/name, output/name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.lock'))
        cfg_folder = output/'Json/Config'
        cfg_folder.mkdir(parents=True, exist_ok=True)
        for name in ['HeaderSchema.json', 'FieldDictionary.json', 'WellRecordRules.json']:
            shutil.copy2(source/'Json/Config'/name, cfg_folder/name)
        lookup=source/'Json/Config/WellConstraintStatus.Local.json'
        if lookup.exists():shutil.copy2(lookup,cfg_folder/lookup.name)
        config.update(profile='TexasNewMexico', apiFilters={'stateprovince':'in(TX,NM)'}, exportShapefiles=False)
        config['note'] = 'Custom cached TX/NM snapshot; no API acquisition or nightly task installed.'
        (cfg_folder/'Workflow.json').write_text(json.dumps(config, indent=2))
        pending = base/'SubsetSourcePending.sqlite'
        db = sqlite3.connect(pending, uri=True)
        try:
            initialize(db)
            db.execute('ATTACH DATABASE ? AS original', ((source_base/'EnverusCache.sqlite').as_uri()+'?mode=ro',))
            print('Selecting cached Texas and New Mexico well records', flush=True)
            db.execute("INSERT INTO Wells SELECT * FROM original.Wells WHERE upper(json_extract(Payload,'$.StateProvince')) IN ('TX','TEXAS','NM','NEW MEXICO')")
            wells = db.execute('SELECT count(*) FROM Wells').fetchone()[0]
            if not wells:
                raise RuntimeError('No TX/NM records matched; no empty delivery will be built')
            db.execute('CREATE TEMP TABLE SelectedBores(Api TEXT PRIMARY KEY)')
            db.execute('INSERT OR IGNORE INTO SelectedBores SELECT DISTINCT Api FROM Wells')
            for table in ['Headers', 'Stations', 'BoreVersions']:
                print('Copying cached '+table+' for '+format(wells, ',')+' selected well records', flush=True)
                db.execute('INSERT INTO '+table+' SELECT o.* FROM original.'+table+' o JOIN SelectedBores b ON o.Api=b.Api')
                db.commit()
            db.execute('INSERT INTO Meta SELECT * FROM original.Meta')
            db.execute('INSERT OR REPLACE INTO Meta VALUES(?,?)', ('scope',json.dumps(config['apiFilters'],sort_keys=True)))
            db.execute('INSERT INTO DirtyOrigins SELECT DISTINCT Origin FROM Wells')
            db.commit()
            if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError('Subset source validation failed')
        finally:
            db.close()
        pending.replace(cache)
        print('Reusing completed national geometry calculations', flush=True)
        pending_processed = base/'SubsetProcessingPending.sqlite'
        db = sqlite3.connect(pending_processed, uri=True)
        try:
            db.execute('ATTACH DATABASE ? AS original', ((source_base/'Processed.sqlite').as_uri()+'?mode=ro',))
            db.execute('ATTACH DATABASE ? AS subset', (str(cache),))
            db.execute('CREATE TABLE Results(Id TEXT PRIMARY KEY,Origin TEXT,Signature TEXT,Layer TEXT,Attrs TEXT,Geom TEXT,Geom3 TEXT)')
            db.execute('CREATE INDEX ResultOrigin ON Results(Origin)')
            db.execute('INSERT INTO Results SELECT r.* FROM original.Results r JOIN subset.Wells w ON r.Id=w.Id')
            reused = db.execute('SELECT count(*) FROM Results').fetchone()[0]
            db.commit()
        finally:
            db.close()
        pending_processed.replace(processed)
        report=dict(prepared=datetime.now(timezone.utc).isoformat(),states=['TX','NM'],sourceRoot=str(source),outputRoot=str(output),sourceRecords=wells,cachedCalculations=reused)
        marker.write_text(json.dumps(report,indent=2))
        print(json.dumps(report),flush=True)
    return config


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-root',default=str(ROOT))
    parser.add_argument('--output-root')
    args=parser.parse_args()
    source=Path(args.source_root).resolve()
    output=Path(args.output_root).resolve() if args.output_root else source/'CustomRuns/TexasNewMexico'
    base=output/'Sqlite/TexasNewMexico/Cache'
    with ProcessLock(base/'Workflow.lock'):
        config=prepare(source,output)
        from BuildProducts import build
        from SurfaceHoles import capture_pending,sync_surface
        cache=base/'EnverusCache.sqlite'
        capture_pending(output,config,cache)
        report=sync_surface(output,config,build(output,config,cache))
        report['customScope']=['TX','NM']
        (output/'Json/Config/LatestPortableOutput.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':main()
