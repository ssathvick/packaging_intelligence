"""Explicitly configured file, HTTPS JSON and outbound change-event adapters."""
import csv
import http.client
import io
import ipaddress
import json
import os
import socket
import ssl
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from .db import ROOT, connect, audit
from .documents import ingest
from .engine import evidence, invalidate
from .models import Component, Product

MAX_RESPONSE=5*1024*1024

def allowed_hosts():
    return {h.strip().lower() for h in os.getenv('AXIOM_CONNECTOR_HOSTS','').split(',') if h.strip()}

def resolve_url(url):
    parsed=urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:
        raise ValueError('Use a full HTTPS URL without credentials or fragment')
    hostname=parsed.hostname.lower()
    local_test=os.getenv('AXIOM_TEST_HTTP','0')=='1'
    if parsed.scheme!='https' and not (local_test and parsed.scheme=='http'):
        raise ValueError('Connectors require HTTPS')
    if hostname not in allowed_hosts():
        raise ValueError('Host is not in AXIOM_CONNECTOR_HOSTS; configure the deployment allowlist first')
    port=parsed.port or (443 if parsed.scheme=='https' else 80)
    addresses=socket.getaddrinfo(hostname,port,type=socket.SOCK_STREAM)
    ips=sorted({r[4][0] for r in addresses})
    if not ips: raise ValueError('Host did not resolve')
    if not local_test and any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError('Private, loopback and reserved destinations are blocked')
    return parsed,ips[0],port

def http_request(config, method='GET', payload=None, idempotency=None):
    parsed,ip,port=resolve_url(config['url'])
    # Pin the already-validated address, preserving TLS hostname verification.
    connection=http.client.HTTPSConnection(parsed.hostname,port,timeout=25,context=ssl.create_default_context()) if parsed.scheme=='https' else http.client.HTTPConnection(parsed.hostname,port,timeout=25)
    connection._create_connection=lambda address, timeout=25, source_address=None: socket.create_connection((ip,port),timeout,source_address)
    headers={'Accept':'application/json','User-Agent':'AxiomPack-Local/1.0'}
    secret_env=config.get('secret_env','')
    if secret_env:
        if not secret_env.startswith('AXIOM_SECRET_') or not secret_env.replace('_','').isalnum():
            raise ValueError('Secret references must use AXIOM_SECRET_* environment variables')
        secret=os.getenv(secret_env)
        if not secret: raise ValueError('Referenced connector secret is not configured')
        headers['Authorization']='Bearer '+secret
    body=None
    if payload is not None:
        body=json.dumps(payload).encode()
        headers['Content-Type']='application/json'
    if idempotency: headers['Idempotency-Key']=idempotency
    try:
        connection.request(method,parsed.path+('?' + parsed.query if parsed.query else '') or '/',body=body,headers=headers)
        response=connection.getresponse()
        data=response.read(MAX_RESPONSE+1)
        if len(data)>MAX_RESPONSE: raise ValueError('Connector response exceeds 5 MB')
        if not 200<=response.status<300: raise ValueError(f'Remote HTTP {response.status}; redirects are not followed')
        return response.status,data
    finally: connection.close()

def validate_config(kind, config):
    allowed={'folder':{'folder'},'http_json':{'url','secret_env','record_type','mapping','records_path'},'webhook':{'url','secret_env'}}[kind]
    if set(config)-allowed: raise ValueError('Unsupported connector setting')
    if kind=='folder':
        name=config.get('folder','')
        if not name or not all(ch.isalnum() or ch in '-_' for ch in name) or len(name)>80:
            raise ValueError('Folder must be a simple inbox name, e.g. supplier-drop')
    else:
        # Reject credentials embedded in URLs and query strings, even before connection.
        parsed=urlsplit(config.get('url',''))
        if parsed.scheme!='https' and os.getenv('AXIOM_TEST_HTTP')!='1': raise ValueError('HTTPS URL required')
        if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Provide a URL without credentials, query string or fragment; use secret_env for bearer tokens')
        if parsed.hostname.lower() not in allowed_hosts(): raise ValueError('URL host must first be added to AXIOM_CONNECTOR_HOSTS')
        if config.get('secret_env') and not str(config['secret_env']).startswith('AXIOM_SECRET_'): raise ValueError('Use an AXIOM_SECRET_* variable reference')
        if kind=='http_json':
            if config.get('record_type') not in ('components','products'): raise ValueError('record_type must be components or products')
            if not isinstance(config.get('mapping',{}),dict): raise ValueError('mapping must map canonical names to source field paths')
    return config

def get_path(row,path):
    for part in path.split('.'):
        if not isinstance(row,dict) or part not in row: return None
        row=row[part]
    return row

