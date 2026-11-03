import gc,json,tempfile,unittest,sqlite3
from pathlib import Path
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy needed')
class SubsetTests(unittest.TestCase):
    def test_subset_preserves_whole_geometries_and_never_uploads(self):
        from AgolSubset import prepare,WELLS
        from WellGeometry import SR
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);ref=root/'Gdb/Reference';ref.mkdir(parents=True);arcpy.management.CreateFileGDB(str(ref),'Reference.gdb');basins=ref/'Reference.gdb/Basins';arcpy.management.CreateFeatureclass(str(basins.parent),'Basins','POLYGON',spatial_reference=SR);arcpy.management.AddField(str(basins),'GuggGisBsn','TEXT',field_length=20)
            with arcpy.da.InsertCursor(str(basins),['GuggGisBsn','SHAPE@']) as c:c.insertRow(['A',arcpy.FromWKT('POLYGON((-104 31.9,-103.95 31.9,-103.95 32.1,-104 32.1,-104 31.9))',SR)])
            out=root/'Gdb/Test/Output';out.mkdir(parents=True)
            for name in ['EnverusGuggWellRecord.gdb','EnverusContext.gdb']:arcpy.management.CreateFileGDB(str(out),name)
            original=arcpy.FromWKT('LINESTRING(-104.02 32,-103.9 32)',SR)
            for name in WELLS:
                fc=out/'EnverusGuggWellRecord.gdb'/name;kind='POINT' if name in ['EnvSH_Gugg','EnvWellCentroid_Gugg'] else 'POLYLINE';arcpy.management.CreateFeatureclass(str(fc.parent),name,kind,spatial_reference=SR);arcpy.management.AddField(str(fc),'GuggGisBsn','TEXT',field_length=20)
                shape=arcpy.PointGeometry(arcpy.Point(-103.97,32),SR) if kind=='POINT' else original
                with arcpy.da.InsertCursor(str(fc),['GuggGisBsn','SHAPE@']) as c:c.insertRow(['A',shape]);c.insertRow(['B',shape])
            fc=out/'EnverusContext.gdb/EnvPipelines';arcpy.management.CreateFeatureclass(str(fc.parent),fc.name,'POLYLINE',spatial_reference=SR)
            with arcpy.da.InsertCursor(str(fc),['SHAPE@']) as c:c.insertRow([original])
            (root/'Json/Config').mkdir(parents=True);(root/'Json/Config/ContextLayers.json').write_text(json.dumps(dict(outputGeodatabase='EnverusContext.gdb',layers=[dict(featureClass='EnvPipelines',enabled=True)])))
            # Completed-source markers prevent publishing a paused partial build.
            state=root/'Sqlite/Test/Cache/Processed.sqlite';state.parent.mkdir(parents=True)
            db=sqlite3.connect(state);db.executescript("CREATE TABLE ProductMeta(Key TEXT PRIMARY KEY,Value TEXT);INSERT INTO ProductMeta VALUES('initialized','1');CREATE TABLE SurfaceMeta(Key TEXT PRIMARY KEY,Value TEXT);INSERT INTO SurfaceMeta VALUES('initialized','1');");db.close()
            db=sqlite3.connect(state.with_name('EnverusCache.sqlite'));db.execute('CREATE TABLE DirtyOrigins(Origin TEXT PRIMARY KEY)');db.commit();db.close()
            settings=json.loads((root/'Json/Config/ContextLayers.json').read_text());settings['layers'][0]['dataset']='pipelines';(root/'Json/Config/ContextLayers.json').write_text(json.dumps(settings))
            cache=root/'Sqlite/Test/Context/pipelines.sqlite';cache.parent.mkdir(parents=True);db=sqlite3.connect(cache);db.execute('CREATE TABLE Dirty(Id TEXT PRIMARY KEY)');db.commit();db.close()
            cfg=dict(profile='Test',scope=dict(featureClass='Gdb/Reference/Reference.gdb/Basins',nameField='GuggGisBsn',wellFieldName='GuggGisBsn'))
            report=prepare(root,cfg);self.assertEqual(report['status'],'ReadyForSizeReview');self.assertFalse(report['uploaded']);self.assertFalse(report['published']);self.assertTrue(all(r['features']==1 for r in report['layers']))
            selected=next(arcpy.da.SearchCursor(str(Path(report['stagingGeodatabase'])/'EnvLateral_Gugg'),['SHAPE@']))[0];self.assertTrue(original.equals(selected));self.assertGreater(report['stagingBytes'],0)
            cfg['awaitUserQualityControl']=True;held=prepare(root,cfg);self.assertEqual(held['status'],'AwaitingUserQualityControl');self.assertFalse(held['published'])
            gc.collect();arcpy.management.ClearWorkspaceCache()

if __name__=='__main__':unittest.main()
