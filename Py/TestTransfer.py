"""Synthetic split-cache export/import and corruption checks."""
import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from SourceCache import initialize
from CacheTransfer import export_cache,import_cache
class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'A';self.other=Path(self.temp.name)/'B';self.cfg=dict(profile='Synthetic',apiFilters={},minimumFreeDiskGb=0)
        p=self.root/'Sqlite/Synthetic/Cache';p.mkdir(parents=True);db=sqlite3.connect(p/'EnverusCache.sqlite');initialize(db);db.executemany('INSERT INTO Meta VALUES(?,?)',[('watermark','2026-11-01T00:00:00+00:00'),('scope','{}')]);db.execute('CREATE TABLE SyntheticBytes(Value BLOB)');db.execute('INSERT INTO SyntheticBytes VALUES(?)',(os.urandom(20000),));db.commit();db.close()
    def tearDown(self):self.temp.cleanup()
    def test_round_trip_preserves_watermark_and_uses_small_parts(self):
        r=export_cache(self.root,self.cfg,512);m=json.loads(Path(r['manifest']).read_text());self.assertGreater(len(m['parts']),1);self.assertTrue(all(p['size']<=512 for p in m['parts']));out=import_cache(self.other,self.cfg,r['manifest']);self.assertEqual(out['nextSync'],'incremental');self.assertEqual(out['watermark'],m['watermark'])
    def test_corrupt_part_is_rejected_before_install(self):
        r=export_cache(self.root,self.cfg,512);m=json.loads(Path(r['manifest']).read_text());part=Path(r['manifest']).parent/m['parts'][0]['name'];part.write_bytes(b'bad')
        with self.assertRaises(RuntimeError):import_cache(self.other,self.cfg,r['manifest'])
        self.assertFalse((self.other/'Sqlite/Synthetic/Cache/EnverusCache.sqlite').exists())
    def test_scope_mismatch_is_rejected(self):
        r=export_cache(self.root,self.cfg,512)
        with self.assertRaises(RuntimeError):import_cache(self.other,dict(self.cfg,apiFilters={'country':'CA'}),r['manifest'])
if __name__=='__main__':unittest.main()
