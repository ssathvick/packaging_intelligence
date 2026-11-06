import asyncio
import csv
import hashlib
import hmac
import io
import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import ValidationError
from . import models as m
from .db import ROOT, DB, connect, initialize, audit, verify_audit
from .security import current, csrf, access, admin, login, password_hash, password_ok, digest, SECURE, ORIGINS, SESSION_SECONDS
from .documents import ingest, search, file_path, MAX_UPLOAD
from .engine import component, evidence, evaluate, scenario_row, invalidate
from .connectors import validate_config, import_records, map_records
from .worker import Worker
from . import llm

VERSION='1.2.1'
worker=Worker()
ask_lock=asyncio.Semaphore(1)

@asynccontextmanager
async def lifespan(app):
    initialize()
    with connect() as c:
        empty=not c.execute('SELECT 1 FROM users LIMIT 1').fetchone()
    if empty and not (ROOT/'setup-token').exists():
        (ROOT/'setup-token').write_text(secrets.token_urlsafe(32))
        (ROOT/'setup-token').chmod(0o600)
    if os.getenv('AXIOM_WORKER','1')=='1': worker.start()
    yield
    worker.close()

app=FastAPI(title='AxiomPack Local',version=VERSION,lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=os.getenv('AXIOM_ALLOWED_HOSTS','localhost,127.0.0.1').split(','))
PUBLIC_URL=os.getenv('AXIOM_PUBLIC_URL','').rstrip('/')

@app.middleware('http')
async def guard(request, call_next):
    canonical_host=urlsplit(PUBLIC_URL).hostname if PUBLIC_URL else None
    if canonical_host and request.headers.get('host','').split(':')[0].lower()=='www.'+canonical_host.lower():
        return RedirectResponse(PUBLIC_URL+request.url.path+('?' + request.url.query if request.url.query else ''),status_code=308)
    origin=request.headers.get('origin')
    if origin and origin not in ORIGINS: return JSONResponse({'detail':'Origin is not allowed'},403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        cap=22*1024*1024 if request.url.path.endswith('/documents') else 2*1024*1024
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>cap): return JSONResponse({'detail':'Request body is too large'},413)
        data=[]; total=0
        async for chunk in request.stream():
            total+=len(chunk)
            if total>cap: return JSONResponse({'detail':'Request body is too large'},413)
            data.append(chunk)
        request._body=b''.join(data)
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/auth/login','/api/auth/setup'):
            try: csrf(request,current(request))
            except HTTPException as ex: return JSONResponse({'detail':ex.detail},ex.status_code)
    response=await call_next(request)
    response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
        'X-Robots-Tag':'noindex, nofollow, noarchive',
        'Referrer-Policy':'no-referrer','Permissions-Policy':'camera=(), microphone=(), geolocation=()',
        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'; form-action 'self'"})
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
    if SECURE: response.headers['Strict-Transport-Security']='max-age=31536000'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request,ex):
    return JSONResponse({'detail':'; '.join('.'.join(str(x) for x in e['loc'][1:])+': '+e['msg'] for e in ex.errors())},422)

@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(request,ex):
    return JSONResponse({'detail':'Record conflicts with an existing identifier or linked record'},409)

@app.exception_handler(sqlite3.OperationalError)
async def database_busy(request,ex):
    logging.getLogger('axiom').error('Database operation failed: %s',type(ex).__name__)
    return JSONResponse({'detail':'Database operation could not complete; retry shortly or check service logs'},503)

@app.get('/api/health')
def health():
    with connect() as c:
        c.execute('SELECT 1').fetchone()
        setup=not bool(c.execute('SELECT 1 FROM users LIMIT 1').fetchone())
    return {'status':'ok','version':VERSION,'setup_required':setup,'deployment':'single-host','worker':bool(worker.thread and worker.thread.is_alive())}

@app.get('/robots.txt')
def robots():return PlainTextResponse('User-agent: *\nDisallow: /\n')

@app.post('/api/auth/setup')
def setup(body:m.Setup, request:Request, response:Response):
    with connect(write=True) as c:
        if c.execute('SELECT 1 FROM users LIMIT 1').fetchone(): raise HTTPException(409,'Setup is already complete')
        token_file=ROOT/'setup-token'
        expected=token_file.read_text().strip() if token_file.exists() else ''
        if not expected or not hmac.compare_digest(body.token,expected): raise HTTPException(403,'Invalid local setup token')
        uid=c.execute('INSERT INTO users(email,name,password,admin,created) VALUES(?,?,?,?,?)',(body.email,body.name,password_hash(body.password),1,time.time())).lastrowid
        audit(c,None,uid,'owner.created')
        token,token_csrf,u=login(c,request,body.email,body.password)
    token_file.unlink(missing_ok=True)
    response.set_cookie('axiom_session',token,httponly=True,secure=SECURE,samesite='strict',max_age=SESSION_SECONDS,path='/')
    return {'user':public_user(u),'csrf':token_csrf}

def public_user(u): return {k:u[k] for k in ('id','name','email','admin')}

@app.post('/api/auth/login')
def signin(body:m.Credentials,request:Request,response:Response):
    with connect(write=True) as c: token,token_csrf,u=login(c,request,body.email,body.password)
    response.set_cookie('axiom_session',token,httponly=True,secure=SECURE,samesite='strict',max_age=SESSION_SECONDS,path='/')
    return {'user':public_user(u),'csrf':token_csrf}

