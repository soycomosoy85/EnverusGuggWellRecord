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
        self.nom=defaultdict(list);self.tcas=defaultdict(list);self.fluids=[];self.geometry={}
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
        projected=geom.projectAs(sr);length=projected.length;a['LatGeomFt']=length*FT_PER_M
        for kind,polygons in [('Tca',self.tcas.get((norm(a.get('GuggBasin')),norm(a.get('GuggBench'))),[])),('Fluid',self.fluids)]:
            overlaps=[]
            for poly in polygons:
                if not extent_intersects(geom.extent,poly['extent']):continue
                shape=self.projected(poly['token'],sr.factoryCode)
                if not extent_intersects(projected.extent,shape.extent):continue
                overlap=projected.intersect(shape,2).length
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
