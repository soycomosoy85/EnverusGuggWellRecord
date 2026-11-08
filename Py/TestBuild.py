"""Synthetic relocated-installation test; no real wells are shipped or downloaded."""
import gc,json,shutil,sqlite3,tempfile,unittest
from pathlib import Path
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy not installed')
class BuildTests(unittest.TestCase):
    def test_relocated_mixed_country_build_and_incremental_reuse(self):
        from SourceCache import initialize
        from Identity import record_id,origin,survey_key
        from BuildProducts import build as build_main
        from SurfaceHoles import capture_pending,sync_surface
        def build(root,config,cache):
            capture_pending(root,config,cache)
            return sync_surface(root,config,build_main(root,config,cache))
        source_root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='WellRecordTest',ignore_cleanup_errors=True) as folder:
            root=Path(folder)
            for name in ['Py','Json/Config','Gdb/Reference','Aprx/Template','Atbx']:shutil.copytree(source_root/name,root/name,ignore=shutil.ignore_patterns('__pycache__','*.lock'))
            # A synthetic basin/bench pair tests propagation of a true
            # constraint through all four final products.
            ref=root/'Gdb/Reference/GuggenheimReference.gdb'
            with arcpy.da.InsertCursor(str(ref/'GUGG_Nomenclature'),['ENVRegion','ENVBasin','ENVInterval','GUGG_BASIN','GUGG_LANDING_ZONE','GUGG_BENCH','GUGG_TCA_PREFIX']) as cursor:cursor.insertRow(['SYNTHETIC','SYNTHETIC','SYNTHETIC','SYNTHETIC','SYNTHETIC','SYNTHETIC','SYNTHETIC'])
            from WellGeometry import SR
            with arcpy.da.InsertCursor(str(ref/'GUGG_TCAs'),['TCA_NAME','GUGG_BASIN','GUGG_BENCH','WPS','SHAPE@']) as cursor:cursor.insertRow(['SyntheticConstraint','SYNTHETIC','SYNTHETIC',4,arcpy.FromWKT('POLYGON((-104.1 31.9,-103.8 31.9,-103.8 32.1,-104.1 32.1,-104.1 31.9))',SR)])
            cfg=json.loads((root/'Json/Config/Workflow.json').read_text());cfg.update(profile='Synthetic',exportShapefiles=True)
            cache=root/'Sqlite/Synthetic/Cache/EnverusCache.sqlite';cache.parent.mkdir(parents=True);db=sqlite3.connect(cache);initialize(db)
            def well(uwi,bore,country,state,x,y,status='PRODUCING',kind='HORIZONTAL'):
                return dict(API_UWI=uwi,API_UWI_Unformatted=uwi,API_UWI_12_Unformatted=bore,API_UWI_14_Unformatted=uwi+'0000' if country=='US' else None,API_UWI_14=uwi+'0000' if country=='US' else None,Country=country,StateProvince=state,WellID=uwi,CompletionID=uwi,WellName='Synthetic Only',Longitude=x,Latitude=y,Longitude_BH=(x+.02 if x is not None else None),Latitude_BH=y,Trajectory=kind,ENVWellStatus=status,LateralLength_FT=1000,ENVRegion='SYNTHETIC',ENVBasin='SYNTHETIC',ENVInterval='SYNTHETIC',UpdatedDate='2026-10-01T00:00:00Z',LateralLine=(f'LINESTRING({x} {y},{x+.02} {y})' if x is not None else None))
            wells=[well('3000010001','300001000100','US','NM',-104,32),well('3000010002','300001000200','US','NM',-104,32,'PERMITTED'),well('100010101001W500','100010101001W500','CA','AB',-110,55),well('5000010001','500001000100','US','AK',-150,65),well('100010101002W500','100010101002W500','CA','AB',None,None)]
            wells[0].update(UpperPerf_FT=8000,LowerPerf_FT=10000)
            wells[0].update(PermitApprovedDate='2026-10-12T18:34:12Z',LastProducingMonth='2026-09')
            point=well('100010101003W500','100010101003W500','CA','AB',-111,54,kind='VERTICAL');point['LateralLine']=None;wells.append(point)
            for w in wells:
                ident=record_id(w);bore=survey_key(w);db.execute('INSERT INTO Wells VALUES(?,?,?,?,?)',(ident,bore,origin(w),w['UpdatedDate'],json.dumps(w)))
                if w['StateProvince']=='NM':
                    kind='ACTUAL' if w is wells[0] else 'PLANNED';db.execute('INSERT INTO Headers VALUES(?,?,?)',(bore,0,json.dumps(dict(API_UWI_12_Unformatted=bore,CoordinateSource=kind))))
                    for i,(md,x) in enumerate([(8000,-104),(10000,-103.98)]):db.execute('INSERT INTO Stations VALUES(?,?,?)',(bore,i,json.dumps(dict(API_UWI_12_Unformatted=bore,CoordinateSource=kind,MeasuredDepth_FT=md,Longitude=x,Latitude=32,SubseaElevation_FT=-5000,Inclination_DEG=90))))
                db.execute('INSERT INTO BoreVersions VALUES(?,?)',(bore,'20261001'))
            db.commit();db.close()
            db=sqlite3.connect(cache);db.executemany('INSERT INTO Meta VALUES(?,?)',[('watermark','2026-11-01T00:00:00+00:00'),('scope','{}')]);db.commit();db.close()
            report=build(root,cfg,cache);self.assertTrue(report['validation']['passed']);self.assertEqual(report['origins'],6);self.assertEqual(report['selectedGeometrySources']['PlannedSurvey'],1);self.assertEqual(report['selectedGeometrySources']['ActualSurvey'],1);self.assertEqual(report['counts']['EnvWellCentroid_Gugg'],5)
            with arcpy.EnvManager(workspace=report['geodatabase']):
                self.assertEqual(set(arcpy.ListFeatureClasses()),{'EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg'});self.assertEqual(arcpy.ListTables(),[])
            template=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
            for dataset in ['EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg','EnvSH_Gugg']:
                fs=[f for f in arcpy.ListFields(str(Path(report['geodatabase'])/dataset)) if f.type not in ['OID','Geometry'] and f.name not in ['Shape_Length','Shape_Area']]
                self.assertEqual([f.name for f in fs],[f['fieldName'] for f in template]);self.assertEqual([f.aliasName for f in fs],[f['alias'] for f in template])
                constraint=next(f for f in fs if f.name=='WellConstr');self.assertEqual(constraint.length,1)
                subtype=next(iter(arcpy.da.ListSubtypes(str(Path(report['geodatabase'])/dataset)).values()));self.assertEqual(subtype['FieldValues']['WellConstr'][0],'N')
                flags={v for v, in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/dataset),['WellConstr'])};self.assertEqual(flags,{'Y','N'})
            self.assertEqual(report['counts']['EnvSH_Gugg'],5)
            for point,x,y in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/'EnvSH_Gugg'),['SHAPE@','ShlLon','ShlLat']):
                self.assertAlmostEqual(point.firstPoint.X,x);self.assertAlmostEqual(point.firstPoint.Y,y)
            dates=[(p,l) for p,l in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/'EnvLateral_Gugg'),['PermitDate','LastProd']) if p]
            self.assertEqual(dates[0][0].hour,0);self.assertEqual(dates[0][1].day,1)
            self.assertFalse((root/'Shp').exists());self.assertNotIn('shapefileParts',report)
            # Resume an interrupted post-GDB export checkpoint using only cached
            # winners. Preserve core feature IDs and perform no geometry work.
            from ManagedProducts import targets
            from ResumeGeodatabaseCheckpoint import finish
            state=sqlite3.connect(root/'Sqlite/Synthetic/Cache/Processed.sqlite')
            state.execute('ATTACH DATABASE ? AS source',(str(cache),))
            targets(state,[r[0] for r in state.execute('SELECT Origin FROM Winners')],template)
            meta=dict(state.execute('SELECT * FROM ProductMeta'))
            checkpoint=dict(rulesHash=meta['rulesHash'],referenceFingerprint=report['referenceFingerprint'])
            (root/'Json/Config/GdbOnlyCheckpoint.json').write_text(json.dumps(checkpoint))
            state.execute("DELETE FROM Managed WHERE Dataset='EnvSH_Gugg'")
            state.execute("UPDATE SurfaceMeta SET Value='0' WHERE Key='initialized'")
            state.commit();state.close()
            core_ids={n:list(arcpy.da.SearchCursor(str(Path(report['geodatabase'])/n),['RecKey','OID@'])) for n in ['EnvLateral_Gugg','EnvWell_Gugg','EnvWellCentroid_Gugg']}
            arcpy.management.Delete(str(Path(report['geodatabase'])/'EnvSH_Gugg'))
            report=finish(root,cfg)
            self.assertEqual(report['processingCounts']['Recomputed'],0)
            self.assertEqual(report['surfaceHoleChanges']['inserted'],5)
            for name,ids in core_ids.items():self.assertEqual(list(arcpy.da.SearchCursor(str(Path(report['geodatabase'])/name),['RecKey','OID@'])),ids)
            project=arcpy.mp.ArcGISProject(report['project']);self.assertFalse(project.listBrokenDataSources());self.assertTrue(all(str(root) in d['databasePath'] for d in project.databases));self.assertTrue(all(str(root) in t['toolboxPath'] for t in project.toolboxes));del project
            # Check signatures by a second local build; no API is involved.
            cfg['exportShapefiles']=False
            # Output/schedule changes must not invalidate source geometry work.
            cfg['nightly']={'time':'01:00','action':'run'}
            second=build(root,cfg,cache)
            self.assertEqual(second['processingCounts'].get('Recomputed',0),0);self.assertEqual(second['gisWrites'],0);self.assertEqual(second['status'],'SkippedNoChanges')
            # A single changed well updates its canonical row and map attributes,
            # with stable ObjectIDs for every other well.
            cfg['exportShapefiles']=True
            before={k:oid for k,oid in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/'EnvLateral_Gugg'),['RecKey','OID@'])}
            connection=sqlite3.connect(cache);ident=record_id(wells[0]);wells[0]['WellName']='Changed Synthetic Name';connection.execute('UPDATE Wells SET Payload=? WHERE Id=?',(json.dumps(wells[0]),ident));connection.execute('INSERT OR IGNORE INTO DirtyOrigins VALUES(?)',(origin(wells[0]),));connection.commit();connection.close()
            import time
            time.sleep(1)
            changed=build(root,cfg,cache);self.assertEqual(changed['affectedOrigins'],1);self.assertEqual(changed['gdbChanges']['EnvLateral_Gugg']['updated'],1);self.assertEqual(changed['gdbChanges']['EnvWellCentroid_Gugg']['updated'],1)
            self.assertEqual(changed['surfaceHoleChanges']['updated'],1)
            after={k:oid for k,oid in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/'EnvLateral_Gugg'),['RecKey','OID@'])};self.assertEqual(before,after)
            # A source timestamp-only change must cause zero GIS writes.
            connection=sqlite3.connect(cache);wells[0]['UpdatedDate']='2026-10-12T00:00:00Z';connection.execute('UPDATE Wells SET Payload=? WHERE Id=?',(json.dumps(wells[0]),ident));connection.execute('INSERT OR IGNORE INTO DirtyOrigins VALUES(?)',(origin(wells[0]),));connection.commit();connection.close();time.sleep(1)
            unchanged=build(root,cfg,cache);self.assertEqual(unchanged['gisWrites'],0)
            # Retired/cancelled records remove only their own analytical and
            # display rows; unrelated ObjectIDs and features remain intact.
            connection=sqlite3.connect(cache);connection.execute('DELETE FROM Wells WHERE Id=?',(record_id(wells[3]),));connection.execute('INSERT OR IGNORE INTO DirtyOrigins VALUES(?)',(origin(wells[3]),));connection.commit();connection.close();time.sleep(1)
            retired=build(root,cfg,cache);self.assertEqual(retired['affectedOrigins'],1);self.assertEqual(retired['gdbChanges']['EnvLateral_Gugg']['deleted'],1);self.assertEqual(retired['gdbChanges']['EnvWell_Gugg']['deleted'],1)
            self.assertEqual(retired['surfaceHoleChanges']['deleted'],1)
            remaining={k:oid for k,oid in arcpy.da.SearchCursor(str(Path(report['geodatabase'])/'EnvLateral_Gugg'),['RecKey','OID@'])};self.assertEqual(len(remaining),len(before)-1);self.assertTrue(all(before[k]==oid for k,oid in remaining.items()))
            # Transfer the managed GIS state too: a new machine must not need a
            # national geometry rebuild when its inputs have not changed.
            from RuntimeTransfer import export_runtime,import_runtime
            transfer=export_runtime(root,cfg,part_bytes=4096)
            manifest=json.loads(Path(transfer['manifest']).read_text());self.assertFalse(any(f['role']=='managedShapefile' for f in manifest['files']))
            relocated=root/'MovedInstallation'
            for name in ['Py','Json/Config','Gdb/Reference','Aprx/Template','Atbx']:shutil.copytree(source_root/name,relocated/name,ignore=shutil.ignore_patterns('__pycache__','*.lock'))
            # Relocation carries the exact same references, including test rows.
            arcpy.management.Delete(str(relocated/'Gdb/Reference/GuggenheimReference.gdb'))
            arcpy.management.ClearWorkspaceCache(str(ref))
            shutil.copytree(ref,relocated/'Gdb/Reference/GuggenheimReference.gdb',ignore=shutil.ignore_patterns('*.lock'))
            imported=import_runtime(relocated,cfg,transfer['manifest']);self.assertTrue(imported['includesGIS'])
            # Git may normalize source line endings on the work computer.
            code=relocated/'Py/Identity.py';code.write_text(code.read_text(),newline='\n')
            moved=build(relocated,cfg,relocated/'Sqlite/Synthetic/Cache/EnverusCache.sqlite');self.assertEqual(moved['gisWrites'],0);self.assertEqual(moved['processingCounts'].get('Recomputed',0),0)
            moved_project=arcpy.mp.ArcGISProject(moved['project']);self.assertFalse(moved_project.listBrokenDataSources());self.assertTrue(all(str(relocated) in d['databasePath'] for d in moved_project.databases));del moved_project
            gc.collect();arcpy.management.ClearWorkspaceCache()

if __name__=='__main__':unittest.main()
