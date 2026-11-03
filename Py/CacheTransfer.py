"""Export/import the successful cache and watermark as private release-sized parts."""
import argparse,bisect,hashlib,io,json,os,sqlite3,zipfile,shutil
from datetime import datetime,timezone
from pathlib import Path
from ProcessLock import ProcessLock,BusyError
ROOT=Path(__file__).resolve().parents[1]

class SplitWriter(io.RawIOBase):
    def __init__(self,folder,limit):self.folder=Path(folder);self.limit=limit;self.total=0;self.current=None;self.used=0;self.parts=[];self.digest=None
    def writable(self):return True
    def seekable(self):return False
    def tell(self):return self.total
    def finish_part(self):
        if self.current:self.current.flush();self.current.close();self.parts[-1].update(size=self.used,sha256=self.digest.hexdigest());self.current=None
    def write(self,data):
        original=len(data);view=memoryview(data)
        while view:
            if self.current is None:
                name='EnverusCache.zip.part'+str(len(self.parts)+1).zfill(4);self.parts.append(dict(name=name));self.current=open(self.folder/name,'wb');self.used=0;self.digest=hashlib.sha256()
            n=min(len(view),self.limit-self.used);chunk=view[:n];self.current.write(chunk);self.digest.update(chunk);self.used+=n;self.total+=n;view=view[n:]
            if self.used==self.limit:self.finish_part()
        return original
    def flush(self):
        if self.current:self.current.flush()
    def close(self):
        if not self.closed:self.finish_part();super().close()

class MultipartReader(io.RawIOBase):
    def __init__(self,paths):self.paths=list(paths);self.offsets=[0];self.position=0;self.handle=None;self.part=None
    def prepare(self):
        for p in self.paths:self.offsets.append(self.offsets[-1]+p.stat().st_size)
        return self
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        position=offset if whence==0 else self.position+offset if whence==1 else self.offsets[-1]+offset
        if not 0<=position<=self.offsets[-1]:raise OSError('Archive seek out of bounds')
        self.position=position;return position
    def read(self,size=-1):
        size=self.offsets[-1]-self.position if size<0 else min(size,self.offsets[-1]-self.position);out=bytearray()
        while size:
            index=bisect.bisect_right(self.offsets,self.position)-1
            if self.part!=index:
                if self.handle:self.handle.close()
                self.handle=open(self.paths[index],'rb');self.part=index
            local=self.position-self.offsets[index];self.handle.seek(local);chunk=self.handle.read(min(size,self.offsets[index+1]-self.position))
            if not chunk:raise OSError('Truncated archive part')
            out.extend(chunk);self.position+=len(chunk);size-=len(chunk)
        return bytes(out)
    def close(self):
        if self.handle:self.handle.close()
        super().close()

def hash_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        while data:=f.read(4*1024**2):h.update(data)
    return h.hexdigest()

