"""Representative-selection policy; grouping keys are country-safe."""
from collections import defaultdict
from Identity import normalize

def produced(a): return bool(a.get('FirstProd') or a.get('LastProd') or (a.get('CumProdBoe') or 0)>0)

def realized(a):
    return bool(a.get('ComplDate') or produced(a) or a.get('EnvStatus') in {
        'PRODUCING','INACTIVE PRODUCER','COMPLETED','INACTIVE COMPLETED','INJECTING',
        'INACTIVE INJECTOR','TA','P & A','DRILLED','DUC'})

def geometry_rank(a):
    return 3 if a.get('GeomSrc')=='ActualSurvey' and a.get('TrimMethod')=='PerforationMd' else 2 if a.get('GeomSrc')=='ActualSurvey' else 1.8 if a.get('GeomSrc')=='PlannedSurvey' and a.get('TrimMethod')=='PerforationMd' else 1.5 if a.get('GeomSrc')=='PlannedSurvey' else 1 if a.get('GeomSrc')=='EnverusLateral' else 0

def suffix(a):
    value=normalize(a.get('ApiUwi14'))
    return int(value[-4:]) if len(value)==14 and value[-4:].isdigit() else -1

def choose(rows):
    """One usable lateral per origin; point-only origins retain a point record."""
    eligible=[r for r in rows if r['layer']=='Line'] or [r for r in rows if r['layer']=='Point'] or rows
    bores=defaultdict(list)
    for row in eligible: bores[row['a'].get('Api12') or row['key']].append(row)
    def bore_rank(pair):
        api,items=pair; attrs=[r['a'] for r in items]
        return (any(a.get('EnvStatus')=='PRODUCING' for a in attrs),any(produced(a) for a in attrs),
                any(realized(a) for a in attrs),max(a.get('LastProd') or '' for a in attrs),
                max(a.get('ComplDate') or '' for a in attrs),max(geometry_rank(a) for a in attrs),api)
    bore,items=max(bores.items(),key=bore_rank)
    active=[r for r in items if r['a'].get('EnvStatus')=='PRODUCING']
    if active: items=active
    winner=max(items,key=lambda r:(realized(r['a']),geometry_rank(r['a']),r['a'].get('ComplDate') or '',
                                   r['a'].get('LastProd') or '',suffix(r['a']),r['key']))
    return winner,bore_rank((bore,bores[bore]))
