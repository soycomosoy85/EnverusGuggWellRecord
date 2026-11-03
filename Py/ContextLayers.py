"""Context datasets run independently; failure in one does not erase others."""
import argparse,json,sys
from pathlib import Path
from ProcessLock import ProcessLock,BusyError
ROOT=Path(__file__).resolve().parents[1]

def run(root,config,action='run',api=None):
    root=Path(root);folder=root/'Sqlite'/config['profile']/'Context';folder.mkdir(parents=True,exist_ok=True);results=[]
    with ProcessLock(folder/'Context.lock'):
        if action in ['sync','run'] and api is None:
            from EnverusApi import Api
            api=Api()
        for layer in config['layers']:
            if not layer.get('enabled',True):results.append(dict(dataset=layer['dataset'],status='Disabled'));continue
            path=folder/(layer['dataset']+'.sqlite')
            try:
                result=dict(dataset=layer['dataset'],status='Complete')
                if action in ['sync','run']:
                    from ContextSync import sync
                    result['sync']=sync(api,path,layer,config)
                if action in ['build','run']:
                    from ContextProducts import build
                    result['build']=build(root,path,layer,config)
                results.append(result)
            except Exception as error:results.append(dict(dataset=layer['dataset'],status='Failed',errorType=type(error).__name__,error=str(error)))
            print(json.dumps(results[-1]),flush=True)
    report=dict(status='Failed' if any(r['status']=='Failed' for r in results) else 'Complete',layers=results)
    output=root/'Json'/config['profile']/'Context/LatestContextRun.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2));return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['sync','build','run']);parser.add_argument('--config',default='Json/Config/ContextLayers.json');args=parser.parse_args()
    try:report=run(ROOT,json.loads((ROOT/args.config).read_text()),args.action);sys.exit(0 if report['status']=='Complete' else 1)
    except BusyError as error:print(str(error));sys.exit(75)
