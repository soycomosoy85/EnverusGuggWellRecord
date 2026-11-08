"""Finish an interrupted export checkpoint without invoking well geometry work.

The three core GDB products must already have complete, matching Desired and
Managed row counts. Only the cached surface-hole product is then populated.
"""
import arcpy
import argparse,hashlib,json,re,sqlite3
from pathlib import Path
from datetime import datetime,timezone
from ProcessLock import ProcessLock
from SurfaceHoles import capture_pending,sync_surface
import ManagedProducts as managed

ROOT=Path(__file__).resolve().parents[1]


def finish(root,config):
    root=Path(root);profile=config['profile'];base=root/'Sqlite'/profile/'Cache'
    checkpoint=json.loads((root/'Json/Config/GdbOnlyCheckpoint.json').read_text())
    source=base/'EnverusCache.sqlite';gdb=root/'Gdb'/profile/'Output/EnverusGuggWellRecord.gdb'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');qa=root/'Json'/profile/'Output/Qa'/stamp;qa.mkdir(parents=True,exist_ok=True)
    fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
    db=sqlite3.connect(base/'Processed.sqlite')
    try:
        print('Verifying completed geodatabase checkpoint; existing features will be retained',flush=True)
        db.execute('ATTACH DATABASE ? AS source',(str(source),))
        signature_sample=db.execute('SELECT w.Payload,b.Version,r.Signature FROM source.Wells w JOIN Results r ON r.Id=w.Id LEFT JOIN source.BoreVersions b ON b.Api=w.Api LIMIT 64').fetchall()
        if not signature_sample or any(hashlib.sha256((payload+str(version)+checkpoint['rulesHash']).encode()).hexdigest()!=signature for payload,version,signature in signature_sample):raise RuntimeError('Cached geometry signatures do not match the captured checkpoint')
        expected=dict(db.execute('SELECT Dataset,count(*) FROM Desired GROUP BY Dataset'))
        registry=dict(db.execute('SELECT Dataset,count(*) FROM Managed GROUP BY Dataset'))
        if set(expected)!=set(managed.SPECS):raise RuntimeError('Expected three completed core products in the export checkpoint')
        for name,count in expected.items():
            if count!=registry.get(name) or count!=int(arcpy.management.GetCount(str(gdb/name))[0]):raise RuntimeError('Incomplete GDB checkpoint: '+name)
            sample=db.execute('SELECT d.Hash,m.Hash FROM Desired d LEFT JOIN Managed m ON m.Dataset=d.Dataset AND m.RecKey=d.RecKey WHERE d.Dataset=? ORDER BY d.RecKey LIMIT 2000',(name,)).fetchall()
            if any(prior!=actual for prior,actual in sample):raise RuntimeError('Feature-hash mismatch in completed checkpoint: '+name)
        print('Verified completed core layers: '+json.dumps(expected),flush=True)
        db.execute('DROP TABLE IF EXISTS Focus');db.execute('CREATE TEMP TABLE Focus(Origin TEXT PRIMARY KEY)');db.execute('INSERT INTO Focus SELECT Origin FROM Winners')
        # Permanently retire all legacy shapefile tracking, including old migrations.
        legacy=[name for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table'") if name.lower().startswith('shp')]
        for name in legacy:
            if not re.fullmatch('[A-Za-z0-9_]+',name):raise RuntimeError('Unexpected legacy tracking-table name')
            db.execute('DROP TABLE "'+name+'"')
        db.commit()
        report=managed.apply(root,config,db,fields,qa)
        if report['gisWrites']!=0:raise RuntimeError('A completed core layer unexpectedly required GIS writes')
        print('Restoring processing summary from cached winners',flush=True)
        db.execute('DELETE FROM WinnerStats');db.execute("INSERT INTO WinnerStats SELECT Origin,json_extract(Attrs,'$.GeomSrc') FROM Winners")
        kinds=dict(db.execute('SELECT Kind,count(*) FROM WinnerStats GROUP BY Kind'))
        db.executemany('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',[('rulesHash',checkpoint['rulesHash']),('sourceCounts',managed.pack(kinds))]);db.commit()
        source_db=sqlite3.connect(source)
        try:source_count=source_db.execute('SELECT count(*) FROM Wells').fetchone()[0]
        finally:source_db.close()
        report.update(run=stamp,qaFolder=str(qa),sourceCache=str(source),referenceFingerprint=checkpoint['referenceFingerprint'],processingCounts=dict(Recomputed=0,Reused=source_count),priorGeometryRecomputations=checkpoint.get('geometryRecomputedBeforeCheckpoint'),selectedGeometrySources=kinds,affectedOrigins=sum(kinds.values()),origins=sum(kinds.values()),includedSourceRecords=source_count,noLocationMapSources=0,noLocationOrigins=kinds.get('NoLocation',0),resumedCompletedGdbCheckpoint=True,outputFormat='FileGeodatabase')
        capture_pending(root,config,source)
        print('Building EnvSH_Gugg directly from cached surface coordinates and selected well attributes',flush=True)
        report=sync_surface(root,config,report)
        source_db=sqlite3.connect(source)
        try:source_db.execute('DELETE FROM DirtyOrigins');source_db.commit()
        finally:source_db.close()
        (qa/'BuildReport.json').write_text(json.dumps(report,indent=2))
        (root/'Json/Config/LatestPortableOutput.json').write_text(json.dumps(report,indent=2))
        db.execute('INSERT OR REPLACE INTO ProductMeta VALUES(?,?)',('lastReport',managed.pack(report)));db.commit()
        print(json.dumps(report,indent=2),flush=True)
        return report
    finally:db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='Json/Config/Workflow.json');args=parser.parse_args()
    config=json.loads((ROOT/args.config).read_text())
    with ProcessLock(ROOT/'Sqlite'/config['profile']/'Cache/Workflow.lock'):finish(ROOT,config)
