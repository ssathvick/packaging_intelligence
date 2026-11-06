import json,time
from fastapi.testclient import TestClient
from backend import db
from backend.main import app
from backend.documents import process_document
from backend.worker import Worker
from test_cpg_programmes import tiny

def payload(p,**changes):
    body={k:p[k] for k in ('sku','name','annual_units','plant','formula','version')}
    body['bom']=[{'component_code':b['code'],'quantity':b['quantity']} for b in p['bom']]
    return {**body,**changes}

def test_full_bom_edit_is_atomic_versioned_and_keeps_identity(client):
    base,_,_=tiny(client);p=client.get(base+'/catalog').json()['products'][0]
    body=payload(p,name='Edited complete kit',sku='KIT-RENAMED',bom=[{'component_code':'A','quantity':3},{'component_code':'B','quantity':1/720},{'component_code':'C','quantity':2}])
    r=client.put(base+'/products/'+str(p['id']),json=body);assert r.status_code==200,r.text
    after=client.get(base+'/catalog').json()['products'][0]
    assert after['id']==p['id'] and after['sku']=='KIT-RENAMED' and after['version']==2
    assert len(after['bom'])==3 and next(b for b in after['bom'] if b['code']=='B')['quantity']==1/720
    assert client.put(base+'/products/'+str(p['id']),json=body).status_code==409
    history=client.get(base+'/products/'+str(p['id'])+'/history').json();assert len(history)==2
    assert json.loads(history[-1]['snapshot'])['sku']=='KIT-01'

def test_invalid_bom_cannot_partially_rename_or_drop_existing_lines(client):
    base,_,_=tiny(client);p=client.get(base+'/catalog').json()['products'][0]
    r=client.put(base+'/products/'+str(p['id']),json=payload(p,sku='BAD-RENAME',bom=[{'component_code':'MISSING','quantity':1}]))
    assert r.status_code==422
    after=client.get(base+'/catalog').json()['products'][0]
    assert after['sku']=='KIT-01' and after['version']==1 and len(after['bom'])==2
    for lines in ([{'component_code':'A','quantity':1},{'component_code':'A','quantity':2}],[{'component_code':'A','quantity':'nan'}]):
        assert client.put(base+'/products/'+str(p['id']),json=payload(p,bom=lines)).status_code==422

def test_add_cannot_overwrite_an_existing_sku(client):
    base,_,_=tiny(client);p=client.get(base+'/catalog').json()['products'][0];body=payload(p);body.pop('version')
    assert client.post(base+'/products',json=body).status_code==409
    assert len(client.get(base+'/catalog').json()['products'][0]['bom'])==2

def test_product_archive_restore_keeps_bom_and_removes_demand(client):
    base,body,_=tiny(client);p=client.get(base+'/catalog').json()['products'][0]
    assert client.post(base+'/products/'+str(p['id'])+'/archive',json={'archived':True,'note':'Synthetic archive test.'}).status_code==200
    assert not client.get(base+'/catalog').json()['products']
    archived=client.get(base+'/catalog?include_archived=true').json()['products'][0]
    assert archived['archived'] and len(archived['bom'])==2
    assert not client.get(base+'/scenarios/'+body['scenario_ids'][0]).json()['evaluation']['affected_products']
    assert client.put(base+'/products/'+str(p['id']),json=payload(archived)).status_code==409
    assert client.post(base+'/products/'+str(p['id'])+'/archive',json={'archived':False,'note':'Synthetic restore test.'}).status_code==200
    assert len(client.get(base+'/catalog').json()['products'][0]['bom'])==2

