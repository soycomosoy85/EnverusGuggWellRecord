"""V3 transport: verified status exclusion, pagination, retry, and bounded surveys."""
import gzip,json,socket,time
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlparse,parse_qsl,urljoin,urlunparse
from requests.utils import parse_header_links
from EnverusCredentials import load_local_credentials
from WellScope import well_parameters,excluded

BASE='https://api.enverus.com/v3/direct-access/'
METADATA_FIELDS={'API_UWI_12_Unformatted','UpdatedDate','DeletedDate'}

class Api:
    def __init__(self,token=None):
        self.allow=lambda ids:False;self.token=token
        if token is None:self.authenticate()
        self.calls=0;self.rows={}
    def authenticate(self):
        credential=load_local_credentials(3)
        if not credential:raise RuntimeError('Run Ps1/SetEnverusCredentials.ps1 -ApiVersion 3 on this Windows account first')
        request=Request(BASE+'tokens',data=json.dumps({'secretKey':credential['SecretKey']}).encode(),headers={'Content-Type':'application/json'})
        del credential
        with urlopen(request,timeout=60) as response:self.token=json.load(response)['token']
    def request(self,url,method='GET'):
        if not url.startswith(BASE) or urlparse(url).netloc!='api.enverus.com':raise RuntimeError('Unexpected API destination')
        for attempt in range(5):
            try:
                self.calls+=1
                with urlopen(Request(url,method=method,headers={'Authorization':'Bearer '+self.token,'Accept-Encoding':'gzip','Accept':'application/json'}),timeout=180) as response:
                    if method=='HEAD':return None,dict(response.headers)
                    stream=gzip.GzipFile(fileobj=response) if response.headers.get('Content-Encoding')=='gzip' else response
                    return json.load(stream),dict(response.headers)
            except HTTPError as error:
                if error.code==401 and attempt==0:self.authenticate();continue
                if error.code not in [429,500,502,503,504] or attempt==4:raise RuntimeError('Enverus HTTP '+str(error.code)+'; response and credentials not logged') from None
                delay=min(float(error.headers.get('Retry-After','5')),45)
            except (URLError,TimeoutError,socket.timeout,ConnectionError):
                if attempt==4:raise RuntimeError('Enverus connection failed after retries') from None
                delay=min(3*2**attempt,45)
            time.sleep(delay)
    def pages(self,dataset,params,metadata=False,start_url=None,checkpoint=None):
        params=dict(params,pagesize=params.get('pagesize',20000))
        if dataset=='wells':params=well_parameters(params)
        elif dataset in ['header-directional-surveys','full-directional-surveys']:
            expr=params.get('api_uwi_12_unformatted','');ids=expr[3:-1].split(',') if expr.startswith('in(') and expr.endswith(')') else []
            global_metadata=metadata and (params.get('updateddate') or params.get('deleteddate')) and set(params.get('fields','').split(','))<=METADATA_FIELDS
            if not (global_metadata or (ids and self.allow(ids))):raise RuntimeError('Survey request is not in the eligible allowlist')
        url=start_url or BASE+dataset+'?'+urlencode(params)
        while url:
            data,headers=self.request(url)
            if not isinstance(data,list):raise RuntimeError('Unexpected API response schema')
            if dataset=='wells' and any(excluded(w.get('ENVWellStatus')) for w in data):raise RuntimeError('Excluded permit status returned; page not saved')
            if dataset!='wells' and not (metadata and not ids):
                if any(str(r.get('API_UWI_12_Unformatted')) not in ids for r in data):raise RuntimeError('Survey API ignored wellbore scope')
            self.rows[dataset]=self.rows.get(dataset,0)+len(data)
            link=next((v for k,v in headers.items() if k.lower()=='link'),'')
            target=next((p['url'] for p in parse_header_links(link) if p.get('rel')=='next'),None)
            if target and data:
                url=('https://api.enverus.com'+target if target.startswith('/v3/') else BASE.rstrip('/')+target) if target.startswith('/') else urljoin(BASE,target)
                parsed=urlparse(url)
                if parsed.path.rstrip('/')!=(urlparse(BASE).path+dataset).rstrip('/'):raise RuntimeError('Pagination changed datasets')
                following=dict(parse_qsl(parsed.query))
                # Preserve original status/ID/date/field scope even if a next
                # link omits it. Keep the server's pagination cursor/offset.
                for key,value in params.items():
                    if key.lower() not in ['offset','cursor','page','skip']:following[key]=value
                url=urlunparse(parsed._replace(query=urlencode(following)))
            else:url=None
            if checkpoint is not None:checkpoint(data,url)
            yield data
    def count(self,dataset,params):
        _,headers=self.request(BASE+dataset+'?'+urlencode(params),method='HEAD')
        return int(next(v for k,v in headers.items() if k.lower()=='x-query-record-count'))
