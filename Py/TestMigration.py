import json,sqlite3,tempfile,unittest
from pathlib import Path
from MigrateProducts import migrate
try:import arcpy
except ImportError:arcpy=None

class MigrationTests(unittest.TestCase):
    def test_missing_header_expansion_stops_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Json/Config').mkdir(parents=True);(root/'Json/Config/HeaderSchema.json').write_text(json.dumps({'fields':[{'directApiField':'PeakOil_BBL'}]}));cache=root/'Sqlite/Test/Cache';cache.mkdir(parents=True)
            db=sqlite3.connect(cache/'EnverusCache.sqlite');db.execute('CREATE TABLE Meta(Key TEXT PRIMARY KEY,Value TEXT)');db.commit();db.close()
            with self.assertRaisesRegex(RuntimeError,'backfilled'):migrate(root,{'profile':'Test'})

    @unittest.skipIf(arcpy is None,'ArcPy required for managed product initialization')
    def test_migration_preserves_sources_and_archives_old_registry(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Json/Config').mkdir(parents=True);(root/'Json/Config/HeaderSchema.json').write_text(json.dumps({'fields':[{'directApiField':'PeakOil_BBL'}]}));cache=root/'Sqlite/Test/Cache';cache.mkdir(parents=True)
            db=sqlite3.connect(cache/'EnverusCache.sqlite');db.execute('CREATE TABLE Meta(Key TEXT PRIMARY KEY,Value TEXT)');db.execute('INSERT INTO Meta VALUES(?,?)',('headerFields','["PeakOil_BBL"]'));db.commit();db.close()
            db=sqlite3.connect(cache/'Processed.sqlite');db.execute('CREATE TABLE ProductMeta(Key TEXT PRIMARY KEY,Value TEXT)');db.execute("INSERT INTO ProductMeta VALUES('schema','old')");db.execute('CREATE TABLE Results(Id TEXT)');db.execute("INSERT INTO Results VALUES('keep')");db.commit();db.close()
            self.assertEqual(migrate(root,{'profile':'Test'})['status'],'ReadyForThreeProductBuild');self.assertEqual(migrate(root,{'profile':'Test'})['status'],'AlreadyMigrated')
            db=sqlite3.connect(cache/'Processed.sqlite');self.assertEqual(db.execute('SELECT Id FROM Results').fetchone()[0],'keep');self.assertTrue(db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'ProductMetaPrevious%'").fetchone());db.close()

if __name__=='__main__':unittest.main()
