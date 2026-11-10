"""Compare delivered content independently of vendor refresh timestamps."""
import hashlib,json


def content(payload):
    row=json.loads(payload) if isinstance(payload,str) else payload
    return json.dumps({k:v for k,v in row.items() if k not in {'UpdatedDate','DeletedDate'}},sort_keys=True,separators=(',',':'))


def same_surveys(previous,bore,tables):
    for table,rows in tables.items():
        prior=sorted(content(p) for p, in previous.execute('SELECT Payload FROM '+table+' WHERE Api=?',(bore,)))
        if prior!=sorted(content(r) for r in rows):return False
    return True


def survey_version(tables):
    canonical={table:sorted(content(r) for r in rows) for table,rows in tables.items()}
    return hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':')).encode()).hexdigest()