def map_records(records,mapping):
    if not isinstance(records,list) or len(records)>5000: raise ValueError('Expected an array of at most 5,000 records')
    if any(not isinstance(r,dict) for r in records): raise ValueError('Each record must be an object')
    return [{canonical:get_path(r,path) for canonical,path in mapping.items()} if mapping else r for r in records]

def import_records(c,project,kind,records,actor=None,source_document=None):
    if not records: raise ValueError('No records to import')
    if len(records)>5000: raise ValueError('Import limit is 5,000 rows')
    counts={'created':0,'updated':0,'records':len(records)}
    for raw in records:
        raw=dict(raw)
        if kind=='components':
            if source_document and not raw.get('evidence_id'): raw['evidence_id']=source_document
            model=Component.model_validate(raw)
            d=model.model_dump()
            evidence(c,project,d['evidence_id'])
            d['attributes']=json.dumps(d['attributes'],sort_keys=True)
            old=c.execute('SELECT id,version FROM components WHERE project_id=? AND code=?',(project,d['code'])).fetchone()
            if old:
                c.execute('UPDATE components SET '+','.join(k+'=?' for k in d)+',version=version+1 WHERE id=?',(*d.values(),old['id']))
                counts['updated']+=1
            else:
                c.execute('INSERT INTO components(project_id,'+','.join(d)+') VALUES('+','.join('?' for _ in range(len(d)+1))+')',(project,*d.values()))
                counts['created']+=1
            snapshot=dict(c.execute('SELECT * FROM components WHERE project_id=? AND code=?',(project,d['code'])).fetchone())
            c.execute('INSERT INTO catalog_versions(project_id,entity,entity_id,snapshot,actor,created) VALUES(?,?,?,?,?,?)',(project,'component',snapshot['id'],json.dumps(snapshot),actor,time.time()))
        elif kind=='products':
            # CSV BOM uses component_code and quantity for a single component; JSON supports full bom arrays.
            if 'component_code' in raw:
                code=raw.pop('component_code')
                quantity=raw.pop('quantity',1)
                raw['bom']=[{'component_code':code,'quantity':quantity}]
            model=Product.model_validate(raw)
            d=model.model_dump(exclude={'bom'})
            old=c.execute('SELECT id,archived FROM products WHERE project_id=? AND sku=?',(project,d['sku'])).fetchone()
            if old:
                if old['archived']:raise ValueError('SKU is archived; explicitly restore it before updating or importing it')
                pid=old['id']
                c.execute('UPDATE products SET '+','.join(k+'=?' for k in d)+',version=version+1 WHERE id=?',(*d.values(),pid))
                c.execute('DELETE FROM bom WHERE product_id=?',(pid,))
                counts['updated']+=1
            else:
                pid=c.execute('INSERT INTO products(project_id,'+','.join(d)+') VALUES('+','.join('?' for _ in range(len(d)+1))+')',(project,*d.values())).lastrowid
                counts['created']+=1
            for line in model.bom:
                if set(line)-{'component_code','quantity'}: raise ValueError('BOM lines support component_code and quantity')
                comp=c.execute('SELECT id FROM components WHERE project_id=? AND code=?',(project,line.get('component_code'))).fetchone()
                quantity=float(line.get('quantity',1))
                import math
                if not comp or not math.isfinite(quantity) or quantity<=0: raise ValueError('BOM needs a known component code and a positive finite quantity')
                c.execute('INSERT INTO bom VALUES(?,?,?)',(pid,comp['id'],quantity))
            snapshot=dict(c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone())
            snapshot['bom']=[dict(r) for r in c.execute('SELECT b.quantity,c.code FROM bom b JOIN components c ON c.id=b.component_id WHERE b.product_id=?',(pid,))]
            c.execute('INSERT INTO catalog_versions(project_id,entity,entity_id,snapshot,actor,created) VALUES(?,?,?,?,?,?)',(project,'product',pid,json.dumps(snapshot),actor,time.time()))
        else: raise ValueError('Unknown import type')
    invalidate(c,project,'catalog import')
    audit(c,project,actor,'catalog.imported',kind,{**counts,'evidence':source_document})
    return counts

