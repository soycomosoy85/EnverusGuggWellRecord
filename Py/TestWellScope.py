import json,sqlite3,tempfile,unittest
from pathlib import Path
from SourceCache import initialize
from ReconcileWellScope import reconcile
from WellScope import excluded,EXCLUDED_STATUS_VALUES


class WellScopeTests(unittest.TestCase):
    def test_cached_aliases_are_removed_and_origins_queued(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'Cache.sqlite';db=sqlite3.connect(path);initialize(db)
            statuses=list(EXCLUDED_STATUS_VALUES)+['PERMITTED','PERMIT PENDING APPROVAL',None]
            for index,status in enumerate(statuses):db.execute('INSERT INTO Wells VALUES(?,?,?,?,?)',(str(index),str(index),str(index),'now',json.dumps(dict(ENVWellStatus=status))))
            db.commit();db.close();report=reconcile(path)
            self.assertEqual(report['removedFromScope'],len(EXCLUDED_STATUS_VALUES))
            db=sqlite3.connect(path)
            self.assertEqual(db.execute('SELECT count(*) FROM Wells').fetchone()[0],3)
            self.assertEqual(db.execute('SELECT count(*) FROM DirtyOrigins').fetchone()[0],len(EXCLUDED_STATUS_VALUES));db.close()
            self.assertTrue(excluded(' expired permit '));self.assertFalse(excluded(None))


if __name__=='__main__':unittest.main()
