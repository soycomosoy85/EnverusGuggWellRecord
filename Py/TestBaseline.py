"""Synthetic baseline interruption/resume test; no API account or well data."""
import tempfile,sqlite3,unittest
from pathlib import Path
from TestCache import FakeApi,fake_well
from BaselineCache import baseline
class PagedFake(FakeApi):
    def pages(self,dataset,params,metadata=False,start_url=None,checkpoint=None):
        for data in super().pages(dataset,params,metadata):
            if checkpoint:checkpoint(data,None)
            yield data
class BaselineTests(unittest.TestCase):
    def test_resume_preserves_completed_wells_and_refreshes_remaining_bores(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'Cache.sqlite';api=PagedFake([fake_well('001','00100'),fake_well('002','00200')]);cfg=dict(apiFilters={},surveyBatchSize=1,workers=1,minimumFreeDiskGb=0,_testSerial=True)
            api.fail=True
            with self.assertRaises(RuntimeError):baseline(api,path,cfg,['WellName'])
            self.assertFalse(path.exists());self.assertTrue(path.with_name('BaselinePending.sqlite').exists());first=api.full_downloads
            api.fail=False;r=baseline(api,path,cfg,['WellName']);self.assertTrue(path.exists());self.assertEqual(api.full_downloads,first);self.assertEqual(r['eligibleWells'],2)
            db=sqlite3.connect(path);self.assertIn('watermark',dict(db.execute('SELECT * FROM Meta')));db.close()
if __name__=='__main__':unittest.main()
