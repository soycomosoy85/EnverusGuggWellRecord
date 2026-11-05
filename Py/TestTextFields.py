import json
import tempfile
import unittest
from pathlib import Path
from TextFields import required_widths, shapefile_text
from ExportCompatibility import compatible_logic_hash, PREVIOUS_LOGIC_HASH, WRITER_REPAIR_LOGIC_HASH


class TextFieldTests(unittest.TestCase):
    def test_full_text_and_constraint_width(self):
        fields=[dict(fieldName='EnvTicker',exportType='TEXT'),dict(fieldName='WellConstr',exportType='TEXT')]
        text='CANADIAN OIL & GAS INTERNATIONAL*'
        self.assertEqual(required_widths(fields,[json.dumps(dict(EnvTicker=text,WellConstr='N'))],{'EnvTicker':32,'WellConstr':1}),{'EnvTicker':64})
        with self.assertRaises(ValueError):
            required_widths(fields,[json.dumps(dict(WellConstr='YES'))],{'EnvTicker':32,'WellConstr':1})

    def test_dbf_marker_always_fits(self):
        for width in [1,5,6,32,254]:
            self.assertLessEqual(len(shapefile_text('X'*300,width)),width)
        self.assertEqual(shapefile_text('ABC',32),'ABC')

    def test_compatibility_is_exact(self):
        self.assertEqual(compatible_logic_hash(WRITER_REPAIR_LOGIC_HASH),PREVIOUS_LOGIC_HASH)
        self.assertEqual(compatible_logic_hash('future-geometry-change'),'future-geometry-change')

    def test_populated_gdb_width_can_expand(self):
        import arcpy
        with tempfile.TemporaryDirectory(prefix='TextWidth',ignore_cleanup_errors=True) as folder:
            gdb=Path(folder)/'Test.gdb';arcpy.management.CreateFileGDB(folder,gdb.name)
            table=str(gdb/'Example');arcpy.management.CreateTable(str(gdb),'Example')
            arcpy.management.AddField(table,'EnvTicker','TEXT',field_length=32)
            with arcpy.da.InsertCursor(table,['EnvTicker']) as rows:rows.insertRow(['ABC'])
            arcpy.management.AlterField(table,'EnvTicker',field_length=64)
            value='CANADIAN OIL & GAS INTERNATIONAL*'
            with arcpy.da.InsertCursor(table,['EnvTicker']) as rows:rows.insertRow([value])
            with arcpy.da.SearchCursor(table,['EnvTicker']) as rows:self.assertEqual([r[0] for r in rows],['ABC',value])
            arcpy.management.ClearWorkspaceCache()


if __name__=='__main__':unittest.main()
