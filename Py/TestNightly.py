"""A scheduled update must never silently start a national initialization."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import BuildEnverusGuggWellRecord as WellRecord

class NightlyTests(unittest.TestCase):
    def test_missing_source_baseline_waits_without_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Json/Config').mkdir(parents=True)
            (root/'Json/Config/Workflow.json').write_text(json.dumps(dict(profile='Synthetic')))
            with patch.object(WellRecord,'ROOT',root),patch('sys.argv',['BuildEnverusGuggWellRecord.py','run','--require-cache']):
                with self.assertRaises(SystemExit) as caught:WellRecord.main()
            self.assertEqual(caught.exception.code,76)

    def test_source_only_transfer_waits_for_initial_gis(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'Json/Config').mkdir(parents=True)
            (root/'Json/Config/Workflow.json').write_text(json.dumps(dict(profile='Synthetic')))
            cache=root/'Sqlite/Synthetic/Cache/EnverusCache.sqlite';cache.parent.mkdir(parents=True)
            with sqlite3.connect(cache) as db:
                db.execute('CREATE TABLE Meta(Key TEXT PRIMARY KEY,Value TEXT)');db.execute("INSERT INTO Meta VALUES('watermark','2026-11-01T00:00:00Z')")
            db.close()
            with patch.object(WellRecord,'ROOT',root),patch('sys.argv',['BuildEnverusGuggWellRecord.py','build','--require-cache']):
                with self.assertRaises(SystemExit) as caught:WellRecord.main()
            self.assertEqual(caught.exception.code,77)

if __name__=='__main__':unittest.main()
