"""Move a complete managed GIS/cache state without carrying credentials or code."""
import json,os,sqlite3,shutil,hashlib,zipfile
from datetime import datetime,timezone
from pathlib import Path
from CacheTransfer import SplitWriter,MultipartReader,hash_file

def export_runtime(root,config,part_bytes=1024**3,build_first=False):
    root=Path(root);profile=config['profile'];base=root/'Sqlite'/profile/'Cache';cache=base/'EnverusCache.sqlite';processed=base/'Processed.sqlite'
    if build_first:
        from BuildProducts import build
        build(root,config,cache)
    if not processed.exists():raise RuntimeError('Build the initial managed GIS products before exporting GIS state')
    state=sqlite3.connect(processed);meta=dict(state.execute('SELECT * FROM ProductMeta'))
    if not meta.get('initialized'):state.close();raise RuntimeError('Managed GIS initialization is not complete')
    gdb=root/'Gdb'/profile/'Output/EnverusGuggWellRecord.gdb'
    if not gdb.exists():state.close();raise RuntimeError('Current managed geodatabase is missing')
    paths=[(cache,'sourceCache'),(processed,'processingState')]
    paths.extend((p,'managedGdb') for p in gdb.rglob('*') if p.is_file() and not p.name.lower().endswith('.lock'))
    for part, in state.execute('SELECT Part FROM ShpParts'):
        shape=root/part
        for p in shape.parent.glob(shape.stem+'.*'):
            if p.is_file() and p.suffix.lower() in ['.shp','.dbf','.shx','.prj','.cpg','.sbn','.sbx','.atx','.xml']:paths.append((p,'managedShapefile'))
    state.close();paths=sorted(set(paths),key=lambda x:str(x[0]));stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=root/'Zip/CacheTransfers'/(profile+stamp);folder.mkdir(parents=True)
    connections=[];writer=None;entries=[]
    try:
        for path in [cache,processed]:
            con=sqlite3.connect(path);con.execute('PRAGMA wal_checkpoint(TRUNCATE)');con.execute('PRAGMA journal_mode=DELETE');con.execute('BEGIN IMMEDIATE');connections.append(con)
        source_meta=dict(connections[0].execute('SELECT * FROM Meta'))
        if not source_meta.get('watermark'):raise RuntimeError('No successful source watermark')
        writer=SplitWriter(folder,part_bytes)
        with zipfile.ZipFile(writer,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as archive:
            for path,role in paths:
                if path.is_symlink():raise RuntimeError('Symbolic links are not supported in managed runtime transfers')
                relative=path.resolve().relative_to(root.resolve()).as_posix();h=hashlib.sha256();size=0
                with archive.open(relative,'w',force_zip64=True) as target,open(path,'rb') as source:
                    while block:=source.read(4*1024**2):
                        if shutil.disk_usage(folder).free<config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Disk reserve reached; successful cache/GIS state remains valid')
                        target.write(block);h.update(block);size+=len(block)
                entries.append(dict(path=relative,role=role,size=size,sha256=h.hexdigest()));print('Runtime transfer packed '+relative,flush=True)
        writer.close();manifest=dict(formatVersion=2,profile=profile,scope=json.loads(source_meta['scope']),watermark=source_meta['watermark'],files=entries,parts=writer.parts,containsWellData=True,containsGIS=True,containsCredentials=False,created=datetime.now(timezone.utc).isoformat());path=folder/'CacheTransferManifest.json';path.write_text(json.dumps(manifest,indent=2))
        return dict(manifest=str(path),parts=len(writer.parts),uncompressedBytes=sum(e['size'] for e in entries),compressedBytes=writer.total,watermark=manifest['watermark'],includesGIS=True,nextBuild='changed records only')
    finally:
        if writer:writer.close()
        for con in connections:con.rollback();con.close()

def import_runtime(root,config,manifest_path,replace=False):
    root=Path(root).resolve();manifest_path=Path(manifest_path);m=json.loads(manifest_path.read_text());profile=config['profile'];base=root/'Sqlite'/profile/'Cache';base.mkdir(parents=True,exist_ok=True);cache=base/'EnverusCache.sqlite'
    if m['formatVersion']!=2 or m['profile']!=profile or m['scope']!=config.get('apiFilters',{}):raise RuntimeError('Runtime transfer profile/scope mismatch')
    if cache.exists() and not replace:raise RuntimeError('A cache already exists; explicit --replace is required')
    prefixes={'managedGdb':f'Gdb/{profile}/Output/EnverusGuggWellRecord.gdb/','managedShapefile':f'Shp/{profile}/Output/Current/'};exact={'sourceCache':f'Sqlite/{profile}/Cache/EnverusCache.sqlite','processingState':f'Sqlite/{profile}/Cache/Processed.sqlite'}
    entries={}
    for entry in m['files']:
        rel=entry['path'];role=entry['role']
        if '\\' in rel or Path(rel).is_absolute() or '..' in Path(rel).parts or not ((role in exact and rel==exact[role]) or (role in prefixes and rel.startswith(prefixes[role]))):raise RuntimeError('Unexpected path in managed transfer')
        if rel in entries:raise RuntimeError('Duplicate archive entry')
        entries[rel]=entry
    if not all(p in entries for p in exact.values()):raise RuntimeError('Source or processing state missing')
    if shutil.disk_usage(root).free<sum(e['size'] for e in entries.values())+config.get('minimumFreeDiskGb',20)*1024**3:raise RuntimeError('Insufficient space to restore full GIS state')
    parts=[]
    for part in m['parts']:
        name=part['name']
        if Path(name).name!=name or '/' in name or '\\' in name or not name.startswith('EnverusCache.zip.part'):raise RuntimeError('Unsafe archive part name')
        p=manifest_path.parent/name
        if p.stat().st_size!=part['size'] or hash_file(p)!=part['sha256']:raise RuntimeError('Archive part checksum mismatch')
        parts.append(p)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');staging=root/'Zip/ImportStaging'/stamp;staging.mkdir(parents=True);marker=base/'ImportInProgress.json';marker.write_text(json.dumps(dict(staging=str(staging),manifest=str(manifest_path)),indent=2));published=False
    try:
        with MultipartReader(parts).prepare() as joined,zipfile.ZipFile(joined) as archive:
            if set(archive.namelist())!=set(entries):raise RuntimeError('Archive contents differ from manifest')
            for info in archive.infolist():
                e=entries[info.filename]
                if info.file_size!=e['size']:raise RuntimeError('Archive entry size mismatch')
                out=staging/info.filename;out.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256()
                with archive.open(info) as source,open(out,'wb') as target:
                    while block:=source.read(4*1024**2):target.write(block);h.update(block)
                if h.hexdigest()!=e['sha256']:raise RuntimeError('Runtime file checksum mismatch')
        for rel in exact.values():
            con=sqlite3.connect(staging/rel)
            try:
                if con.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('SQLite runtime validation failed')
                if rel==exact['sourceCache']:
                    meta=dict(con.execute('SELECT * FROM Meta'))
                    if meta['watermark']!=m['watermark'] or json.loads(meta['scope'])!=m['scope']:raise RuntimeError('Watermark/scope validation failed')
            finally:con.close()
        moves=[f'Gdb/{profile}/Output/EnverusGuggWellRecord.gdb',f'Shp/{profile}/Output/Current',exact['processingState'],exact['sourceCache']]
        backup=root/'Zip/ImportBackups'/stamp
        for rel in moves:
            source=staging/rel;target=root/rel
            if not source.exists():continue
            target.resolve().relative_to(root)
            if target.exists():
                if not replace:raise RuntimeError('Managed destination already exists; --replace required')
                saved=backup/rel;saved.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(target),str(saved))
            target.parent.mkdir(parents=True,exist_ok=True);os.replace(source,target)
        published=True;marker.unlink(missing_ok=True)
        return dict(cache=str(cache),includesGIS=True,watermark=m['watermark'],nextSync='incremental',nextBuild='changed records only; project/layer paths remapped locally',sha256Verified=True)
    finally:
        # A failed publication keeps the marker so the nightly task cannot run
        # against a partially restored set. Verified files remain recoverable.
        if published and staging.exists():
            staging.resolve().relative_to((root/'Zip/ImportStaging').resolve());shutil.rmtree(staging)
