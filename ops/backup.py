"""Online SQLite backup plus immutable source files. Run as the service owner."""
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.db import ROOT, DB

def backup(destination):
    root=Path(destination).resolve()
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=root/('axiompack-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    target.mkdir(mode=0o700)
    (target/'uploads').mkdir(mode=0o700)
    with sqlite3.connect(DB) as source,sqlite3.connect(target/'axiompack.sqlite3') as dest:
        source.backup(dest)
    (target/'axiompack.sqlite3').chmod(0o600)
    with sqlite3.connect(target/'axiompack.sqlite3') as c:
        rows=c.execute('SELECT id,name,sha256 FROM documents').fetchall()
    for did,name,sha in rows:
        filename=did+Path(name).suffix.lower()
        src=ROOT/'uploads'/filename
        if not src.is_file() or hashlib.sha256(src.read_bytes()).hexdigest()!=sha:
            raise RuntimeError('Source file missing or hash mismatch: '+did)
        shutil.copyfile(src,target/'uploads'/filename)
        (target/'uploads'/filename).chmod(0o600)
    manifest={'schema':'axiompack.backup.v1','created':datetime.now(timezone.utc).isoformat(),'documents':len(rows),
        'database_sha256':hashlib.sha256((target/'axiompack.sqlite3').read_bytes()).hexdigest(),
        'note':'Contains customer data. Store on encrypted, access-controlled media. Environment secrets require separate secure backup.'}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2))
    return str(target)

def verify(target):
    target=Path(target).resolve()
    manifest=json.loads((target/'manifest.json').read_text())
    if manifest['database_sha256']!=hashlib.sha256((target/'axiompack.sqlite3').read_bytes()).hexdigest(): raise RuntimeError('Database hash mismatch')
    with sqlite3.connect('file:'+str(target/'axiompack.sqlite3')+'?mode=ro',uri=True) as c:
        if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok': raise RuntimeError('Database integrity check failed')
        if c.execute('PRAGMA foreign_key_check').fetchall(): raise RuntimeError('Foreign key check failed')
        rows=c.execute('SELECT id,name,sha256 FROM documents').fetchall()
    for did,name,sha in rows:
        path=target/'uploads'/(did+Path(name).suffix.lower())
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha: raise RuntimeError('Source integrity check failed: '+did)
    if len(rows)!=manifest['documents']: raise RuntimeError('Document count mismatch')
    return {'verified':True,'documents':len(rows),'path':str(target)}

def restore(source,target):
    verify(source)
    target=Path(target).resolve()
    if target.exists() and any(target.iterdir()): raise RuntimeError('Restore target must be a new or empty directory; never overwrite a live database')
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    shutil.copyfile(Path(source)/'axiompack.sqlite3',target/'axiompack.sqlite3')
    (target/'axiompack.sqlite3').chmod(0o600)
    shutil.copytree(Path(source)/'uploads',target/'uploads',dirs_exist_ok=True)
    # Revoke sessions in restored deployments.
    with sqlite3.connect(target/'axiompack.sqlite3') as c: c.execute('DELETE FROM sessions')
    return {'restored':True,'target':str(target),'sessions_revoked':True}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['create','verify','restore'])
    parser.add_argument('path')
    parser.add_argument('--target')
    args=parser.parse_args()
    if args.action=='create': result=verify(backup(args.path))
    elif args.action=='verify': result=verify(args.path)
    else:
        if not args.target: parser.error('restore requires --target')
        result=restore(args.path,args.target)
    print(json.dumps(result))
