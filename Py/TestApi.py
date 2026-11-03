"""Synthetic pagination/allowlist tests; no credentials or network requests."""
import unittest
from urllib.parse import urlparse,parse_qs
from EnverusApi import Api,BASE

class StubApi(Api):
    def __init__(self):self.allow=lambda ids:False;self.rows={};self.urls=[]
    def request(self,url,method='GET'):
        self.urls.append(url)
        if len(self.urls)==1:return [dict(ENVWellStatus='PRODUCING')],{'Link':'</wells?offset=2>; rel="next"'}
        if len(self.urls)==2:return [dict(ENVWellStatus='PRODUCING')],{'Link':'</v3/direct-access/wells?offset=3>; rel="next"'}
        return [dict(ENVWellStatus='PRODUCING')],{}

class ApiTests(unittest.TestCase):
    def test_authentication_retries_server_error_without_logging_credential(self):
        import io
        from unittest.mock import patch
        from urllib.error import HTTPError
        response=io.BytesIO(b'{"token":"synthetic-token"}')
        with patch('EnverusApi.load_local_credentials',return_value={'SecretKey':'synthetic-secret'}),patch('EnverusApi.urlopen',side_effect=[HTTPError(BASE+'tokens',500,'Server error',{},None),response]),patch('EnverusApi.time.sleep') as pause:
            api=Api();self.assertEqual(api.token,'synthetic-token');pause.assert_called_once()
    def test_relative_pagination_preserves_status_and_field_scope(self):
        api=StubApi();rows=list(api.pages('wells',dict(fields='ENVWellStatus',country='CA')));self.assertEqual(len(rows),3)
        for url in api.urls:
            self.assertTrue(url.startswith(BASE));query=parse_qs(urlparse(url).query);self.assertEqual(query['envwellstatus'],['not(in(PERMIT CANCELLED,PERMIT EXPIRED))']);self.assertEqual(query['country'],['CA']);self.assertEqual(query['fields'],['ENVWellStatus'])
    def test_full_survey_download_requires_allowlist(self):
        api=StubApi()
        with self.assertRaises(RuntimeError):list(api.pages('full-directional-surveys',dict(fields='Latitude,Longitude')))
    def test_global_change_scan_cannot_request_geometry(self):
        api=StubApi()
        with self.assertRaises(RuntimeError):list(api.pages('full-directional-surveys',dict(updateddate='ge(2026-10-01)',fields='Latitude,Longitude'),metadata=True))

if __name__=='__main__':unittest.main()