def export_cache(root,config,part_bytes=1024**3):
    root=Path(root);cache=root/'Sqlite'/config['profile']/'Cache'/'EnverusCache.sqlite'
    if not cache.exists():raise RuntimeError('No successful cache exists yet')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=root/'Zip/CacheTransfers'/(config['profile']+stamp);folder.mkdir(parents=True)
    connection=sqlite3.connect(cache);writer=None
    try:
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)');connection.execute('PRAGMA journal_mode=DELETE');connection.execute('BEGIN IMMEDIATE')
        metadata=dict(connection.execute('SELECT * FROM Meta'))
        if not metadata.get('watermark'):raise RuntimeError('Cache baseline is not complete')
        size=cache.stat().st_size;digest=hashlib.sha256();done=0;writer=SplitWriter(folder,part_bytes)
        with zipfile.ZipFile(writer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            with archive.open('EnverusCache.sqlite','w',force_zip64=True) as target,open(cache,'rb') as source:
                while block:=source.read(4*1024**2):
                    if shutil.disk_usage(folder).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; cache remains valid, transfer can be retried')
                    target.write(block);digest.update(block);done+=len(block)
                    if done%(1024**3)<len(block):print('Transfer input compressed '+str(done)+'/'+str(size)+' bytes',flush=True)
        writer.close()
        manifest=dict(formatVersion=1,profile=config['profile'],scope=json.loads(metadata['scope']),watermark=metadata['watermark'],cacheSize=size,cacheSha256=digest.hexdigest(),parts=writer.parts,containsWellData=True,containsCredentials=False,created=datetime.now(timezone.utc).isoformat())
        path=folder/'CacheTransferManifest.json';path.write_text(json.dumps(manifest,indent=2));return dict(manifest=str(path),parts=len(writer.parts),cacheSize=size,compressedBytes=writer.total,watermark=metadata['watermark'])
    finally:
        if writer:writer.close()
        connection.rollback();connection.close()

def import_cache(root,config,manifest_path,replace=False):
    manifest_path=Path(manifest_path);m=json.loads(manifest_path.read_text());root=Path(root)
    if m.get('formatVersion')==2:
        from RuntimeTransfer import import_runtime
        return import_runtime(root,config,manifest_path,replace)
    if m.get('formatVersion')!=1 or m['scope']!=config.get('apiFilters',{}):raise RuntimeError('Transfer schema or acquisition scope mismatch')
    paths=[]
    for part in m['parts']:
        name=part['name']
        if Path(name).name!=name or '/' in name or '\\' in name or not name.startswith('EnverusCache.zip.part'):raise RuntimeError('Unsafe archive part name')
        path=manifest_path.parent/name
        if path.stat().st_size!=part['size'] or hash_file(path)!=part['sha256']:raise RuntimeError('Archive part missing, incomplete, or hash mismatch: '+name)
        paths.append(path)
    folder=root/'Sqlite'/config['profile']/'Cache';folder.mkdir(parents=True,exist_ok=True);cache=folder/'EnverusCache.sqlite';pending=folder/'ImportedPending.sqlite'
    if cache.exists() and not replace:raise RuntimeError('A cache already exists; explicit --replace is required')
    if shutil.disk_usage(folder).free<m['cacheSize']+config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Not enough free space to restore the cache')
    try:
        digest=hashlib.sha256();done=0
        with MultipartReader(paths).prepare() as joined,zipfile.ZipFile(joined) as archive:
            entries=archive.infolist()
            if len(entries)!=1 or entries[0].filename!='EnverusCache.sqlite' or entries[0].file_size!=m['cacheSize']:raise RuntimeError('Unexpected archive contents')
            with archive.open(entries[0]) as source,open(pending,'wb') as target:
                while block:=source.read(4*1024**2):target.write(block);digest.update(block);done+=len(block)
        if digest.hexdigest()!=m['cacheSha256'] or done!=m['cacheSize']:raise RuntimeError('Restored cache hash mismatch')
        db=sqlite3.connect(pending)
        try:
            metadata=dict(db.execute('SELECT * FROM Meta'))
            if metadata.get('watermark')!=m['watermark'] or json.loads(metadata['scope'])!=m['scope']:raise RuntimeError('Restored watermark or scope mismatch')
            check=db.execute('PRAGMA quick_check').fetchone()[0]
            if check!='ok':raise RuntimeError('SQLite validation failed')
        finally:db.close()
        os.replace(pending,cache);return dict(cache=str(cache),watermark=m['watermark'],nextSync='incremental',sha256Verified=True)
    finally:
        if pending.exists():pending.unlink()

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['export','import']);p.add_argument('--config',default='Json/Config/Workflow.json');p.add_argument('--manifest');p.add_argument('--replace',action='store_true');p.add_argument('--include-gis',action='store_true');p.add_argument('--build-gis-first',action='store_true');args=p.parse_args();config=json.loads((ROOT/args.config).read_text());folder=ROOT/'Sqlite'/config['profile']/'Cache'
    with ProcessLock(folder/'Workflow.lock'):
        if args.action=='export':
            transfer=config.get('transfer',{})
            if args.include_gis or transfer.get('includeGIS'):
                from RuntimeTransfer import export_runtime
                result=export_runtime(ROOT,config,build_first=args.build_gis_first or transfer.get('buildGISFirst',False))
            else:result=export_cache(ROOT,config)
        else:
            if not args.manifest:raise RuntimeError('--manifest is required')
            result=import_cache(ROOT,config,args.manifest,args.replace)
    print(json.dumps(result,indent=2));report=ROOT/'Json'/config['profile']/'Output/Qa/LatestCacheTransfer.json';report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except BusyError as error:print(str(error));raise SystemExit(75)
