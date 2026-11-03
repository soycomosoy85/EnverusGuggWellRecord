import unittest
from collections import defaultdict
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy needed')
class ConstraintTests(unittest.TestCase):
    def references(self,tie=False):
        from GuggEnrichment import References
        from WellGeometry import SR
        refs=References.__new__(References);refs.geometry={};refs.basins=[];refs.fluids=[];refs.tcas=defaultdict(list);refs.nom=defaultdict(list)
        refs.nom[('TEST','TEST','TEST')]=[dict(GUGG_BASIN='DEL',GUGG_LANDING_ZONE='ZONE',GUGG_BENCH='WCA',GUGG_TCA_PREFIX='PREFIX')]
        for i in range(2 if tie else 1):
            token='T'+str(i);shape=arcpy.FromWKT('POLYGON((-104.1 31.9,-103.9 31.9,-103.9 32.1,-104.1 32.1,-104.1 31.9))',SR);refs.geometry[token]=shape
            refs.tcas[('DEL','WCA')].append(dict(token=token,extent=shape.extent,TCA_NAME=token,TCA_ID=token,WPS=4,FLUID_TYPE='OIL',AVG_TVD=10000,IRR=.1,PRIM_SEC='PRIMARY',CAPEX_FT=1000,UPSIDE='Y'))
        return refs

    def assign(self,attrs,tie=False,line=None):
        from WellGeometry import SR,measurement_sr
        refs=self.references(tie);line=line or arcpy.FromWKT('LINESTRING(-104.05 32,-103.95 32)',SR);flags=set();refs.assign(line,attrs,flags,measurement_sr(line));refs.projected.cache_clear();return attrs,flags

    def test_matching_nonvertical_lateral_is_constraint(self):
        attrs,flags=self.assign(dict(GuggBasin='DEL',GuggBench='WCA',Trajectory='HORIZONTAL'));self.assertEqual(attrs['WellConstr'],'Y')

    def test_vertical_unknown_and_mismatched_basin_or_bench_remain_n(self):
        for basin,bench,trajectory in [('DEL','WCA','VERTICAL'),('DEL','WCA',None),('OTHER','WCA','HORIZONTAL'),('DEL','OTHER','HORIZONTAL')]:
            with self.subTest(basin=basin,bench=bench,trajectory=trajectory):
                attrs,_=self.assign(dict(GuggBasin=basin,GuggBench=bench,Trajectory=trajectory));self.assertEqual(attrs['WellConstr'],'N')

    def test_primary_tca_tie_does_not_remove_constraint(self):
        attrs,flags=self.assign(dict(GuggBasin='DEL',GuggBench='WCA',Trajectory='DIRECTIONAL'),tie=True);self.assertEqual(attrs['WellConstr'],'Y');self.assertIsNone(attrs.get('TcaName'));self.assertIn('TcaTie',flags)

    def test_surface_only_nonvertical_well_is_not_constraint(self):
        from BuildProducts import compute
        refs=self.references();well=dict(API_UWI='TEST',Country='US',Trajectory='HORIZONTAL',Longitude=-104,Latitude=32,ENVRegion='TEST',ENVBasin='TEST',ENVInterval='TEST')
        layer,attrs,*_=compute(well,'TEST',[],[],{'fields':[dict(fieldName='Trajectory',directApiField='Trajectory',exportType='TEXT')]},refs,{'plannedSurveyStates':['NM']});self.assertEqual(layer,'Point');self.assertEqual(attrs['GuggBench'],'WCA');self.assertEqual(attrs['WellConstr'],'N');refs.projected.cache_clear()

    def test_boundary_intersection_qualifies_without_clipping(self):
        from WellGeometry import SR
        line=arcpy.FromWKT('LINESTRING(-104.2 32,-104.1 32)',SR);original=line.JSON;attrs,_=self.assign(dict(GuggBasin='DEL',GuggBench='WCA',Trajectory='HORIZONTAL'),line=line);self.assertEqual(attrs['WellConstr'],'Y');self.assertEqual(original,line.JSON)

if __name__=='__main__':unittest.main()
