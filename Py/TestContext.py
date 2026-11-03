import json,sqlite3,tempfile,unittest
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from ContextSync import sync,pages,BASE

class FakeApi:
    def __init__(self,rows):self.rows=rows;self.fullReads=0;self.fail=False
    def count(self,*args):return len(self.rows)
    def request(self,url):
        params=parse_qs(urlparse(url).query);rows=self.rows
        if 'fields' in params:rows=[{k:r.get(k) for k in params['fields'][0].split(',')} for r in rows]
        else:
            if self.fail:raise RuntimeError('Synthetic network failure')
            self.fullReads+=len(rows)
            if 'uniqueid' in params:
                ids=params['uniqueid'][0][3:-1].split(',');rows=[r for r in rows if str(r['UniqueID']) in ids]
        return rows,{}

class ContextTests(unittest.TestCase):
    def test_null_timestamp_records_are_refreshed_each_run(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'context.sqlite';api=FakeApi([dict(UniqueID='A',UpdatedDate=None,Name='Old')]);layer=dict(dataset='pipelines',idField='UniqueID');cfg=dict(minimumFreeDiskGb=0)
            sync(api,path,layer,cfg);api.rows[0]['Name']='New';again=sync(api,path,layer,cfg);self.assertEqual(again['fullRecordsDownloaded'],1)
            db=sqlite3.connect(path);self.assertEqual(json.loads(db.execute('SELECT Payload FROM Records').fetchone()[0])['Name'],'New');db.close()
    def test_baseline_changes_noop_and_roster_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'context.sqlite';layer=dict(dataset='pipelines',idField='UniqueID');cfg=dict(minimumFreeDiskGb=0,maximumAutomaticRemovalFraction=1)
            api=FakeApi([dict(UniqueID='A',UpdatedDate='2026-11-01',Name='First'),dict(UniqueID='B',UpdatedDate='2026-11-01',Name='Second')])
            first=sync(api,path,layer,cfg);self.assertEqual(first['liveRecords'],2)
            before=api.fullReads;second=sync(api,path,layer,cfg);self.assertEqual(second['fullRecordsDownloaded'],0);self.assertEqual(api.fullReads,before)
            api.rows=[dict(UniqueID='A',UpdatedDate='2026-11-02',Name='Changed')];third=sync(api,path,layer,cfg);self.assertEqual(third['removedRecords'],1)
            db=sqlite3.connect(path);self.assertEqual(json.loads(db.execute('SELECT Payload FROM Records').fetchone()[0])['Name'],'Changed');self.assertEqual(db.execute('SELECT count(*) FROM Records').fetchone()[0],1);db.close()

    def test_failed_payload_retrieval_preserves_previous_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'context.sqlite';layer=dict(dataset='pipelines',idField='UniqueID');cfg=dict(minimumFreeDiskGb=0)
            api=FakeApi([dict(UniqueID='A',UpdatedDate='old')]);sync(api,path,layer,cfg);api.rows=[dict(UniqueID='A',UpdatedDate='new')];api.fail=True
            with self.assertRaises(RuntimeError):sync(api,path,layer,cfg)
            db=sqlite3.connect(path);self.assertEqual(db.execute('SELECT Updated FROM Records').fetchone()[0],'old');db.close()

    def test_duplicate_source_identifier_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            row=dict(UniqueID='A',UpdatedDate='old');api=FakeApi([row,row])
            with self.assertRaisesRegex(RuntimeError,'not unique'):sync(api,Path(folder)/'x.sqlite',dict(dataset='pipelines',idField='UniqueID'),dict(minimumFreeDiskGb=0))

    def test_non_well_pagination_preserves_filters_without_well_status(self):
        class Paging:
            calls=[]
            def request(self,url):
                self.calls.append(url)
                return ([{}],{'Link':'</v3/direct-access/pipelines?offset=1>; rel="next"'}) if len(self.calls)==1 else ([{}],{})
        api=Paging();list(pages(api,'pipelines',{'deleteddate':'null','fields':'UniqueID'}));last=parse_qs(urlparse(api.calls[-1]).query)
        self.assertEqual(last['deleteddate'],['null']);self.assertEqual(last['fields'],['UniqueID']);self.assertNotIn('envwellstatus',last)

if __name__=='__main__':unittest.main()
