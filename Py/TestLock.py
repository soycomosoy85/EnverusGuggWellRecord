import os,subprocess,sys,tempfile,unittest
from pathlib import Path
from ProcessLock import ProcessLock,BusyError
class LockTests(unittest.TestCase):
    def test_overlap_is_rejected_and_old_file_is_reusable(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'Workflow.lock'
            with ProcessLock(p):
                with self.assertRaises(BusyError):
                    with ProcessLock(p):pass
            with ProcessLock(p):pass
    def test_abrupt_process_exit_releases_lock(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'Workflow.lock';env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).parent)+os.pathsep+env.get('PYTHONPATH','')
            subprocess.run([sys.executable,'-c','import os,sys;from ProcessLock import ProcessLock;lock=ProcessLock(sys.argv[1]);lock.__enter__();os._exit(0)',str(p)],env=env,check=True)
            with ProcessLock(p):pass
if __name__=='__main__':unittest.main()