@app.post('/api/auth/logout')
def logout(request:Request,response:Response,u=Depends(current)):
    with connect(write=True) as c:
        c.execute('DELETE FROM sessions WHERE hash=?',(digest(request.cookies.get('axiom_session','')),))
        audit(c,None,u['id'],'session.closed')
    response.delete_cookie('axiom_session',path='/')
    return {'ok':True}

@app.get('/api/auth/me')
def me(u=Depends(current)): return {'user':public_user(u),'csrf':u['csrf']}

@app.get('/api/users')
def users(u=Depends(current)):
    admin(u)
    with connect() as c: return [dict(r) for r in c.execute('SELECT id,email,name,admin,active FROM users ORDER BY name')]

@app.post('/api/users')
def new_user(body:m.NewUser,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        uid=c.execute('INSERT INTO users(email,name,password,created) VALUES(?,?,?,?)',(body.email,body.name,password_hash(body.password),time.time())).lastrowid
        audit(c,None,u['id'],'user.created',uid)
    return {'id':uid}

class PasswordChange(m.Model):
    current_password:str
    new_password:str=m.Field(min_length=12,max_length=256)

@app.post('/api/auth/password')
def change_password(body:PasswordChange,u=Depends(current)):
    if not password_ok(body.current_password,u['password']): raise HTTPException(403,'Current password is incorrect')
    with connect(write=True) as c:
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(body.new_password),u['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
        audit(c,None,u['id'],'password.changed')
    return {'ok':True,'message':'Password changed; sign in again'}

@app.post('/api/users/{uid}/disable')
def disable_user(uid:int,u=Depends(current)):
    admin(u)
    if uid==u['id']: raise HTTPException(422,'Cannot disable your own account')
    with connect(write=True) as c:
        c.execute('UPDATE users SET active=0 WHERE id=?',(uid,))
        c.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
        audit(c,None,u['id'],'user.disabled',uid)
    return {'ok':True}

@app.get('/api/projects')
def projects(include_archived:bool=False,u=Depends(current)):
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT p.*,COALESCE(m.role,'reviewer') role FROM projects p LEFT JOIN members m ON m.project_id=p.id AND m.user_id=? WHERE (?=1 OR m.user_id IS NOT NULL) AND (?=1 OR p.archived=0) ORDER BY p.id",(u['id'],u['admin'],include_archived))]

@app.post('/api/projects')
def create_project(body:m.Project,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        if c.execute('SELECT 1 FROM projects WHERE lower(trim(name))=lower(?)',(body.name,)).fetchone():raise HTTPException(409,'A project with this name already exists; open it or choose a distinct name')
        pid=c.execute('INSERT INTO projects(name,synthetic,created) VALUES(?,?,?)',(body.name,int(body.synthetic),time.time())).lastrowid
        c.execute('INSERT INTO members VALUES(?,?,?)',(pid,u['id'],'reviewer'))
        audit(c,pid,u['id'],'project.created',pid,{'name':body.name})
    return {'id':pid}

@app.put('/api/projects/{pid}')
def rename_project(pid:int,body:m.ProjectRename,u=Depends(current)):
    admin(u);name=body.name.strip()
    if len(name)<2:raise HTTPException(422,'Enter a project name')
    with connect(write=True) as c:
        old,_=access(c,u,pid,write=True)
        if c.execute('SELECT 1 FROM projects WHERE id!=? AND lower(trim(name))=lower(?)',(pid,name)).fetchone():raise HTTPException(409,'Another project already uses this name')
        c.execute('UPDATE projects SET name=? WHERE id=?',(name,pid));audit(c,pid,u['id'],'project.renamed',pid,{'before':old['name'],'after':name})
    return {'ok':True}

@app.post('/api/projects/{pid}/archive')
def archive_project(pid:int,body:m.Archive,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        old,_=access(c,u,pid)
        if body.archived and c.execute("SELECT 1 FROM jobs WHERE project_id=? AND status='running'",(pid,)).fetchone():raise HTTPException(409,'A project job is running; wait for it to finish before archiving')
        if bool(old['archived'])==body.archived:return {'ok':True,'archived':body.archived}
        c.execute('UPDATE projects SET archived=? WHERE id=?',(int(body.archived),pid))
        if body.archived:
            c.execute('UPDATE connectors SET enabled=0 WHERE project_id=?',(pid,))
            c.execute("UPDATE documents SET status='failed',error='Project archived before processing; restore the project and retry' WHERE project_id=? AND status='queued'",(pid,))
            c.execute("UPDATE jobs SET status='cancelled',error='Project archived',finished=? WHERE project_id=? AND status='queued'",(time.time(),pid))
            c.execute("UPDATE deliveries SET status='failed',error='Project archived; explicitly requeue after restoration' WHERE connector_id IN (SELECT id FROM connectors WHERE project_id=?) AND status IN ('queued','retry')",(pid,))
        audit(c,pid,u['id'],'project.archived' if body.archived else 'project.restored',pid,{'note':body.note,'connectors_remain_paused':True})
    return {'ok':True,'archived':body.archived}

@app.get('/api/projects/{pid}/members')
def members(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        return [dict(r) for r in c.execute('SELECT u.id,u.name,u.email,m.role FROM members m JOIN users u ON u.id=m.user_id WHERE m.project_id=?',(pid,))]

@app.post('/api/projects/{pid}/members')
def assign_member(pid:int,body:m.Member,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        access(c,u,pid)
        c.execute('INSERT INTO members VALUES(?,?,?) ON CONFLICT(project_id,user_id) DO UPDATE SET role=excluded.role',(pid,body.user_id,body.role))
        audit(c,pid,u['id'],'member.assigned',body.user_id,{'role':body.role})
    return {'ok':True}

@app.get('/api/projects/{pid}/overview')
def overview(pid:int,u=Depends(current)):
    with connect() as c:
        project,role=access(c,u,pid)
        counts={table:c.execute('SELECT count(*) n FROM '+table+' WHERE project_id=?',(pid,)).fetchone()['n'] for table in ('documents','components','products','scenarios','connectors')}
        counts['products']=c.execute('SELECT count(*) n FROM products WHERE project_id=? AND archived=0',(pid,)).fetchone()['n']
        counts['archived_products']=c.execute('SELECT count(*) n FROM products WHERE project_id=? AND archived=1',(pid,)).fetchone()['n']
        docs=[dict(r) for r in c.execute('SELECT status,count(*) count FROM documents WHERE project_id=? GROUP BY status',(pid,))]
        events=[dict(r) for r in c.execute('SELECT a.id,a.action,a.target,a.created,u.name actor FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE project_id=? ORDER BY a.id DESC LIMIT 12',(pid,))]
    return {'project':project,'role':role,'counts':counts,'documents':docs,'events':events}

@app.get('/api/projects/{pid}/documents')
def documents(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        return [dict(r) for r in c.execute('SELECT d.*,u.name reviewer,(SELECT count(*) FROM fields f WHERE f.document_id=d.id) field_count FROM documents d LEFT JOIN users u ON u.id=d.reviewed_by WHERE project_id=? ORDER BY created DESC LIMIT 1000',(pid,))]

@app.post('/api/projects/{pid}/documents')
async def upload(pid:int,file:UploadFile=File(...),u=Depends(current)):
    content=await file.read(MAX_UPLOAD+1)
    with connect(write=True) as c:
        access(c,u,pid,write=True)
        n=c.execute("SELECT count(*) n FROM jobs WHERE project_id=? AND status IN ('queued','running')",(pid,)).fetchone()['n']
        if n>=100: raise HTTPException(429,'Project already has 100 pending jobs')
        return ingest(c,pid,file.filename or 'upload.txt',content,u['id'])

def document(c,pid,did):
    doc=c.execute('SELECT * FROM documents WHERE id=? AND project_id=?',(did,pid)).fetchone()
    if not doc: raise HTTPException(404,'Document not found')
    return dict(doc)

@app.get('/api/projects/{pid}/documents/{did}')
def document_detail(pid:int,did:str,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        doc=document(c,pid,did)
        return {**doc,'fields':[dict(r) for r in c.execute('SELECT * FROM fields WHERE document_id=? ORDER BY page,id',(did,))],
            'chunks':[dict(r) for r in c.execute('SELECT id,page,text FROM chunks WHERE document_id=? ORDER BY id LIMIT 500',(did,))]}

@app.get('/api/projects/{pid}/documents/{did}/file')
def download(pid:int,did:str,u=Depends(current)):
    with connect() as c: access(c,u,pid); doc=document(c,pid,did)
    path=file_path(doc)
    if not path.exists(): raise HTTPException(410,'Source file missing; restore from backup')
    return FileResponse(path,filename=doc['name'],media_type='application/octet-stream')

@app.post('/api/projects/{pid}/documents/{did}/review')
def review_document(pid:int,did:str,body:m.FieldReview,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True)
        doc=document(c,pid,did)
        if doc['status'] not in ('review','approved'): raise HTTPException(409,'Document must finish extraction first')
        valid={str(r['id']) for r in c.execute('SELECT id FROM fields WHERE document_id=?',(did,))}
        if set(body.fields)-valid: raise HTTPException(422,'Unknown extracted field')
        if any(len(v)>500 for v in body.fields.values()): raise HTTPException(422,'Field values must be 500 characters or fewer')
        for fid,value in body.fields.items():
            c.execute("UPDATE fields SET value=?,status='reviewed',reviewed_by=? WHERE id=? AND document_id=?",(value.strip(),u['id'],fid,did))
        c.execute("UPDATE fields SET status='reviewed',reviewed_by=? WHERE document_id=?",(u['id'],did))
        c.execute("UPDATE documents SET status='approved',reviewed_by=?,reviewed_at=? WHERE id=?",(u['id'],time.time(),did))
        if doc['status']=='approved': invalidate(c,pid,'reviewed source changed',document_id=did)
        audit(c,pid,u['id'],'document.approved',did,{'note':body.note,'field_corrections':body.fields})
    return {'ok':True}

@app.post('/api/projects/{pid}/documents/{did}/reopen')
def reopen(pid:int,did:str,body:m.Note,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True); doc=document(c,pid,did)
        if doc['status']!='approved': raise HTTPException(409,'Only an approved document can be reopened')
        c.execute("UPDATE documents SET status='review',reviewed_by=NULL,reviewed_at=NULL WHERE id=?",(did,))
        invalidate(c,pid,'source reopened',document_id=did)
        audit(c,pid,u['id'],'document.reopened',did,{'note':body.note})
    return {'ok':True}

@app.post('/api/projects/{pid}/documents/{did}/retry')
def retry_document(pid:int,did:str,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True); doc=document(c,pid,did)
        if doc['status']!='failed': raise HTTPException(409,'Only failed documents can be retried')
        c.execute("UPDATE documents SET status='queued',error=NULL WHERE id=?",(did,))
        queue(c,pid,'document',did)
        audit(c,pid,u['id'],'document.retry',did)
    return {'ok':True}

@app.get('/api/projects/{pid}/catalog')
def catalog(pid:int,include_archived:bool=False,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        from .engine import decoded_component
        comps=[decoded_component(r) for r in c.execute('SELECT * FROM components WHERE project_id=? ORDER BY code',(pid,))]
        prods=[dict(r) for r in c.execute('SELECT * FROM products WHERE project_id=? AND (?=1 OR archived=0) ORDER BY sku',(pid,include_archived))]
        for p in prods:
            p['bom']=[dict(r) for r in c.execute('SELECT b.quantity,c.code,c.name,c.id component_id FROM bom b JOIN components c ON c.id=b.component_id WHERE b.product_id=?',(p['id'],))]
    return {'components':comps,'products':prods}

@app.post('/api/projects/{pid}/components')
def save_component(pid:int,body:m.Component,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True)
        return import_records(c,pid,'components',[body.model_dump()],u['id'])

@app.get('/api/projects/{pid}/components/{cid}/history')
def component_history(pid:int,cid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid);component(c,pid,cid)
        return [dict(r) for r in c.execute("SELECT * FROM catalog_versions WHERE project_id=? AND entity='component' AND entity_id=? ORDER BY id DESC",(pid,cid))]

@app.post('/api/projects/{pid}/products')
def save_product(pid:int,body:m.Product,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True)
        if c.execute('SELECT 1 FROM products WHERE project_id=? AND sku=?',(pid,body.sku)).fetchone():raise HTTPException(409,'This SKU exists; use Edit product to preserve and review its complete BOM')
        try: return import_records(c,pid,'products',[body.model_dump()],u['id'])
        except (ValidationError,ValueError) as ex: raise HTTPException(422,'Invalid product or BOM: '+str(ex)[:250]) from None

@app.put('/api/projects/{pid}/products/{product_id}')
def edit_product(pid:int,product_id:int,body:m.ProductUpdate,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True)
        old=c.execute('SELECT * FROM products WHERE id=? AND project_id=?',(product_id,pid)).fetchone()
        if not old:raise HTTPException(404,'Product not found')
        if old['archived']:raise HTTPException(409,'Product is archived; restore it before editing')
        if old['version']!=body.version:raise HTTPException(409,'Product changed since this editor opened; reload it before saving')
        conflict=c.execute('SELECT id FROM products WHERE project_id=? AND sku=? AND id!=?',(pid,body.sku,product_id)).fetchone()
        if conflict:raise HTTPException(409,'Another product already uses that SKU')
        c.execute('UPDATE products SET sku=? WHERE id=?',(body.sku,product_id))
        try:result=import_records(c,pid,'products',[body.model_dump(exclude={'version'})],u['id'])
        except (ValidationError,ValueError) as ex:raise HTTPException(422,'Invalid product or BOM: '+str(ex)[:250]) from None
        audit(c,pid,u['id'],'product.edited',product_id,{'before_sku':old['sku'],'sku':body.sku,'previous_version':body.version})
    return result

@app.post('/api/projects/{pid}/products/{product_id}/archive')
def archive_product(pid:int,product_id:int,body:m.Archive,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True)
        old=c.execute('SELECT * FROM products WHERE id=? AND project_id=?',(product_id,pid)).fetchone()
        if not old:raise HTTPException(404,'Product not found')
        if bool(old['archived'])==body.archived:return {'ok':True}
        c.execute('UPDATE products SET archived=?,version=version+1 WHERE id=?',(int(body.archived),product_id))
        snapshot=dict(c.execute('SELECT * FROM products WHERE id=?',(product_id,)).fetchone())
        snapshot['bom']=[dict(r) for r in c.execute('SELECT b.quantity,co.code FROM bom b JOIN components co ON co.id=b.component_id WHERE b.product_id=?',(product_id,))]
        c.execute('INSERT INTO catalog_versions(project_id,entity,entity_id,snapshot,actor,created) VALUES(?,?,?,?,?,?)',(pid,'product',product_id,json.dumps(snapshot),u['id'],time.time()))
        invalidate(c,pid,'product archive state changed')
        audit(c,pid,u['id'],'product.archived' if body.archived else 'product.restored',product_id,{'note':body.note})
    return {'ok':True}

@app.get('/api/projects/{pid}/products/{product_id}/history')
def product_history(pid:int,product_id:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        if not c.execute('SELECT 1 FROM products WHERE id=? AND project_id=?',(product_id,pid)).fetchone():raise HTTPException(404,'Product not found')
        return [dict(r) for r in c.execute("SELECT * FROM catalog_versions WHERE project_id=? AND entity='product' AND entity_id=? ORDER BY id DESC",(pid,product_id))]

class Import(m.Model):
    document_id:str
    record_type:m.Literal['components','products']
    mapping:dict[str,str]=m.Field(default_factory=dict)

@app.post('/api/projects/{pid}/catalog/import')
def catalog_import(pid:int,body:Import,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True)
        doc=evidence(c,pid,body.document_id)
        path=file_path(doc)
        try:
            if path.suffix=='.csv': rows=list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
            elif path.suffix=='.json': rows=json.loads(path.read_text())
            else: raise ValueError('Structured import requires reviewed CSV or JSON')
            rows=map_records(rows,body.mapping)
            return import_records(c,pid,body.record_type,rows,u['id'],body.document_id)
        except (ValidationError,ValueError) as ex: raise HTTPException(422,'Import validation failed. '+str(ex)[:400]) from None

@app.get('/api/projects/{pid}/search')
def evidence_search(pid:int,q:str='',approved:bool=True,u=Depends(current)):
    if len(q)>2000: raise HTTPException(422,'Query is too long')
    with connect() as c: access(c,u,pid); return search(c,pid,q,approved)

@app.post('/api/projects/{pid}/ask')
async def ask(pid:int,body:m.Question,u=Depends(current)):
    with connect(write=True) as c: access(c,u,pid); sources=search(c,pid,body.question,True,6)
    if ask_lock.locked(): raise HTTPException(429,'Local model is answering another question; try again shortly')
    async with ask_lock:
        try: result=await llm.answer(body.question,sources)
        except (httpx.HTTPError,ValueError,KeyError,TypeError): raise HTTPException(503,'Local model is unavailable or returned an invalid response. Check Ollama and retry.') from None
    with connect(write=True) as c: audit(c,pid,u['id'],'knowledge.answered','',{'question':body.question,'model':llm.MODEL,'source_ids':[s['id'] for s in sources],'citation_repair_attempted':result.get('citation_repair_attempted',False)})
    return {**result,'sources':sources,'basis':'Reviewed source documents only; AI output requires human verification'}

@app.get('/api/projects/{pid}/scenarios')
def scenarios(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        rows=[]
        for s in c.execute('SELECT * FROM scenarios WHERE project_id=? ORDER BY created DESC',(pid,)):
            snap=c.execute('SELECT snapshot FROM approval_snapshots WHERE scenario_id=? ORDER BY id DESC LIMIT 1',(s['id'],)).fetchone()
            ev=json.loads(snap['snapshot']) if snap and s['status']=='implemented' else evaluate(c,s)
            rows.append({**dict(s),'evaluation':ev})
        return rows

@app.get('/api/projects/{pid}/opportunities')
def opportunity_screen(pid:int,u=Depends(current)):
    from .engine import opportunities
    with connect() as c:access(c,u,pid);return opportunities(c,pid)

@app.get('/api/projects/{pid}/programmes')
def programmes(pid:int,u=Depends(current)):
    from .programmes import rollup
    with connect() as c:
        access(c,u,pid)
        return [rollup(c,row) for row in c.execute('SELECT * FROM programmes WHERE project_id=? ORDER BY created',(pid,))]

@app.post('/api/projects/{pid}/programmes')
def create_programme(pid:int,body:m.Programme,u=Depends(current)):
    from .programmes import validate_members
    with connect(write=True) as c:
        access(c,u,pid,review=True);validate_members(c,pid,body.scenario_ids);evidence(c,pid,body.evidence_id)
        gid=uuid.uuid4().hex;d=body.model_dump();d['scenario_ids']=json.dumps(d['scenario_ids'])
        c.execute('INSERT INTO programmes(id,project_id,'+','.join(d)+',created) VALUES('+','.join('?' for _ in range(len(d)+3))+')',(gid,pid,*d.values(),time.time()))
        audit(c,pid,u['id'],'programme.created',gid,body.model_dump())
    return {'id':gid}

@app.get('/api/projects/{pid}/programmes/{gid}')
def programme_detail(pid:int,gid:str,u=Depends(current)):
    from .programmes import rollup
    with connect() as c:
        access(c,u,pid)
        row=c.execute('SELECT * FROM programmes WHERE id=? AND project_id=?',(gid,pid)).fetchone()
        if not row:raise HTTPException(404,'Programme not found')
        return rollup(c,row)

@app.post('/api/projects/{pid}/scenarios')
def create_scenario(pid:int,body:m.Scenario,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True)
        component(c,pid,body.baseline_id);component(c,pid,body.candidate_id)
        sid=uuid.uuid4().hex
        inputs=body.model_dump(exclude={'name','baseline_id','candidate_id'})
        c.execute('INSERT INTO scenarios(id,project_id,name,baseline_id,candidate_id,inputs,created) VALUES(?,?,?,?,?,?,?)',(sid,pid,body.name,body.baseline_id,body.candidate_id,json.dumps(inputs),time.time()))
        audit(c,pid,u['id'],'scenario.created',sid,body.model_dump())
    return {'id':sid}

@app.put('/api/projects/{pid}/scenarios/{sid}')
def update_scenario(pid:int,sid:str,body:m.Scenario,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,write=True); s=scenario_row(c,pid,sid)
        if s['status'] in ('change_requested','implemented'): raise HTTPException(409,'Create a new scenario after a change has been requested')
        component(c,pid,body.baseline_id); component(c,pid,body.candidate_id)
        inputs=body.model_dump(exclude={'name','baseline_id','candidate_id'})
        c.execute("UPDATE scenarios SET name=?,baseline_id=?,candidate_id=?,inputs=?,version=version+1,status='draft',qualifications='{}',approved_by=NULL,approved_at=NULL,approved_fingerprint=NULL WHERE id=?",(body.name,body.baseline_id,body.candidate_id,json.dumps(inputs),sid))
        audit(c,pid,u['id'],'scenario.revised',sid,body.model_dump())
    return {'ok':True}

@app.get('/api/projects/{pid}/scenarios/{sid}')
def scenario_detail(pid:int,sid:str,u=Depends(current)):
    with connect() as c:
        access(c,u,pid); s=scenario_row(c,pid,sid)
        snapshot=c.execute('SELECT snapshot FROM approval_snapshots WHERE scenario_id=? ORDER BY id DESC LIMIT 1',(sid,)).fetchone()
        return {**s,'evaluation':evaluate(c,s),'approved_evaluation':json.loads(snapshot['snapshot']) if snapshot else None}

@app.post('/api/projects/{pid}/scenarios/{sid}/qualifications')
def qualify(pid:int,sid:str,body:m.Qualification,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True); s=scenario_row(c,pid,sid)
        if s['status'] not in ('draft','qualified'): raise HTTPException(409,'Revise the scenario before changing qualification records')
        evidence(c,pid,body.evidence_id)
        ev=evaluate(c,s)
        if not ev['eligible']: raise HTTPException(422,'Resolve component compatibility or evidence issues before qualification')
        records=json.loads(s['qualifications'])
        records[body.key]={**body.model_dump(),'by':u['id'],'at':time.time(),'fingerprint':ev['fingerprint']}
        c.execute('UPDATE scenarios SET qualifications=? WHERE id=?',(json.dumps(records),sid))
        updated=scenario_row(c,pid,sid)
        if evaluate(c,updated)['qualification_complete']: c.execute("UPDATE scenarios SET status='qualified' WHERE id=?",(sid,))
        else: c.execute("UPDATE scenarios SET status='draft' WHERE id=?",(sid,))
        audit(c,pid,u['id'],'qualification.recorded',sid,body.model_dump())
    return {'ok':True}

@app.post('/api/projects/{pid}/scenarios/{sid}/approve')
def approve(pid:int,sid:str,body:m.Note,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True); s=scenario_row(c,pid,sid); ev=evaluate(c,s)
        if not ev['can_approve']: raise HTTPException(409,'Approval requires eligible components and all three current, evidence-backed qualifications')
        c.execute("UPDATE scenarios SET status='approved',approved_by=?,approved_at=?,approved_fingerprint=? WHERE id=?",(u['id'],time.time(),ev['fingerprint'],sid))
        frozen={**ev,'approval_current':True,'approved_as_of':time.time()}
        c.execute('INSERT INTO approval_snapshots(scenario_id,version,snapshot,approved_by,created) VALUES(?,?,?,?,?)',(sid,s['version'],json.dumps(frozen),u['id'],time.time()))
        audit(c,pid,u['id'],'scenario.approved',sid,{'note':body.note,'fingerprint':ev['fingerprint'],'financials':ev['financials']})
    return {'ok':True}

@app.post('/api/projects/{pid}/scenarios/{sid}/request-change')
def request_change(pid:int,sid:str,body:m.Note,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True); s=scenario_row(c,pid,sid)
        if s['status']!='approved' or not evaluate(c,s)['approval_current']: raise HTTPException(409,'A current approval is required')
        c.execute("UPDATE scenarios SET status='change_requested' WHERE id=?",(sid,))
        audit(c,pid,u['id'],'change.requested',sid,{'note':body.note})
    return {'ok':True}

@app.post('/api/projects/{pid}/scenarios/{sid}/implement')
def implement(pid:int,sid:str,body:m.Implementation,u=Depends(current)):
    with connect(write=True) as c:
        access(c,u,pid,review=True); s=scenario_row(c,pid,sid)
        if s['status']!='change_requested' or not evaluate(c,s)['approval_current']: raise HTTPException(409,'A current requested change is required')
        evidence(c,pid,body.evidence_id)
        record={**body.model_dump(),'by':u['id'],'at':time.time()}
        c.execute("UPDATE scenarios SET status='implemented',implementation=? WHERE id=?",(json.dumps(record),sid))
        audit(c,pid,u['id'],'change.implementation_acknowledged',sid,record)
    return {'ok':True,'message':'Manual implementation acknowledgement recorded; no ERP success is implied'}

@app.get('/api/projects/{pid}/scenarios/{sid}/export')
def export_scenario(pid:int,sid:str,u=Depends(current)):
    with connect() as c:
        project,_=access(c,u,pid); s=scenario_row(c,pid,sid)
        pack={'schema':'axiompack.change.v1','project':project,'scenario':s,'evaluation':evaluate(c,s),
              'events':[dict(r) for r in c.execute('SELECT * FROM audit WHERE project_id=? AND target=? ORDER BY id',(pid,sid))],
              'exported_at':time.time(),'audit_chain_valid':verify_audit(c)}
        pack['benefits']=[dict(r) for r in c.execute('SELECT * FROM benefits WHERE scenario_id=?',(sid,))]
        pack['approval_snapshots']=[{**dict(r),'snapshot':json.loads(r['snapshot'])} for r in c.execute('SELECT * FROM approval_snapshots WHERE scenario_id=? ORDER BY id',(sid,))]
    return JSONResponse(pack,headers={'Content-Disposition':f'attachment; filename="scenario-{sid[:8]}.json"'})

class Benefit(m.Model):
    evidence_id:str
    period_start:str
    period_end:str
    actual_units:int=m.Field(gt=0,le=10000000000)
    baseline_price:float=m.Field(ge=0,le=10000000)
    actual_price:float=m.Field(ge=0,le=10000000)
    actual_extra:float=m.Field(ge=0,le=100000000000)
    actual_transition:float=m.Field(ge=0,le=100000000000)
    note:str=m.Field(min_length=10,max_length=2000)

@app.post('/api/projects/{pid}/scenarios/{sid}/benefits')
def record_benefits(pid:int,sid:str,body:Benefit,u=Depends(current)):
    from datetime import date
    try: start=date.fromisoformat(body.period_start);end=date.fromisoformat(body.period_end)
    except ValueError: raise HTTPException(422,'Use ISO dates YYYY-MM-DD') from None
    if start>end or end>date.today(): raise HTTPException(422,'Benefit period must be completed and dates must be in order')
    with connect(write=True) as c:
        access(c,u,pid,review=True);s=scenario_row(c,pid,sid)
        if s['status']!='implemented': raise HTTPException(409,'Record implementation before recording realised benefits')
        evidence(c,pid,body.evidence_id)
        if c.execute('SELECT 1 FROM benefits WHERE scenario_id=? AND period_start<=? AND period_end>=?',(sid,body.period_end,body.period_start)).fetchone():
            raise HTTPException(409,'Benefit period overlaps a previously recorded period')
        bid=uuid.uuid4().hex; d=body.model_dump()
        c.execute('INSERT INTO benefits(id,project_id,scenario_id,'+','.join(d)+',recorded_by,created) VALUES('+','.join('?' for _ in range(len(d)+5))+')',(bid,pid,sid,*d.values(),u['id'],time.time()))
        audit(c,pid,u['id'],'benefit.recorded',sid,{**d,'id':bid})
    return {'id':bid}

@app.get('/api/projects/{pid}/scenarios/{sid}/benefits')
def benefits(pid:int,sid:str,u=Depends(current)):
    from .engine import money
    from decimal import Decimal
    with connect() as c:
        access(c,u,pid);scenario_row(c,pid,sid)
        rows=[dict(r) for r in c.execute('SELECT * FROM benefits WHERE scenario_id=? ORDER BY period_start',(sid,))]
    for r in rows:
        r['realised_net']=money((Decimal(str(r['baseline_price']))-Decimal(str(r['actual_price'])))*r['actual_units']-Decimal(str(r['actual_extra']))-Decimal(str(r['actual_transition'])))
    return rows

def queue(c,pid,kind,target):
    if c.execute("SELECT 1 FROM jobs WHERE kind=? AND target=? AND status IN ('queued','running')",(kind,target)).fetchone(): raise HTTPException(409,'An operation is already queued or running')
    jid=uuid.uuid4().hex
    c.execute('INSERT INTO jobs(id,project_id,kind,target,status,created) VALUES(?,?,?,?,?,?)',(jid,pid,kind,target,'queued',time.time()))
    return jid

@app.get('/api/projects/{pid}/connectors')
def connectors(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        rows=[dict(r) for r in c.execute('SELECT * FROM connectors WHERE project_id=? ORDER BY name',(pid,))]
        for r in rows:
            r['config']=json.loads(r['config'])
            if r['kind']=='folder': r['inbox_path']=str(ROOT/'inbox'/str(pid)/r['config']['folder'])
            r['runs']=[dict(x) for x in c.execute('SELECT * FROM connector_runs WHERE connector_id=? ORDER BY started DESC LIMIT 8',(r['id'],))]
    return rows

@app.post('/api/projects/{pid}/connectors')
def create_connector(pid:int,body:m.Connector,u=Depends(current)):
    admin(u)
    try: validate_config(body.kind,body.config)
    except ValueError as ex: raise HTTPException(422,str(ex)) from None
    with connect(write=True) as c:
        access(c,u,pid)
        cid=uuid.uuid4().hex
        c.execute('INSERT INTO connectors(id,project_id,name,kind,config,enabled,interval_seconds) VALUES(?,?,?,?,?,?,?)',(cid,pid,body.name,body.kind,json.dumps(body.config),int(body.enabled),body.interval_seconds))
        if body.kind=='folder': (ROOT/'inbox'/str(pid)/body.config['folder']).mkdir(parents=True,exist_ok=True,mode=0o700)
        audit(c,pid,u['id'],'connector.created',cid,{'kind':body.kind,'name':body.name})
    return {'id':cid}

@app.put('/api/projects/{pid}/connectors/{cid}')
def edit_connector(pid:int,cid:str,body:m.Connector,u=Depends(current)):
    admin(u)
    try: validate_config(body.kind,body.config)
    except ValueError as ex: raise HTTPException(422,str(ex)) from None
    with connect(write=True) as c:
        access(c,u,pid)
        if not c.execute('SELECT 1 FROM connectors WHERE id=? AND project_id=?',(cid,pid)).fetchone(): raise HTTPException(404,'Connector not found')
        c.execute('UPDATE connectors SET name=?,kind=?,config=?,enabled=?,interval_seconds=?,next_run=0 WHERE id=?',(body.name,body.kind,json.dumps(body.config),int(body.enabled),body.interval_seconds,cid))
        audit(c,pid,u['id'],'connector.updated',cid,{'enabled':body.enabled,'kind':body.kind})
    return {'ok':True}

@app.post('/api/projects/{pid}/connectors/{cid}/run')
def run_connector(pid:int,cid:str,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        access(c,u,pid)
        con=c.execute('SELECT * FROM connectors WHERE id=? AND project_id=?',(cid,pid)).fetchone()
        if not con: raise HTTPException(404,'Connector not found')
        if con['kind']=='webhook': raise HTTPException(422,'Send an approved scenario change through this outbound connector')
        jid=queue(c,pid,'connector',cid)
        audit(c,pid,u['id'],'connector.queued',cid)
    return {'job_id':jid}

@app.post('/api/projects/{pid}/scenarios/{sid}/deliver')
def deliver(pid:int,sid:str,body:m.Delivery,u=Depends(current)):
    admin(u)
    with connect(write=True) as c:
        access(c,u,pid);s=scenario_row(c,pid,sid);ev=evaluate(c,s)
        if s['status']!='change_requested' or not ev['approval_current']: raise HTTPException(409,'Request a current approved change first')
        con=c.execute("SELECT * FROM connectors WHERE id=? AND project_id=? AND kind='webhook' AND enabled=1",(body.connector_id,pid)).fetchone()
        if not con: raise HTTPException(422,'Choose an enabled outbound webhook connector in this project')
        payload=json.dumps({'schema':'axiompack.change.v1','scenario_id':sid,'version':s['version'],'fingerprint':ev['fingerprint'],
            'baseline':ev['baseline'],'candidate':ev['candidate'],'affected_products':ev['affected_products'],'financials':ev['financials'],
            'qualifications':ev['qualifications'],'approved_by':s['approved_by'],'approved_at':s['approved_at']},sort_keys=True)
        old=c.execute('SELECT id,status FROM deliveries WHERE connector_id=? AND scenario_id=? AND payload=?',(con['id'],sid,payload)).fetchone()
        if old:
            if old['status']=='delivered': return {'id':old['id'],'status':'delivered','duplicate':True}
            did=old['id']; c.execute("UPDATE deliveries SET status='queued',error=NULL WHERE id=?",(did,))
        else:
            did=uuid.uuid4().hex
            c.execute('INSERT INTO deliveries(id,connector_id,scenario_id,payload,status,created) VALUES(?,?,?,?,?,?)',(did,con['id'],sid,payload,'queued',time.time()))
        queue(c,pid,'delivery',did)
        audit(c,pid,u['id'],'change.delivery_queued',did,{'scenario_id':sid,'connector_id':con['id']})
    return {'id':did,'status':'queued'}

@app.get('/api/projects/{pid}/operations')
def operations(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        return {'jobs':[dict(r) for r in c.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 100',(pid,))],
            'deliveries':[dict(r) for r in c.execute('SELECT d.id,d.scenario_id,d.connector_id,d.status,d.attempts,d.error,d.remote_status,d.created FROM deliveries d JOIN connectors c ON c.id=d.connector_id WHERE c.project_id=? ORDER BY d.created DESC LIMIT 100',(pid,))]}

@app.get('/api/projects/{pid}/audit')
def audit_log(pid:int,u=Depends(current)):
    with connect() as c:
        access(c,u,pid)
        return {'chain_valid':verify_audit(c),'events':[dict(r) for r in c.execute('SELECT a.*,u.name actor_name FROM audit a LEFT JOIN users u ON u.id=a.actor WHERE project_id=? ORDER BY id DESC LIMIT 1000',(pid,))]}

@app.get('/api/system')
async def system(u=Depends(current)):
    admin(u)
    status={'available':False,'model':llm.MODEL}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r=await client.get(llm.BASE_URL+'/api/tags'); r.raise_for_status()
            tags=r.json()['models']
            status={'available':any(x['name']==llm.MODEL for x in tags),'model':llm.MODEL,'installed':[x['name'] for x in tags]}
    except (httpx.HTTPError,KeyError,ValueError): pass
    with connect() as c: valid=verify_audit(c)
    return {'version':VERSION,'database':'SQLite WAL','data_path':str(ROOT),'worker':bool(worker.thread and worker.thread.is_alive()),
        'model':status,'context_tokens':int(os.getenv('OLLAMA_NUM_CTX','8192')),'secure_cookies':SECURE,
        'origins':sorted(ORIGINS),'connector_hosts':sorted(__import__('backend.connectors',fromlist=['allowed_hosts']).allowed_hosts()),
        'public_url':PUBLIC_URL,
        'audit_chain_valid':valid,'ocr':'Tesseract English; 50-page PDF limit',
        'deployment_note':'Single host. External identity, high availability and customer-specific SAP/PLM adapters require deployment configuration and validation.'}

@app.post('/api/sample-project')
def sample_project(body:m.SampleCreate|None=None,u=Depends(current)):
    admin(u)
    from .sample import create_sample
    body=body or m.SampleCreate()
    with connect(write=True) as c:
        if body.create_new:
            if not body.request_key:raise HTTPException(422,'Explicit new-demo creation requires an idempotency request key')
            old=c.execute('SELECT p.* FROM sample_requests r JOIN projects p ON p.id=r.project_id WHERE r.user_id=? AND r.request_key=?',(u['id'],body.request_key)).fetchone()
            if old:return {'id':old['id'],'reused':True}
        else:
            old=c.execute("SELECT * FROM projects WHERE sample_template='clearcare' AND archived=0 ORDER BY id LIMIT 1").fetchone()
            if old:return {'id':old['id'],'reused':True}
        name=body.name.strip()
        if len(name)<2:raise HTTPException(422,'Enter a demo project name')
        if c.execute('SELECT 1 FROM projects WHERE lower(trim(name))=lower(?)',(name,)).fetchone():raise HTTPException(409,'Project name already exists; open that project instead')
        result=create_sample(c,u['id'],name)
        if body.request_key:c.execute('INSERT INTO sample_requests VALUES(?,?,?)',(u['id'],body.request_key,result['id']))
        return result

WEB=Path(__file__).resolve().parents[1]/'web'
app.mount('/assets',StaticFiles(directory=WEB),name='assets')

@app.get('/')
def index(): return FileResponse(WEB/'index.html',headers={'Cache-Control':'no-cache'})
