import os
os.environ['AXIOM_WORKER']='0'
os.environ['AXIOM_TEST_HTTP']='0'
import pytest
from fastapi.testclient import TestClient
from backend import db,documents,connectors,main

@pytest.fixture
def client(tmp_path,monkeypatch):
    root=tmp_path/'data'
    monkeypatch.setattr(db,'ROOT',root);monkeypatch.setattr(db,'DB',root/'axiompack.sqlite3')
    for mod in (documents,connectors,main): monkeypatch.setattr(mod,'ROOT',root)
    with TestClient(main.app,base_url='http://localhost:8015') as c:
        token=(root/'setup-token').read_text()
        r=c.post('/api/auth/setup',json={'email':'owner@example.test','name':'QA Owner','password':'Test-password-123!','token':token})
        assert r.status_code==200,r.text
        c.headers['X-CSRF-Token']=r.json()['csrf']
        yield c

@pytest.fixture
def sample(client):
    from backend.documents import process_document
    r=client.post('/api/sample-project');assert r.status_code==200,r.text
    data=r.json();pid=data['id']
    docs={}
    for doc in data['documents']:
        process_document(doc['id'])
        r=client.post(f'/api/projects/{pid}/documents/{doc["id"]}/review',json={'fields':{},'note':'Reviewed synthetic fixture against original file.'})
        assert r.status_code==200,r.text
        docs[doc['name']]=doc['id']
    for name,kind in [('01-components.csv','components'),('02-products.csv','products')]:
        r=client.post(f'/api/projects/{pid}/catalog/import',json={'document_id':docs[name],'record_type':kind,'mapping':{}})
        assert r.status_code==200,r.text
    cat=client.get(f'/api/projects/{pid}/catalog').json()
    return {'pid':pid,'docs':docs,'components':{x['code']:x for x in cat['components']},'catalog':cat}

@pytest.fixture
def scenario(client,sample):
    pid=sample['pid']
    body={'name':'Lightweight bottle scope','baseline_id':sample['components']['BOT-104']['id'],
        'candidate_id':sample['components']['BOT-209']['id'],'annual_units':8000000,'extra_per_unit':.02,'transition_cost':400000,
        'assumption_note':'Synthetic forecast: SH-250-001/002/003, Plant A, Formula Alpha; current generated quote window, tax excluded, same delivery basis.'}
    r=client.post(f'/api/projects/{pid}/scenarios',json=body);assert r.status_code==200,r.text
    return {**sample,'sid':r.json()['id'],'inputs':body}

def qualify(client,scenario):
    for key in ('fit_seal','line_trial','formula_compatibility'):
        r=client.post(f'/api/projects/{scenario["pid"]}/scenarios/{scenario["sid"]}/qualifications',json={
            'key':key,'passed':True,'evidence_id':scenario['docs']['06-synthetic-trial-evidence.txt'],
            'note':'Synthetic fixture reviewed for BOT-104 R6 to BOT-209 C2 at Plant A, Formula Alpha, SKUs 001/002/003.'})
        assert r.status_code==200,r.text

def approve(client,scenario):
    qualify(client,scenario)
    r=client.post(f'/api/projects/{scenario["pid"]}/scenarios/{scenario["sid"]}/approve',json={'note':'Synthetic evidence and exact scope reviewed.'})
    assert r.status_code==200,r.text
