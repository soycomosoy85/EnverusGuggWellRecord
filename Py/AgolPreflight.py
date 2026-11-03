"""Local readiness checks only. This command never uploads or publishes data."""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def readiness(root,config):
    root=Path(root);scope=config.get('scope',{});path=scope.get('featureClass');field=scope.get('nameField')
    report=dict(status='WaitingForGisBasinLayer',uploaded=False,published=False,fullNationalPublication=False,requiredInputs=['scope.featureClass','scope.nameField'])
    if path and field:
        import arcpy
        path=str(root/path)
        if not arcpy.Exists(path):raise RuntimeError('GIS basin feature class does not exist')
        if arcpy.Describe(path).shapeType!='Polygon':raise RuntimeError('GIS basin input must contain polygons')
        if field not in {f.name for f in arcpy.ListFields(path)}:raise RuntimeError('GIS basin name field is missing')
        values=[v for v, in arcpy.da.SearchCursor(path,[field])]
        if not values or any(not str(v or '').strip() for v in values):raise RuntimeError('GIS basin names must be populated')
        report.update(status='ReadyForSubsetPreparation',basinFeatures=len(values),distinctNames=len(set(values)),requiredInputs=[],qcHold=bool(config.get('awaitUserQualityControl')))
    output=root/'Json'/config['profile']/'Agol/PublishReadiness.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2));return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',default='Json/Config/ArcGisOnline.json');parser.add_argument('--prepare-subset',action='store_true');args=parser.parse_args();config=json.loads((ROOT/args.config).read_text());report=readiness(ROOT,config)
    if args.prepare_subset and report['status']=='ReadyForSubsetPreparation':
        from AgolSubset import prepare
        report=prepare(ROOT,config)
    print(json.dumps(report,indent=2))
