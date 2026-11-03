"""Synthetic geometry checks for source precedence, regional SRs, and toe-back trims."""
import unittest
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy not installed')
class GeometryTests(unittest.TestCase):
    def test_midpoint_is_on_curved_line_and_vertical_uses_surface(self):
        from WellGeometry import SR,measurement_sr
        from ManagedProducts import midpoint
        shape=arcpy.FromWKT('LINESTRING(-104 32,-104 32.02,-103.94 32.02)',SR);sr=measurement_sr(shape)
        point=midpoint(shape,dict(Trajectory='HORIZONTAL'));projected=shape.projectAs(sr);local=point.projectAs(sr)
        self.assertLess(local.distanceTo(projected),.01);self.assertLess(abs(projected.measureOnLine(local)/projected.length-.5),1e-5)
        vertical=midpoint(shape,dict(Trajectory='VERTICAL',ShlLon=-105,ShlLat=33));self.assertAlmostEqual(vertical.firstPoint.X,-105);self.assertAlmostEqual(vertical.firstPoint.Y,33)
    def test_regional_projection(self):
        from WellGeometry import measurement_sr,SR
        alaska=measurement_sr(arcpy.PointGeometry(arcpy.Point(-150,65),SR));canada=measurement_sr(arcpy.PointGeometry(arcpy.Point(-110,55),SR));nm=measurement_sr(arcpy.PointGeometry(arcpy.Point(-104,32),SR))
        self.assertEqual(alaska.factoryCode,32606);self.assertEqual(canada.factoryCode,32612);self.assertEqual(nm.factoryCode,32613)
    def test_toe_back_reverse_order_and_exact_length(self):
        from WellGeometry import SR,FT_PER_M,measurement_sr,trim_fallback
        raw=arcpy.FromWKT('LINESTRING(-110 55,-109.98 55)',SR);sr=measurement_sr(raw);a=dict(Trajectory='HORIZONTAL',LatLenFt=1000,BhlLon=-109.98,BhlLat=55)
        g,method,details=trim_fallback(raw,a,sr);self.assertEqual(method,'ToeBackLengthEstimate');self.assertLess(abs(g.projectAs(sr).length*FT_PER_M-1000),.1)
        reverse=arcpy.FromWKT('LINESTRING(-109.98 55,-110 55)',SR);r,_,_=trim_fallback(reverse,a,sr);self.assertTrue(g.equals(r))
    def test_planned_never_mislabeled_as_actual(self):
        from WellGeometry import SR,measurement_sr,survey_lateral
        sr=measurement_sr(arcpy.PointGeometry(arcpy.Point(-104,32),SR));stations=[dict(CoordinateSource='PLANNED',MeasuredDepth_FT=md,Longitude=x,Latitude=32,SubseaElevation_FT=-5000,Inclination_DEG=90) for md,x in [(8000,-104),(10000,-103.98)]]
        self.assertIsNone(survey_lateral(stations,{},[],sr,source_kind='ACTUAL'));self.assertIsNotNone(survey_lateral(stations,{},[],sr,source_kind='PLANNED'))
    def test_unknown_status_is_flagged_without_dropping_record(self):
        from BuildProducts import compute
        class EmptyReferences:
            def nomenclature(self,well,attrs,flags):flags.add('NomenclatureUnmatched')
        layer,attrs,geom,geom3=compute(dict(Country='CA',WellID=1,API_UWI='SYNTHETIC',ENVWellStatus=None),'SYNTHETIC',[],[],{'fields':[]},EmptyReferences(),{'plannedSurveyStates':['NM']})
        self.assertEqual(layer,'NoLocation');self.assertIn('UnknownWellStatus',attrs['QaStatus']);self.assertIsNotNone(attrs['WellKey'])

if __name__=='__main__':unittest.main()