def run_connector(cid):
    rid=uuid.uuid4().hex
    with connect(write=True) as c:
        row=c.execute('SELECT * FROM connectors WHERE id=?',(cid,)).fetchone()
        if not row: return
        con=dict(row)
        if c.execute('SELECT archived FROM projects WHERE id=?',(con['project_id'],)).fetchone()['archived']:
            raise ValueError('Project is archived; connector execution is paused')
        c.execute('INSERT INTO connector_runs(id,connector_id,status,started) VALUES(?,?,?,?)',(rid,cid,'running',time.time()))
    config=json.loads(con['config'])
    try:
        if con['kind']=='folder':
            folder=ROOT/'inbox'/str(con['project_id'])/config['folder']
            folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            files=sorted(folder.iterdir())[:100]
            counts={'imported':0,'duplicates':0,'failed':0}
            for path in files:
                if path.is_symlink() or not path.is_file(): continue
                if path.stat().st_size>20*1024*1024: counts['failed']+=1; continue
                try:
                    with connect(write=True) as c:
                        result=ingest(c,con['project_id'],path.name,path.read_bytes())
                    counts['duplicates' if result['duplicate'] else 'imported']+=1
                except HTTPException: counts['failed']+=1
            if counts['failed']: raise ValueError(f"{counts['failed']} unsupported or oversized inbox files; accepted files remain imported")
        elif con['kind']=='http_json':
            _,data=http_request(config)
            records=json.loads(data)
            if config.get('records_path'): records=get_path(records,config['records_path'])
            records=map_records(records,config.get('mapping',{}))
            for raw in records:
                candidate=dict(raw)
                if config['record_type']=='components':
                    candidate.setdefault('evidence_id','pending-review')
                    Component.model_validate(candidate)
                else:
                    if 'component_code' in candidate:
                        code=candidate.pop('component_code');quantity=candidate.pop('quantity',1)
                        candidate['bom']=[{'component_code':code,'quantity':quantity}]
                    Product.model_validate(candidate)
            with connect(write=True) as c:
                staged=ingest(c,con['project_id'],f"{con['name'][:100]}-{config['record_type']}.json",json.dumps(records,sort_keys=True,ensure_ascii=False).encode())
                counts={'staged_records':len(records),'document_id':staged['id'],'duplicate':staged['duplicate'],'next':'Review staged JSON and import through the controlled catalog action'}
        else:
            raise ValueError('Webhook is outbound. Deliver an approved change from a scenario.')
        with connect(write=True) as c:
            c.execute("UPDATE connector_runs SET status='succeeded',counts=?,finished=? WHERE id=?",(json.dumps(counts),time.time(),rid))
            c.execute('UPDATE connectors SET last_success=?,last_error=NULL,failures=0,next_run=? WHERE id=?',(time.time(),time.time()+con['interval_seconds'],cid))
            audit(c,con['project_id'],None,'connector.succeeded',cid,counts)
    except Exception as ex:
        # Never log response bodies, authentication headers or secret values.
        msg=safe_error(ex)
        with connect(write=True) as c:
            failures=con['failures']+1
            c.execute("UPDATE connector_runs SET status='failed',error=?,finished=? WHERE id=?",(msg,time.time(),rid))
            c.execute('UPDATE connectors SET last_error=?,failures=?,next_run=? WHERE id=?',(msg,failures,time.time()+min(3600,con['interval_seconds']*2**min(failures,4)),cid))
            audit(c,con['project_id'],None,'connector.failed',cid,{'error':msg})
        raise ValueError(msg) from None

def safe_error(ex):
    if isinstance(ex,(ValueError,HTTPException)):
        # Pydantic errors include original input; expose a generic message instead.
        from pydantic import ValidationError
        if isinstance(ex,ValidationError): return 'Incoming record validation failed; check schema and field mapping'
        value=ex.detail if isinstance(ex,HTTPException) else str(ex)
        return str(value)[:400]
    return f'{type(ex).__name__}: connector operation failed; check endpoint, TLS, mapping and credentials'

def send_delivery(did):
    from .engine import evaluate
    # One writer transaction serializes approval changes with the final send check.
    # Reads remain available under WAL. The bounded network operation may briefly delay writes.
    with connect(write=True) as c:
        row=c.execute('SELECT d.*,con.config,con.project_id,con.enabled FROM deliveries d JOIN connectors con ON con.id=d.connector_id WHERE d.id=?',(did,)).fetchone()
        if not row: return
        d=dict(row)
        if d['status']=='delivered': return
        s=c.execute('SELECT * FROM scenarios WHERE id=?',(d['scenario_id'],)).fetchone()
        archived=c.execute('SELECT archived FROM projects WHERE id=?',(d['project_id'],)).fetchone()['archived']
        if archived or not d['enabled'] or not s or not evaluate(c,s)['approval_current'] or s['status'] not in ('approved','change_requested'):
            c.execute("UPDATE deliveries SET status='failed',error='Connector paused or approval is no longer current' WHERE id=?",(did,))
            return
        c.execute("UPDATE deliveries SET status='sending',attempts=attempts+1 WHERE id=?",(did,))
        try:
            status,_=http_request(json.loads(d['config']),'POST',json.loads(d['payload']),did)
            c.execute("UPDATE deliveries SET status='delivered',remote_status=?,error=NULL,finished=? WHERE id=?",(status,time.time(),did))
            audit(c,d['project_id'],None,'change.delivered',did,{'http_status':status,'idempotency_key':did})
        except Exception as ex:
            c.execute("UPDATE deliveries SET status=?,error=?,finished=? WHERE id=?",('retry' if d['attempts']<2 else 'failed',safe_error(ex),time.time(),did))
