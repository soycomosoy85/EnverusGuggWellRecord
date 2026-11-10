"""Synthetic regression cases; contains no downloaded Enverus well data."""
import copy,json,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from Identity import record_id,origin
from SourceCache import sync

def fake_well(name,bore,country='US',status='PRODUCING',updated='2026-10-01T00:00:00Z'):
    return dict(API_UWI=name,API_UWI_Unformatted=name,API_UWI_14_Unformatted=name+'0000' if country=='US' else None,API_UWI_12_Unformatted=bore,Country=country,WellID=name,CompletionID=name,ENVWellStatus=status,UpdatedDate=updated,DeletedDate=None,WellName='Synthetic Test Only')

class FakeApi:
    def __init__(self,wells):self.wells=wells;self.headers={};self.stations={};self.events=[];self.fail=False;self.allow=lambda ids:False;self.full_downloads=0
    def count(self,dataset,params):
        status=params.get('envwellstatus')
        from WellScope import EXCLUDED_STATUS_FILTER,excluded
        if status==EXCLUDED_STATUS_FILTER:return sum(excluded(w['ENVWellStatus']) for w in self.wells)
        if status=='null':return sum(w['ENVWellStatus'] is None for w in self.eligible())
        return sum(w['ENVWellStatus'] is not None for w in self.eligible()) if status else len(self.wells)
    def eligible(self):
        from WellScope import excluded
        return [w for w in self.wells if not w.get('DeletedDate') and not excluded(w['ENVWellStatus'])]
    def pages(self,dataset,params,metadata=False):
        expr=params.get('api_uwi_12_unformatted');ids=expr[3:-1].split(',') if expr else None
        if dataset=='wells':
            rows=[copy.deepcopy(w) for w in self.eligible() if ids is None or w['API_UWI_12_Unformatted'] in ids]
            rows=[w for w in rows if (w['ENVWellStatus'] is None)==(params.get('envwellstatus')=='null')]
            fields=params.get('fields','').split(',')
            if 'WellName' in fields:self.full_downloads+=len(rows)
            yield [{k:w.get(k) for k in fields} for w in rows];return
        if self.fail and not metadata:raise RuntimeError('Synthetic network interruption')
        if metadata:
            rows=[r for r in self.events if ids is None or r['API_UWI_12_Unformatted'] in ids]
            for param,field in [('updateddate','UpdatedDate'),('deleteddate','DeletedDate')]:
                if param in params:rows=[r for r in rows if str(r.get(field) or '')>=params[param][3:-1]]
            yield rows;return
        rows=[]
        for bore in ids or []:rows.extend(self.headers.get(bore,[]) if dataset=='header-directional-surveys' else self.stations.get(bore,[]))
        yield copy.deepcopy(rows)

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'Cache.sqlite';self.config=dict(apiFilters={},lookbackDays=3,surveyBatchSize=2,workers=1,surveyChangeScan='ScopedMetadata',maximumAutomaticRemovalFraction=1.0,_testSerial=True)
        self.api=FakeApi([fake_well('001','00100'),fake_well('002','00200'),fake_well('CAUWIFULL1601','CAUWIFULL1601','CA')])
        self.api.stations['00100']=[dict(API_UWI_12_Unformatted='00100',StationNumber=1),dict(API_UWI_12_Unformatted='00100',StationNumber=2)]
        self.time=datetime(2026,10,10,tzinfo=timezone.utc)
    def tearDown(self):self.temp.cleanup()
    def call(self):return sync(self.api,self.path,self.config,['WellName'],now=self.time)
    def test_baseline_and_unchanged_refresh(self):
        a=self.call();b=self.call();self.assertTrue(a['baseline']);self.assertFalse(b['baseline']);self.assertEqual(b['fullWellPayloadsDownloaded'],0);self.assertEqual(b['surveyWellboresRefreshed'],0)
    def test_changed_well_only(self):
        self.call();self.api.wells[1]['UpdatedDate']='2026-10-11T00:00:00Z';self.api.wells[1]['WellName']='Changed Synthetic';r=self.call();self.assertEqual(r['fullWellPayloadsDownloaded'],1);self.assertEqual(r['surveyWellboresRefreshed'],1)
    def clear_dirty_and_snapshot(self):
        from contextlib import closing
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('DELETE FROM DirtyOrigins');db.commit()
            return list(db.execute('SELECT Id,Payload FROM Wells ORDER BY Id')),list(db.execute('SELECT * FROM BoreVersions ORDER BY Api'))
    def test_vendor_timestamp_only_refresh_does_not_dirty_features(self):
        from contextlib import closing
        self.call();before=self.clear_dirty_and_snapshot()
        self.api.wells[0]['UpdatedDate']='2026-10-11T00:00:00Z'
        r=self.call();self.assertEqual(r['wellContentChanged'],0);self.assertEqual(r['surveyContentChanged'],0)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM DirtyOrigins').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT Updated FROM Wells WHERE Id=?',(record_id(self.api.wells[0]),)).fetchone()[0],self.api.wells[0]['UpdatedDate'])
        self.assertEqual(self.clear_dirty_and_snapshot(),before)
        self.assertEqual(self.call()['fullWellPayloadsDownloaded'],0)
    def test_identical_survey_event_and_order_does_not_invalidate_geometry(self):
        from contextlib import closing
        self.call();before=self.clear_dirty_and_snapshot()
        self.api.events=[dict(API_UWI_12_Unformatted='00100',UpdatedDate='2026-10-11')]
        self.api.stations['00100'].reverse()
        for row in self.api.stations['00100']:row['UpdatedDate']='2026-10-11'
        r=self.call();self.assertEqual(r['surveyWellboresRefreshed'],1);self.assertEqual(r['surveyContentChanged'],0)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(db.execute('SELECT count(*) FROM DirtyOrigins').fetchone()[0],0)
        self.assertEqual(self.clear_dirty_and_snapshot(),before)
    def test_real_status_and_survey_edit_remain_dirty(self):
        from contextlib import closing
        self.call();self.clear_dirty_and_snapshot()
        self.api.wells[0].update(UpdatedDate='2026-10-11',ENVWellStatus='PERMITTED')
        self.api.stations['00100'][0]['Longitude']=-104.1
        r=self.call();self.assertEqual(r['wellContentChanged'],1);self.assertEqual(r['surveyContentChanged'],1)
        with closing(sqlite3.connect(self.path)) as db:self.assertEqual(list(db.execute('SELECT Origin FROM DirtyOrigins')),[(origin(self.api.wells[0]),)])
    def test_status_exit_and_disappearance_removed(self):
        self.call();self.api.wells[0]['ENVWellStatus']='PERMIT CANCELLED';self.api.wells.pop(1);r=self.call();self.assertEqual(r['removedFromScope'],2)
        d=sqlite3.connect(self.path);self.assertEqual(d.execute('SELECT count(*) FROM Wells').fetchone()[0],1);d.close();self.assertEqual(r['fullWellPayloadsDownloaded'],0)
    def test_station_only_deletion_replaces_bore(self):
        self.call();self.api.events=[dict(API_UWI_12_Unformatted='00100',UpdatedDate='2026-10-11',DeletedDate='2026-10-11')];self.api.stations['00100']=self.api.stations['00100'][:1];r=self.call();self.assertEqual(r['fullWellPayloadsDownloaded'],0);self.assertEqual(r['surveyWellboresRefreshed'],1)
        d=sqlite3.connect(self.path);self.assertEqual(d.execute("SELECT count(*) FROM Stations WHERE Api='00100'").fetchone()[0],1);d.close()
    def test_failure_does_not_advance_watermark_or_change_cache(self):
        self.call();before=self.path.read_bytes();self.api.events=[dict(API_UWI_12_Unformatted='00100',UpdatedDate='2026-10-11',DeletedDate=None)];self.api.fail=True
        with self.assertRaises(RuntimeError):self.call()
        self.assertEqual(self.path.read_bytes(),before)
        from ProcessLock import ProcessLock
        with ProcessLock(self.path.with_suffix('.lock')):pass
    def test_canadian_uwi_not_truncated_and_country_separates_origins(self):
        a=fake_well('111101604922W302','111101604922W302','CA');self.assertIn('111101604922W302',origin(a));self.assertNotEqual(origin(a),origin(dict(a,Country='US')));self.assertIn('111101604922W302',record_id(a))
    def test_excluded_permits_never_cached_and_pending_kept(self):
        self.api.wells.extend([fake_well('003','00300',status='PERMIT EXPIRED'),fake_well('004','00400',status='PERMIT PENDING APPROVAL')]);r=self.call();self.assertEqual(r['eligibleWells'],4)
        d=sqlite3.connect(self.path);payload=[json.loads(p) for p, in d.execute('SELECT Payload FROM Wells')];d.close();self.assertFalse(any(w['ENVWellStatus']=='PERMIT EXPIRED' for w in payload));self.assertTrue(any(w['ENVWellStatus']=='PERMIT PENDING APPROVAL' for w in payload))
    def test_deleted_timestamp_catches_unchanged_updated_timestamp(self):
        self.call();self.api.events=[dict(API_UWI_12_Unformatted='00100',UpdatedDate='2020-01-01',DeletedDate='2026-10-11')];self.api.stations['00100']=[];r=self.call();self.assertEqual(r['surveyWellboresRefreshed'],1)
        d=sqlite3.connect(self.path);self.assertEqual(d.execute("SELECT count(*) FROM Stations WHERE Api='00100'").fetchone()[0],0);d.close()
    def test_manual_survey_reconciliation_does_not_refetch_wells(self):
        self.call();self.config['forceSurveyRefresh']=True;r=self.call();self.assertEqual(r['surveyWellboresRefreshed'],3);self.assertEqual(r['fullWellPayloadsDownloaded'],0)
    def test_scope_change_requires_a_new_profile(self):
        self.call();before=self.path.read_bytes();self.config['apiFilters']={'envbasin':'SYNTHETIC'}
        with self.assertRaises(RuntimeError):self.call()
        self.assertEqual(self.path.read_bytes(),before)
    def test_usable_point_precedes_missing_geometry(self):
        from Selection import choose
        rows=[dict(key='A',layer='NoLocation',a=dict(Api12='A',EnvStatus='PRODUCING')),dict(key='B',layer='Point',a=dict(Api12='B',EnvStatus='INACTIVE PRODUCER'))]
        self.assertEqual(choose(rows)[0]['key'],'B')
    def test_null_status_is_retained_and_transitions_are_reconciled(self):
        self.api.wells.append(fake_well('005','00500',status=None));r=self.call();self.assertEqual(r['eligibleWells'],4);self.assertEqual(r['unknownStatusWells'],1)
        self.api.wells[-1].update(ENVWellStatus='PRODUCING',UpdatedDate='2026-10-11T00:00:00Z');r=self.call();self.assertEqual(r['unknownStatusWells'],0);self.assertEqual(r['fullWellPayloadsDownloaded'],1)
    def test_large_unexpected_removal_preserves_previous_cache(self):
        self.call();before=self.path.read_bytes();self.config['maximumAutomaticRemovalFraction']=0.05;self.api.wells=[]
        with self.assertRaises(RuntimeError):self.call()
        self.assertEqual(self.path.read_bytes(),before)
    def test_changed_origins_queue_persists_until_gis_acknowledges_it(self):
        self.call();self.api.wells[0]['WellName']='Changed Synthetic';self.api.wells[0]['UpdatedDate']='2026-10-11T00:00:00Z';self.call();self.call()
        d=sqlite3.connect(self.path);queued={r[0] for r in d.execute('SELECT Origin FROM DirtyOrigins')};d.close();self.assertEqual(queued,{origin(self.api.wells[0])})

if __name__=='__main__':unittest.main()
