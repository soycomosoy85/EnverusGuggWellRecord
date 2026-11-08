import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


class ConstraintUpgradeTests(unittest.TestCase):
    def test_existing_outputs_upgrade_without_geometry_or_signature_changes(self):
        import arcpy
        from ManagedProducts import initialize
        from UpgradeWellAttributes import upgrade_if_needed,schema_signature,DATASETS,feature_check
        from WellGeometry import SR
        source=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='ConstraintUpgrade',ignore_cleanup_errors=True) as folder:
            root=Path(folder);config=dict(profile='Test')
            (root/'Json/Config').mkdir(parents=True)
            (root/'Json/Config/WellConstraintStatus.Local.json').write_text(json.dumps(dict(mapping={'PRODUCING':'PDP','PERMITTED':'PERMIT'})))
            shutil.copytree(source/'Aprx/Template',root/'Aprx/Template')
            out=root/'Gdb/Test/Output';out.mkdir(parents=True);gdb=out/'EnverusGuggWellRecord.gdb';arcpy.management.CreateFileGDB(str(out),gdb.name)
            old=[dict(fieldName=n,internalField=n,alias=a,exportType='TEXT',textLength=w) for n,a,w in [('Trajectory','Trajectory',32),('EnvStatus','ENV Well Status',32),('WellConstr','Well Constraint',1),('RecKey','Internal Key',32)]]
            fields=old[:-1]+[dict(fieldName='WelCnsStat',internalField='WelCnsStat',alias='Well Constraint Status',exportType='TEXT',textLength=6)]+old[-1:]
            db=sqlite3.connect(':memory:');initialize(db)
            db.execute('CREATE TABLE Results(Id TEXT PRIMARY KEY,Signature TEXT)');db.execute("INSERT INTO Results VALUES('cached','unchanged')")
            db.executemany('INSERT INTO ProductMeta VALUES(?,?)',[('schema',schema_signature(old)),('initialized','1'),('rulesHash','original-geometry-rules')]);db.commit()
            before={}
            values=[('HORIZONTAL','PRODUCING','Y','a'),('UNDETERMINED','PERMITTED','Y','b'),('DIRECTIONAL','UNLISTED','Y','c'),('VERTICAL','PRODUCING','Y','d')]
            for dataset in DATASETS:
                kind='POLYLINE' if dataset in DATASETS[:2] else 'POINT';path=gdb/dataset
                arcpy.management.CreateFeatureclass(str(gdb),dataset,kind,spatial_reference=SR)
                for field in old:arcpy.management.AddField(str(path),field['fieldName'],'TEXT',field_length=field['textLength'],field_alias=field['alias'])
                shape=arcpy.FromWKT('LINESTRING(-104 32,-103.99 32)',SR) if kind=='POLYLINE' else arcpy.PointGeometry(arcpy.Point(-104,32),SR)
                with arcpy.da.InsertCursor(str(path),['SHAPE@']+[f['fieldName'] for f in old]) as cursor:
                    for row in values:
                        oid=cursor.insertRow([shape]+list(row));db.execute('INSERT INTO Managed VALUES(?,?,?,?,?)',(dataset,row[-1],row[-1],'old-hash',oid))
                before[dataset]=feature_check(path)
            report=upgrade_if_needed(root,config,db,fields)
            self.assertTrue(report['validation']['passed']);self.assertEqual(report['geometryRecomputations'],0)
            for dataset in DATASETS:
                after=feature_check(gdb/dataset)
                self.assertEqual((after['count'],after['geometryChecksum']),(before[dataset]['count'],before[dataset]['geometryChecksum']))
                columns=[f.name for f in arcpy.ListFields(str(gdb/dataset))];self.assertEqual(columns.index('WelCnsStat'),columns.index('WellConstr')+1)
                with arcpy.da.SearchCursor(str(gdb/dataset),['RecKey','WellConstr','WelCnsStat']) as rows:
                    result={r[0]:r[1:] for r in rows}
                self.assertEqual(result['a'],('Y','PDP'));self.assertEqual(result['b'],('N','PERMIT'));self.assertEqual(result['c'],('Y',None));self.assertEqual(result['d'],('N','PDP'))
            self.assertEqual(db.execute('SELECT Signature FROM Results').fetchone()[0],'unchanged')
            self.assertEqual(dict(db.execute('SELECT * FROM ProductMeta'))['rulesHash'],'original-geometry-rules')
            self.assertIsNone(upgrade_if_needed(root,config,db,fields))
            db.close();arcpy.management.ClearWorkspaceCache()


if __name__=='__main__':unittest.main()
