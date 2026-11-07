"""Shared well-status scope; excluded statuses never belong in new acquisitions."""
EXCLUDED_STATUS_VALUES=('PERMIT CANCELLED','PERMIT EXPIRED','EXPIRED PERMIT','PERMIT CANCELED','CANCELLED PERMIT','CANCELED PERMIT')
EXCLUDED_STATUSES=frozenset(EXCLUDED_STATUS_VALUES)
EXCLUDED_STATUS_FILTER='in('+','.join(EXCLUDED_STATUS_VALUES)+')'
STATUS_FILTER='not('+EXCLUDED_STATUS_FILTER+')'


def excluded(value): return str(value or '').strip().upper() in EXCLUDED_STATUSES


def well_parameters(params):
    params=dict(params)
    key=next((k for k in params if k.lower()=='envwellstatus'),None)
    if key is None: params['envwellstatus']=STATUS_FILTER
    elif excluded(params[key]): raise ValueError('Excluded permit status cannot be downloaded')
    elif params[key]!=STATUS_FILTER and any(s in str(params[key]).upper() for s in EXCLUDED_STATUSES):
        raise ValueError('Requested status expression contains excluded statuses')
    elif params[key]!=STATUS_FILTER and '(' in str(params[key]) and not str(params[key]).lower().startswith('in('):
        raise ValueError('Use the verified status exclusion or an explicit included status list')
    return params
