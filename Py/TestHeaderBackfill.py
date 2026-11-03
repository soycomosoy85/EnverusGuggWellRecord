import json,sqlite3,tempfile,unittest
from pathlib import Path
from HeaderBackfill import ensure_fields
from SourceCache import initialize
from Identity import record_id,origin,survey_key

class BackfillTests(unittest.TestCase):
    def test_new_fields_are_added_without_surveys_and_unchanged_schema_is_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'Cache.sqlite';well=dict(API_UWI='1000000001',Country='US',WellID=1,CompletionID=1,ENVWellStatus='PRODUCING',WellName='Preserved')
            db=sqlite3.connect(path);initialize(db);db.execute('INSERT INTO Wells VALUES(?,?,?,?,?)',(record_id(well),survey_key(well),origin(well),'old',json.dumps(well)));db.execute('INSERT INTO Meta VALUES(?,?)',('headerFields',json.dumps(list(well))));db.commit();db.close()
            class Fake:
                calls=[]
                def pages(self,dataset,params,**kwargs):
                    self.calls.append((dataset,params))
                    page=[] if params['envwellstatus']=='null' else [dict(well,PeakOil_BBL=123)]
                    kwargs['checkpoint'](page,None);yield page
            api=Fake();result=ensure_fields(api,path,{'minimumFreeDiskGb':0},set(well)|{'PeakOil_BBL'})
            self.assertEqual(result['surveyDownloads'],0);self.assertTrue(all(n=='wells' for n,p in api.calls));self.assertTrue(all('WellName' not in p['fields'].split(',') for n,p in api.calls))
            db=sqlite3.connect(path);payload=json.loads(db.execute('SELECT Payload FROM Wells').fetchone()[0]);self.assertEqual(payload['WellName'],'Preserved');self.assertEqual(payload['PeakOil_BBL'],123);self.assertEqual(db.execute('SELECT count(*) FROM DirtyOrigins').fetchone()[0],1);db.close()
            before=len(api.calls);self.assertEqual(ensure_fields(api,path,{'minimumFreeDiskGb':0},set(well)|{'PeakOil_BBL'})['status'],'NoNewHeaderFields');self.assertEqual(len(api.calls),before)

if __name__=='__main__':unittest.main()
