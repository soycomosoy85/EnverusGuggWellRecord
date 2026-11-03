import json,sqlite3,tempfile,unittest,gc
from pathlib import Path
try:import arcpy
except ImportError:arcpy=None
from ContextSync import sync
from TestContext import FakeApi

@unittest.skipIf(arcpy is None,'Licensed ArcPy needed')
class ContextGisTests(unittest.TestCase):
    def test_updates_and_removals_preserve_other_feature_ids(self):
        from ContextProducts import build
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            root=Path(folder);(root/'Json/ApiSchema').mkdir(parents=True);(root/'Json/Config').mkdir(parents=True)
            names=['UniqueID','UpdatedDate','SystemName','Geom_Line'];(root/'Json/ApiSchema/pipelinesDocs.json').write_text(json.dumps([dict(name=n) for n in names]));(root/'Json/Config/ContextFieldTypes.json').write_text('{}')
            layer=dict(dataset='pipelines',idField='UniqueID',featureClass='EnvPipelines',geometryType='POLYLINE',geometryFields=['Geom_Line']);cfg=dict(profile='Synthetic',outputGeodatabase='EnverusContext.gdb',minimumFreeDiskGb=0,maximumAutomaticRemovalFraction=1)
            cache=root/'Sqlite/Synthetic/Context/pipelines.sqlite';rows=[dict(UniqueID='00001',UpdatedDate='2026-11-01',SystemName='One',Geom_Line='LINESTRING(-104 32,-103.99 32)'),dict(UniqueID='00002',UpdatedDate='2026-11-01',SystemName='Two',Geom_Line='LINESTRING(-104 33,-103.99 33)')];api=FakeApi(rows)
            sync(api,cache,layer,cfg);first=build(root,cache,layer,cfg);self.assertEqual(first['features'],2);self.assertEqual(first['gisWrites'],2)
            before={ident:oid for ident,oid in arcpy.da.SearchCursor(first['featureClass'],['SrcId','OID@'])};self.assertIn('00001',before)
            sync(api,cache,layer,cfg);self.assertEqual(build(root,cache,layer,cfg)['gisWrites'],0)
            rows[0].update(UpdatedDate='2026-11-02',SystemName='Changed');sync(api,cache,layer,cfg);changed=build(root,cache,layer,cfg);self.assertEqual(changed['changes']['updated'],1)
            after={ident:oid for ident,oid in arcpy.da.SearchCursor(first['featureClass'],['SrcId','OID@'])};self.assertEqual(before,after)
            api.rows=rows[:1];sync(api,cache,layer,cfg);removed=build(root,cache,layer,cfg);self.assertEqual(removed['changes']['deleted'],1);self.assertEqual(removed['features'],1)
            self.assertTrue(all(len(f.name)<=10 for f in arcpy.ListFields(first['featureClass']) if not f.required))
            gc.collect();arcpy.management.ClearWorkspaceCache()

if __name__=='__main__':unittest.main()
