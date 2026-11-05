"""Install the tested attribute amendment under a destination's workflow lock."""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from ProcessLock import ProcessLock,BusyError
from UpgradeWellAttributes import upgrade_if_needed


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    source=Path(__file__).resolve().parents[1];root=Path(args.root).resolve()
    config=json.loads((root/'Json/Config/Workflow.json').read_text());base=root/'Sqlite'/config['profile']/'Cache'
    marker=root/'Json/Config/ConstraintAttributeAmendment.json'
    report=dict(status='Pending',root=str(root),updated=datetime.now(timezone.utc).isoformat())
    with ProcessLock(base/'Workflow.lock'):
        try:
            report['status']='Running';marker.write_text(json.dumps(report,indent=2))
            for name in ['BuildProducts.py','ManagedProducts.py','GuggEnrichment.py','SurfaceHoles.py','ExportCompatibility.py','TextFields.py','WellConstraintAttributes.py','UpgradeWellAttributes.py']:
                if (source/'Py'/name).resolve()!=(root/'Py'/name).resolve():shutil.copy2(source/'Py'/name,root/'Py'/name)
            for name in ['FieldDictionary.json','WellRecordRules.json','WellConstraintStatus.Local.json']:
                if (source/'Json/Config'/name).resolve()!=(root/'Json/Config'/name).resolve():shutil.copy2(source/'Json/Config'/name,root/'Json/Config'/name)
            fields=json.loads((root/'Json/Config/FieldDictionary.json').read_text())
            db=sqlite3.connect(base/'Processed.sqlite')
            try:result=upgrade_if_needed(root,config,db,fields)
            finally:db.close()
            report.update(status='Complete',upgrade=result,updated=datetime.now(timezone.utc).isoformat())
            print(json.dumps(report,indent=2),flush=True)
        except Exception as error:
            report.update(status='NeedsAttention',error=str(error));raise
        finally:marker.write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    try:main()
    except BusyError as error:print(str(error),flush=True);raise SystemExit(75)
