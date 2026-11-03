"""Shared validated survey and fallback geometry rules; no workspace paths."""
import arcpy
import math
SR=arcpy.SpatialReference(4326)
FT_PER_M=1/0.3048
def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None

def norm(value):
    return str(value or '').strip().upper()

def point_at(stations, md):
    for row in stations:
        if abs(row['md'] - md) < 1e-6:
            return row
    for a, b in zip(stations, stations[1:]):
        if a['md'] < md < b['md']:
            fraction = (md-a['md'])/(b['md']-a['md'])
            return {key: a[key]+fraction*(b[key]-a[key]) for key in ('md','x','y','z','inc')}
    raise ValueError('Trim bound outside survey')

def survey_lateral(raw, well, flags, measure_sr, source_kind='ACTUAL'):
    stations = []
    for row in raw:
        if norm(row.get('CoordinateSource')) != source_kind:
            continue
        values = [number(row.get(k)) for k in ('MeasuredDepth_FT','Longitude','Latitude','SubseaElevation_FT','Inclination_DEG')]
        if any(v is None for v in values):
            flags.append('InvalidStation')
            continue
        md,x,y,z,inc = values
        if not (-180 <= x <= 180 and -90 <= y <= 90 and md >= 0):
            flags.append('InvalidStation')
            continue
        stations.append(dict(md=md,x=x,y=y,z=z,inc=inc))
    stations.sort(key=lambda r:r['md'])
    distinct = {}
    for row in stations:
        if row['md'] in distinct and any(abs(row[k]-distinct[row['md']][k]) > 1e-6 for k in ('x','y','z')):
            flags.append('ConflictingStationMd')
            return None
        distinct[row['md']] = row
    stations = list(distinct.values())
    if len(stations) < 2:
        flags.append('InsufficientStations')
        return None
    top, bottom = number(well.get('UpperPerf_FT')), number(well.get('LowerPerf_FT'))
    if top is not None and bottom is not None and top < bottom and stations[0]['md'] <= top and bottom <= stations[-1]['md']:
        method = 'PerforationMd'
    else:
        flags.append('EstimatedTrim80Deg')
        if top is not None or bottom is not None:
            flags.append('InvalidOrPartialPerfBounds')
        runs, current = [], []
        for row in stations:
            if row['inc'] >= 80:
                current.append(row)
            else:
                if len(current) >= 2:
                    runs.append(current)
                current = []
        if len(current) >= 2:
            runs.append(current)
        if not runs:
            flags.append('NoEstimatedLateral')
            return None
        run = max(runs,key=lambda r:r[-1]['md']-r[0]['md'])
        top,bottom,method = run[0]['md'],run[-1]['md'],'Inclination80Pilot'
    clipped = [point_at(stations,top)] + [r for r in stations if top < r['md'] < bottom] + [point_at(stations,bottom)]
    geom3 = arcpy.Polyline(arcpy.Array([arcpy.Point(r['x'],r['y'],r['z']) for r in clipped]),SR,True)
    geom2 = arcpy.Polyline(arcpy.Array([arcpy.Point(r['x'],r['y']) for r in clipped]),SR)
    if geom2.projectAs(measure_sr).length <= 0.01:
        flags.append('ZeroPlanLength')
        return None
    return geom2,geom3,method,top,bottom

def trim_fallback(geom, a, measure_sr):
    """Distances are projected XY meters, not measured depth or geographic degrees."""
    p = geom.projectAs(measure_sr)
    target = number(a.get('LatLenFt'))
    info = dict(sourceFt=p.length*FT_PER_M, targetFt=target, toeEnd=None)
    if norm(a.get('Trajectory')) == 'VERTICAL': return geom, 'ReviewVertical', info
    if target is None or target <= 0: return geom, 'ReviewNoLength', info
    if p.partCount != 1: return geom, 'ReviewMultipart', info
    distance = target / FT_PER_M
    if distance > p.length: return geom, 'ReviewLengthOverPath', info
    def endpoint_distances(x, y):
        x, y = number(x), number(y)
        if x is None or y is None or not (-180 <= x <= 180 and -90 <= y <= 90): return None
        q = arcpy.PointGeometry(arcpy.Point(x, y), SR).projectAs(measure_sr)
        return [arcpy.PointGeometry(pt, measure_sr).distanceTo(q) for pt in [p.firstPoint, p.lastPoint]]
    # A bottom-hole endpoint within 100 ft is preferred. If a BHL exists but
    # conflicts with the path, do not silently substitute a surface-based guess.
    ds = endpoint_distances(a.get('BhlLon'), a.get('BhlLat'))
    if ds is not None:
        if min(ds) > 30.48 or abs(ds[0]-ds[1]) <= 1: return geom, 'ReviewToeUncertain', info
        toe = 0 if ds[0] < ds[1] else 1
        info['toeEvidence'] = 'BHL within 100 ft of endpoint'
        info['toeOffsetFt'] = min(ds)*FT_PER_M
    else:
        ds = endpoint_distances(a.get('ShlLon'), a.get('ShlLat'))
        if ds is None or min(ds) > 30.48 or abs(ds[0]-ds[1]) <= 1: return geom, 'ReviewToeUncertain', info
        toe = 1 if ds[0] < ds[1] else 0
        info['toeEvidence'] = 'Opposite verified SHL endpoint; BHL absent'
        info['toeOffsetFt'] = None
    info['toeEnd'] = 'First' if toe == 0 else 'Last'
    result = p.segmentAlongLine(0, distance) if toe == 0 else p.segmentAlongLine(p.length-distance, p.length)
    output = result.projectAs(SR)
    returned = output.projectAs(measure_sr)
    info['resultFt'] = returned.length*FT_PER_M
    info['removedFt'] = info['sourceFt']-info['resultFt']
    if abs(info['resultFt']-target) > 0.1: raise RuntimeError('Toe-back length verification failed')
    kept_toe = returned.firstPoint if toe == 0 else returned.lastPoint
    old_toe = p.firstPoint if toe == 0 else p.lastPoint
    if arcpy.PointGeometry(kept_toe, measure_sr).distanceTo(arcpy.PointGeometry(old_toe, measure_sr)) > .01:
        raise RuntimeError('Toe endpoint moved')
    if returned.length > p.length+.01: raise RuntimeError('Trim enlarged source path')
    return output, 'ToeBackLengthEstimate', info

def measurement_sr(geometry):
    points=[p for part in geometry for p in part if p] if geometry.type=='polyline' else [geometry.firstPoint]
    lat=sum(p.Y for p in points)/len(points)
    lon=math.degrees(math.atan2(sum(math.sin(math.radians(p.X)) for p in points),sum(math.cos(math.radians(p.X)) for p in points)))
    if lat>84:return arcpy.SpatialReference(32661)
    if lat<-80:return arcpy.SpatialReference(32761)
    zone=max(1,min(60,int((lon+180)//6)+1))
    return arcpy.SpatialReference((32600 if lat>=0 else 32700)+zone)