def test_project_rename_archive_restore_and_no_background_work(client):
    base,_,_=tiny(client);pid=int(base.split('/')[-1])
    assert client.put(base,json={'name':'Renamed synthetic kit'}).status_code==200
    cid=client.post(base+'/connectors',json={'name':'Synthetic inbox','kind':'folder','enabled':True,'config':{'folder':'test'}}).json()['id']
    did=client.post(base+'/documents',files={'file':('pending.txt',b'SYNTHETIC pending source.')}).json()['id']
    assert client.post(base+'/archive',json={'archived':True,'note':'Synthetic project archive.'}).status_code==200
    assert not any(p['id']==pid for p in client.get('/api/projects').json())
    assert next(p for p in client.get('/api/projects?include_archived=true').json() if p['id']==pid)['archived']
    assert client.get(base+'/catalog').status_code==200
    assert client.post(base+'/products',json={'sku':'NO','name':'Blocked','annual_units':1,'plant':'A','formula':'F'}).status_code==409
    assert client.put(base,json={'name':'Cannot edit archived'}).status_code==409
    with db.connect() as c:
        assert not c.execute('SELECT enabled FROM connectors WHERE id=?',(cid,)).fetchone()['enabled']
        assert c.execute('SELECT status FROM documents WHERE id=?',(did,)).fetchone()['status']=='failed'
        assert not c.execute("SELECT 1 FROM jobs WHERE project_id=? AND status='queued'",(pid,)).fetchone()
    Worker().tick()
    assert client.post(base+'/archive',json={'archived':False,'note':'Synthetic project restore.'}).status_code==200
    with db.connect() as c:assert not c.execute('SELECT enabled FROM connectors WHERE id=?',(cid,)).fetchone()['enabled']
    assert client.get(base+'/audit').json()['chain_valid']

def test_project_archive_waits_for_running_job(client):
    base,_,_=tiny(client);pid=int(base.split('/')[-1])
    with db.connect(write=True) as c:c.execute("INSERT INTO jobs(id,project_id,kind,target,status,created) VALUES('running',?,'document','test','running',?)",(pid,time.time()))
    assert client.post(base+'/archive',json={'archived':True,'note':'Must wait for running job.'}).status_code==409
    assert not client.get(base+'/overview').json()['project']['archived']

def test_repeated_sample_open_and_explicit_creation_are_idempotent(client):
    first=client.post('/api/sample-project').json();second=client.post('/api/sample-project').json()
    assert first['id']==second['id'] and second['reused']
    body={'name':'Separate customer demo','create_new':True,'request_key':'request-20261106-00001'}
    created=client.post('/api/sample-project',json=body).json()
    assert client.post('/api/sample-project',json=body).json()['id']==created['id']
    assert len(client.get('/api/projects').json())==2
    assert client.post('/api/sample-project',json={**body,'request_key':'request-20261106-00002'}).status_code==409
    assert client.post('/api/sample-project',json={'name':'No key','create_new':True}).status_code==422

def test_project_names_and_cross_project_product_ids_are_protected(client):
    base,_,_=tiny(client);p=client.get(base+'/catalog').json()['products'][0]
    other=client.post('/api/projects',json={'name':'Other project'}).json()['id']
    assert client.post('/api/projects',json={'name':'  OTHER PROJECT '}).status_code==409
    assert client.put(base,json={'name':'Other project'}).status_code==409
    assert client.put(f'/api/projects/{other}/products/'+str(p['id']),json=payload(p)).status_code==404
    assert client.post(f'/api/projects/{other}/products/'+str(p['id'])+'/archive',json={'archived':True,'note':'Wrong project control.'}).status_code==404

def test_viewer_cannot_edit_or_archive_and_editor_cannot_manage_projects(client):
    base,_,_=tiny(client);pid=int(base.split('/')[-1]);p=client.get(base+'/catalog').json()['products'][0]
    uid=client.post('/api/users',json={'name':'Management viewer','email':'management@example.test','password':'Synthetic-management-123!'}).json()['id']
    client.post(base+'/members',json={'user_id':uid,'role':'viewer'})
    with TestClient(app,base_url='http://localhost:8015') as other:
        auth=other.post('/api/auth/login',json={'email':'management@example.test','password':'Synthetic-management-123!'}).json();other.headers['X-CSRF-Token']=auth['csrf']
        assert other.put(base+'/products/'+str(p['id']),json=payload(p)).status_code==403
        assert other.post(base+'/products/'+str(p['id'])+'/archive',json={'archived':True,'note':'Viewer cannot archive.'}).status_code==403
        client.post(base+'/members',json={'user_id':uid,'role':'editor'})
        assert other.put(base,json={'name':'Editor cannot rename project'}).status_code==403
        assert other.post(base+'/archive',json={'archived':True,'note':'Editor cannot archive project.'}).status_code==403
