import gc,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
try:import arcpy
except ImportError:arcpy=None

@unittest.skipIf(arcpy is None,'ArcPy needed')
class DefaultTests(unittest.TestCase):
    def test_existing_default_is_not_rewritten_on_each_update(self):
        from SurfaceHoles import ensure_defaults
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
            arcpy.management.CreateFileGDB(folder,'Test.gdb');path=str(Path(folder)/'Test.gdb/Wells');arcpy.management.CreateTable(str(Path(folder)/'Test.gdb'),'Wells');arcpy.management.AddField(path,'WellConstr','TEXT',field_length=1)
            fields=[dict(fieldName='WellConstr',defaultValue='N')]
            with patch('SurfaceHoles.arcpy.management.AssignDefaultToField',wraps=arcpy.management.AssignDefaultToField) as assign:
                ensure_defaults(path,fields);ensure_defaults(path,fields);self.assertEqual(assign.call_count,1)
            self.assertEqual(next(iter(arcpy.da.ListSubtypes(path).values()))['FieldValues']['WellConstr'][0],'N');gc.collect();arcpy.management.ClearWorkspaceCache()

if __name__=='__main__':unittest.main()
