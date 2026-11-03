"""Crosswalk and longest-overlap assignments across all available reference basins."""
import arcpy
from collections import defaultdict
from functools import lru_cache
from WellGeometry import norm,number,SR,FT_PER_M
from WellRecordCalculations import calculate_spacing

def rows(path,fields):
    with arcpy.da.SearchCursor(str(path),fields) as cursor:return [dict(zip(fields,row)) for row in cursor]
def extent_intersects(a,b):return a.XMin<=b.XMax and a.XMax>=b.XMin and a.YMin<=b.YMax and a.YMax>=b.YMin

class References:
    def __init__(self,gdb):
        self.nom=defaultdict(list);self.tcas=defaultdict(list);self.fluids=[];self.geometry={};self.basins=[]
        if arcpy.Exists(str(gdb/'GUGG_GIS_Basin')):
            grouped={}
            for name,shape in arcpy.da.SearchCursor(str(gdb/'GUGG_GIS_Basin'),['GuggGisBsn','SHAPE@']):
                if not str(name or '').strip():raise RuntimeError('Gugg GIS basin names must be populated')
                shape=shape.projectAs(SR);grouped[name]=grouped[name].union(shape) if name in grouped else shape
            for i,(name,shape) in enumerate(sorted(grouped.items())):
                token='B'+str(i);self.geometry[token]=shape;self.basins.append(dict(name=name,token=token,extent=shape.extent))
        for r in rows(gdb/'GUGG_Nomenclature',['ENVRegion','ENVBasin','ENVInterval','GUGG_BASIN','GUGG_LANDING_ZONE','GUGG_BENCH','GUGG_TCA_PREFIX']):self.nom[tuple(norm(r[k]) for k in ['ENVRegion','ENVBasin','ENVInterval'])].append(r)
        tcas=rows(gdb/'GUGG_TCAs',['TCA_NAME','TCA_ID','GUGG_BASIN','GUGG_BENCH','WPS','FLUID_TYPE','AVG_TVD','IRR','PRIM_SEC','CAPEX_FT','UPSIDE','SHAPE@'])
        names=[norm(r['TCA_NAME']) for r in tcas]
        if not all(names) or len(names)!=len(set(names)):raise RuntimeError('TCA_NAME must be nonblank and unique across reference inputs')
        for i,r in enumerate(tcas):
            r['token']='T'+str(i);self.geometry[r['token']]=r.pop('SHAPE@');r['extent']=self.geometry[r['token']].projectAs(SR).extent;self.tcas[(norm(r['GUGG_BASIN']),norm(r['GUGG_BENCH']))].append(r)
        for i,r in enumerate(rows(gdb/'GUGG_FluidWindows',['Play','SubPlay','Type','SHAPE@'])):
            r['token']='F'+str(i);self.geometry[r['token']]=r.pop('SHAPE@');r['extent']=self.geometry[r['token']].projectAs(SR).extent;self.fluids.append(r)
    @lru_cache(maxsize=2048)
    def projected(self,token,epsg):return self.geometry[token].projectAs(arcpy.SpatialReference(epsg))
    def nomenclature(self,well,a,flags):
        matches=self.nom.get(tuple(norm(well.get(k)) for k in ['ENVRegion','ENVBasin','ENVInterval']),[])
        if len(matches)==1:
            a.update({n:matches[0][k] for n,k in [('GuggBasin','GUGG_BASIN'),('GuggZone','GUGG_LANDING_ZONE'),('GuggBench','GUGG_BENCH'),('GuggPrefix','GUGG_TCA_PREFIX')]})
        else:flags.add('NomenclatureUnmatched' if not matches else 'NomenclatureAmbiguous')
    def assign(self,geom,a,flags,sr):
        projected=geom.projectAs(sr);length=projected.length;a['LatGeomFt']=length*FT_PER_M;a['WellConstr']='N'
        trajectory=norm(a.get('Trajectory'))
        constraint_eligible=geom.type=='polyline' and length>1e-6 and trajectory not in {'','VERTICAL','UNKNOWN','UNSPECIFIED','UNDETERMINED'} and bool(norm(a.get('GuggBasin'))) and bool(norm(a.get('GuggBench')))
        self.assign_gis_basin(geom,a,flags,sr,projected)
        for kind,polygons in [('Tca',self.tcas.get((norm(a.get('GuggBasin')),norm(a.get('GuggBench'))),[])),('Fluid',self.fluids)]:
            overlaps=[]
            for poly in polygons:
                if not extent_intersects(geom.extent,poly['extent']):continue
                constraint_hit=kind=='Tca' and constraint_eligible and not geom.disjoint(self.projected(poly['token'],SR.factoryCode))
                if constraint_hit:a['WellConstr']='Y'
                shape=self.projected(poly['token'],sr.factoryCode)
                if not extent_intersects(projected.extent,shape.extent):
                    if constraint_hit:flags.add('ConstraintTcaBoundaryContact')
                    continue
                overlap=projected.intersect(shape,2).length
                if constraint_hit and overlap<=1e-6:flags.add('ConstraintTcaBoundaryContact')
                if overlap<=1e-6:continue
                if overlap>length+.001:flags.add(kind+'PrecisionReview');continue
                overlaps.append((min(overlap,length),poly))
            overlaps.sort(key=lambda p:p[0],reverse=True)
            if not overlaps:flags.add(kind+'Unmatched');continue
            if len(overlaps)>1 and abs(overlaps[0][0]-overlaps[1][0])<1e-6:flags.add(kind+'Tie');continue
            overlap,p=overlaps[0]
            if kind=='Tca':
                a.update(TcaName=p['TCA_NAME'],TcaId=p['TCA_ID'],TcaWps=number(p['WPS']),TcaFluid=p['FLUID_TYPE'],TcaTvd=number(p['AVG_TVD']),TcaIrr=number(p['IRR']),TcaPrimSec=p['PRIM_SEC'],TcaCapexFt=number(p['CAPEX_FT']),TcaUpside=p['UPSIDE'],TcaPct=100*overlap/length)
            else:a.update(FluidType=p['Type'],FluidPlay=p['Play'],FluidSub=p['SubPlay'],FluidPct=100*overlap/length)
        calc=calculate_spacing(a.get('TcaWps'));a.update(Spacing_Ft=calc['Spacing_Ft'],DA_Ft=calc['DA_Ft'])
        if calc['status']!='Calculated':flags.add(calc['status'])

    def assign_gis_basin(self,geom,a,flags,sr=None,projected=None):
        a['GuggGisBsn']=None
        if not self.basins:return
        if str(a.get('Trajectory') or '').upper()=='VERTICAL':
            x,y=number(a.get('ShlLon')),number(a.get('ShlLat'))
            if x is None or y is None or not (-180<=x<=180 and -90<=y<=90):return
            geom=arcpy.PointGeometry(arcpy.Point(x,y),SR)
        point=geom.type=='point';matches=[]
        for basin in self.basins:
            if not extent_intersects(geom.extent,basin['extent']):continue
            if point:
                if not geom.disjoint(self.geometry[basin['token']]):matches.append((1,basin['name']))
            else:
                length=(projected if projected is not None else geom.projectAs(sr)).intersect(self.projected(basin['token'],sr.factoryCode),2).length
                if length>1e-6:matches.append((length,basin['name']))
        matches.sort(reverse=True)
        if not matches:return
        if len(matches)>1:
            flags.add('GisBasinMultiple')
            if abs(matches[0][0]-matches[1][0])<1e-6:flags.add('GisBasinTie');return
        a['GuggGisBsn']=matches[0][1]
