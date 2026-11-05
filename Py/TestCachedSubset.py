import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from BuildCachedSubset import prepare
from SourceCache import initialize


class CachedSubsetTests(unittest.TestCase):
    def test_snapshot_filters_states_and_reuses_only_selected_calculations(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'Source';output=root/'Delivery'
            for name in ['Py','Aprx/Template','Atbx','Gdb/Reference','Json/Config','Sqlite/NorthAmerica/Cache']:
                (source/name).mkdir(parents=True,exist_ok=True)
            for name in ['HeaderSchema.json','FieldDictionary.json','WellRecordRules.json']:
                (source/'Json/Config'/name).write_text('{}')
            (source/'Json/Config/Workflow.json').write_text(json.dumps(dict(profile='NorthAmerica')))
            base=source/'Sqlite/NorthAmerica/Cache';db=sqlite3.connect(base/'EnverusCache.sqlite');initialize(db)
            for state in ['TX','NM','OK']:
                db.execute('INSERT INTO Wells VALUES(?,?,?,?,?)',(state,state,state,'now',json.dumps(dict(StateProvince=state))))
                db.execute('INSERT INTO Stations VALUES(?,?,?)',(state,1,'{}'))
                db.execute('INSERT INTO BoreVersions VALUES(?,?)',(state,'v1'))
            db.execute('INSERT INTO Meta VALUES(?,?)',('watermark','baseline'));db.commit();db.close()
            db=sqlite3.connect(base/'Processed.sqlite')
            db.execute('CREATE TABLE Results(Id TEXT PRIMARY KEY,Origin TEXT,Signature TEXT,Layer TEXT,Attrs TEXT,Geom TEXT,Geom3 TEXT)')
            for state in ['TX','NM','OK']:db.execute('INSERT INTO Results VALUES(?,?,?,?,?,?,?)',(state,state,'signature','Line','{}','geometry',None))
            db.commit();db.close()
            config=prepare(source,output);self.assertEqual(config['profile'],'TexasNewMexico')
            self.assertFalse(config['exportShapefiles'])
            base=output/'Sqlite/TexasNewMexico/Cache'
            with closing(sqlite3.connect(base/'EnverusCache.sqlite')) as db:
                self.assertEqual(set(r[0] for r in db.execute('SELECT Id FROM Wells')),{'TX','NM'})
                self.assertEqual(set(r[0] for r in db.execute('SELECT Api FROM Stations')),{'TX','NM'})
            with closing(sqlite3.connect(base/'Processed.sqlite')) as db:
                self.assertEqual(set(r[0] for r in db.execute('SELECT Id FROM Results')),{'TX','NM'})
            self.assertEqual(prepare(source,output)['profile'],'TexasNewMexico')
            with closing(sqlite3.connect(source/'Sqlite/NorthAmerica/Cache/EnverusCache.sqlite')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM Wells').fetchone()[0],3)


if __name__=='__main__':unittest.main()
