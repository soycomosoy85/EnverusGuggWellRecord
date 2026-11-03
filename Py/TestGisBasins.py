import unittest
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy needed')
class BasinTests(unittest.TestCase):
    def references(self):
        from GuggEnrichment import References
        from WellGeometry import SR
        refs=References.__new__(References);refs.geometry={};refs.basins=[]
        for name,x0,x1 in [('A',-104.1,-103.98),('B',-104,-103.9)]:
            geom=arcpy.FromWKT(f'POLYGON(({x0} 31.9,{x1} 31.9,{x1} 32.1,{x0} 32.1,{x0} 31.9))',SR);refs.geometry[name]=geom;refs.basins.append(dict(name=name,token=name,extent=geom.extent))
        return refs

    def test_longest_lateral_overlap_wins_without_clipping(self):
        from WellGeometry import SR,measurement_sr
        refs=self.references();line=arcpy.FromWKT('LINESTRING(-104.02 32,-103.92 32)',SR);original=line.JSON;attrs=dict(Trajectory='HORIZONTAL');flags=set();refs.assign_gis_basin(line,attrs,flags,measurement_sr(line))
        self.assertEqual(attrs['GuggGisBsn'],'B');self.assertIn('GisBasinMultiple',flags);self.assertEqual(original,line.JSON);refs.projected.cache_clear()

    def test_vertical_uses_surface_not_lateral(self):
        from WellGeometry import SR,measurement_sr
        refs=self.references();line=arcpy.FromWKT('LINESTRING(-103.96 32,-103.92 32)',SR);attrs=dict(Trajectory='VERTICAL',ShlLon=-104.05,ShlLat=32);refs.assign_gis_basin(line,attrs,set(),measurement_sr(line));self.assertEqual(attrs['GuggGisBsn'],'A');refs.projected.cache_clear()

    def test_overlapping_point_is_flagged_instead_of_arbitrary_assignment(self):
        from WellGeometry import SR
        refs=self.references();attrs={};flags=set();refs.assign_gis_basin(arcpy.PointGeometry(arcpy.Point(-103.99,32),SR),attrs,flags);self.assertIsNone(attrs['GuggGisBsn']);self.assertIn('GisBasinTie',flags);refs.projected.cache_clear()

if __name__=='__main__':unittest.main()
