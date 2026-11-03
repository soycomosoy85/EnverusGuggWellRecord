import tempfile,unittest
from pathlib import Path
from AgolPreflight import readiness

class PreflightTests(unittest.TestCase):
    def test_missing_basin_never_publishes_or_uploads(self):
        with tempfile.TemporaryDirectory() as folder:
            report=readiness(Path(folder),dict(profile='Synthetic',scope={}))
            self.assertEqual(report['status'],'WaitingForGisBasinLayer');self.assertFalse(report['uploaded']);self.assertFalse(report['published']);self.assertFalse(report['fullNationalPublication'])

if __name__=='__main__':unittest.main()
