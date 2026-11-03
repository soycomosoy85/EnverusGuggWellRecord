"""Country-safe identities. Never truncate Canadian UWIs to a US API10/API14."""
import re

def normalize(value):return re.sub(r'[^A-Za-z0-9]','',str(value or '')).upper()
def country(well):return str(well.get('Country') or 'UNKNOWN').upper()
def origin(well):
    uwi=normalize(well.get('API_UWI_Unformatted') or well.get('API_UWI'))
    if not uwi:uwi='WELLID'+str(well.get('WellID'))
    return country(well)+'|'+uwi
def record_id(well):
    token=normalize(well.get('API_UWI_14_Unformatted') or well.get('API_UWI_Unformatted') or well.get('API_UWI'))
    if not token and well.get('WellID') is None:raise ValueError('Source has no stable identity')
    return country(well)+'|'+token+'|'+str(well.get('WellID'))+'|'+str(well.get('CompletionID'))
def survey_key(well):return str(well.get('API_UWI_12_Unformatted') or '')
