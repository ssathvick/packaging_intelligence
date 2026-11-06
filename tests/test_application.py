import io
import json
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend import db,main
from backend.documents import process_document,extract
from conftest import qualify,approve

def test_bootstrap_auth_csrf_origin_and_headers(client):
    assert client.get('/api/health').json()['setup_required'] is False
    assert client.post('/api/auth/setup',json={'name':'Again','email':'x@y.test','password':'Test-password-123!','token':'x'*32}).status_code==409
    saved=client.headers.pop('X-CSRF-Token')
    assert client.post('/api/projects',json={'name':'Blocked'}).status_code==403
    client.headers['X-CSRF-Token']=saved
    assert client.post('/api/projects',headers={'Origin':'https://evil.example'},json={'name':'Blocked'}).status_code==403
    response=client.get('/')
    assert response.status_code==200
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert response.headers['x-content-type-options']=='nosniff'
    assert client.post('/api/auth/login',json={'email':'owner@example.test','password':'wrong'}).status_code==401

def test_login_rate_limit(client):
    for _ in range(8): assert client.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'missing@example.test','password':'wrong'}).status_code==429

def test_upload_validation_dedup_and_review(client):
    pid=client.post('/api/projects',json={'name':'Document test'}).json()['id'];base=f'/api/projects/{pid}'
    assert client.post(base+'/documents',files={'file':('x.exe',b'executable')}).status_code==422
    assert client.post(base+'/documents',files={'file':('x.pdf',b'invalid')}).status_code==422
    assert client.post(base+'/documents',files={'file':('x.txt',b'x'*(20*1024*1024+1))}).status_code==413
    source=b'Component code: BOT-11\nRevision: R1\nWeight: 18 g\nMaterial: PET\nCapacity: 250 ml\nNeck finish: N24-A\n'
    did=client.post(base+'/documents',files={'file':('spec.txt',source)}).json()['id']
    dup=client.post(base+'/documents',files={'file':('copy.txt',source)}).json()
    assert dup=={'id':did,'duplicate':True}
    process_document(did)
    d=client.get(base+'/documents/'+did).json()
    assert any(f['name']=='weight_g' and f['value']=='18' for f in d['fields'])
    weight=next(f for f in d['fields'] if f['name']=='weight_g')
    assert client.get(base+'/search?q=BOT-11').json()==[]
    assert client.post(base+'/documents/'+did+'/review',json={'fields':{str(weight['id']):'17.8'},'note':'Corrected against physical source specification.'}).status_code==200
    d=client.get(base+'/documents/'+did).json()
    assert next(f for f in d['fields'] if f['id']==weight['id'])['proposed']=='18'
    assert next(f for f in d['fields'] if f['id']==weight['id'])['value']=='17.8'
    assert client.get(base+'/documents/'+did+'/file').content==source
    found=client.get(base+'/search?q=BOT-11').json();assert found and found[0]['document_id']==did

def test_catalog_bom_and_complete_controlled_cycle(client,scenario):
    pid,sid=scenario['pid'],scenario['sid'];url=f'/api/projects/{pid}/scenarios/{sid}'
    assert len(scenario['catalog']['products'])==20
    e=client.get(url).json()['evaluation']
    assert e['eligible'] and e['annual_component_demand']==8000000
    assert len(e['affected_products'])==3
    assert e['financials']['gross_annual']==2400000
    assert e['financials']['first_year_net']==1840000
    assert e['financials']['material_tonnes']==16
    assert client.post(url+'/approve',json={'note':'Trying without qualification.'}).status_code==409
    approve(client,scenario)
    assert client.get(url).json()['evaluation']['approval_current']
    assert client.post(url+'/request-change',json={'note':'Proceed with synthetic controlled change.'}).status_code==200
    assert client.post(url+'/implement',json={'evidence_id':scenario['docs']['07-synthetic-implementation-receipt.txt'],'reference':'CC-2026-001','note':'Fictional implementation receipt reviewed.'}).status_code==200
    r=client.post(url+'/benefits',json={'evidence_id':scenario['docs']['08-synthetic-actual-benefit-evidence.txt'],
        'period_start':'2026-11-01','period_end':'2026-11-04','actual_units':10000,'baseline_price':5.2,'actual_price':4.9,'actual_extra':200,'actual_transition':0,'note':'Synthetic actuals for workflow validation only.'})
    assert r.status_code==200,r.text
    assert client.get(url+'/benefits').json()[0]['realised_net']==2800
    assert client.post(url+'/benefits',json={'evidence_id':scenario['docs']['08-synthetic-actual-benefit-evidence.txt'],
        'period_start':'2026-11-02','period_end':'2026-11-03','actual_units':1,'baseline_price':5.2,'actual_price':4.9,'actual_extra':0,'actual_transition':0,'note':'Overlapping period must fail.'}).status_code==409
    pack=client.get(url+'/export').json()
    assert pack['audit_chain_valid'] and pack['scenario']['status']=='implemented' and len(pack['benefits'])==1
    assert client.get(f'/api/projects/{pid}/audit').json()['chain_valid']

def test_component_revision_invalidates_approval_and_preserves_history(client,scenario):
    approve(client,scenario)
    comp=scenario['components']['BOT-209'].copy()
    for key in ('id','project_id','version'):comp.pop(key)
    comp.update(price=5.0,revision='C3')
    r=client.post(f'/api/projects/{scenario["pid"]}/components',json=comp);assert r.status_code==200,r.text
    s=client.get(f'/api/projects/{scenario["pid"]}/scenarios/{scenario["sid"]}').json()
    assert s['status']=='draft' and not s['evaluation']['approval_current'] and not s['evaluation']['qualification_complete']
    assert s['evaluation']['financials']['first_year_net']==1040000
    hist=client.get(f'/api/projects/{scenario["pid"]}/components/{scenario["components"]["BOT-209"]["id"]}/history').json()
    assert len(hist)==2 and json.loads(hist[-1]['snapshot'])['price']==4.9

def test_scenario_revision_and_source_reopen_invalidate(client,scenario):
    approve(client,scenario);pid,sid=scenario['pid'],scenario['sid'];url=f'/api/projects/{pid}/scenarios/{sid}'
    body={**scenario['inputs'],'extra_per_unit':.05}
    assert client.put(url,json=body).status_code==200
    assert client.get(url).json()['qualifications']=='{}'
    approve(client,scenario)
    did=scenario['docs']['06-synthetic-trial-evidence.txt']
    assert client.post(f'/api/projects/{pid}/documents/{did}/reopen',json={'note':'Recheck qualification source evidence.'}).status_code==200
    assert not client.get(url).json()['evaluation']['approval_current']

def test_incompatible_and_expired_candidates_block(client,scenario):
    pid=scenario['pid'];body={**scenario['inputs'],'candidate_id':scenario['components']['BOT-331']['id']}
    sid=client.post(f'/api/projects/{pid}/scenarios',json=body).json()['id']
    e=client.get(f'/api/projects/{pid}/scenarios/{sid}').json()['evaluation']
    assert not e['eligible'] and any(c['attribute']=='neck' and not c['passed'] for c in e['checks'])
    with db.connect(write=True) as c:c.execute("UPDATE components SET price_valid_until='2026-01-01' WHERE id=?",(scenario['components']['BOT-209']['id'],))
    e=client.get(f'/api/projects/{pid}/scenarios/{scenario["sid"]}').json()['evaluation']
    assert not e['eligible']

def test_catalog_import_is_atomic(client,sample):
    from backend.connectors import import_records
    pid=sample['pid'];component=sample['components']['BOT-104'].copy()
    for key in ('id','project_id','version'):component.pop(key)
    bad={**component,'code':'NEW-BAD','weight_g':-4}
    with pytest.raises(Exception):
        with db.connect(write=True) as c:import_records(c,pid,'components',[{**component,'price':99},bad])
    with db.connect() as c:assert c.execute('SELECT price FROM components WHERE id=?',(sample['components']['BOT-104']['id'],)).fetchone()['price']==5.2

def test_rbac_project_isolation_and_session_revocation(client,sample):
    r=client.post('/api/users',json={'name':'QA Viewer','email':'viewer@example.test','password':'Viewer-password-123!'})
    assert r.status_code==200;uid=r.json()['id'];pid=sample['pid']
    client.post(f'/api/projects/{pid}/members',json={'user_id':uid,'role':'viewer'})
    with TestClient(main.app,base_url='http://localhost:8015') as other:
        auth=other.post('/api/auth/login',json={'email':'viewer@example.test','password':'Viewer-password-123!'}).json()
        other.headers['X-CSRF-Token']=auth['csrf']
        assert other.get(f'/api/projects/{pid}/catalog').status_code==200
        assert other.post(f'/api/projects/{pid}/documents',files={'file':('test.txt',b'Some source')}).status_code==403
        assert other.post(f'/api/projects/{pid}/catalog/import',json={'document_id':sample['docs']['01-components.csv'],'record_type':'components'}).status_code==403
        secret=client.post('/api/projects',json={'name':'Other private customer'}).json()['id']
        assert other.get(f'/api/projects/{secret}/catalog').status_code==404
        assert other.get(f'/api/projects/{secret}/documents/'+sample['docs']['01-components.csv']).status_code==404
        assert other.get('/api/system').status_code==403
        assert client.post(f'/api/users/{uid}/disable').status_code==200
        assert other.get('/api/auth/me').status_code==401

def test_editor_cannot_approve_evidence(client,sample):
    uid=client.post('/api/users',json={'name':'QA Editor','email':'editor@example.test','password':'Editor-password-123!'}).json()['id'];pid=sample['pid']
    client.post(f'/api/projects/{pid}/members',json={'user_id':uid,'role':'editor'})
    other=TestClient(main.app,base_url='http://localhost:8015')
    auth=other.post('/api/auth/login',json={'email':'editor@example.test','password':'Editor-password-123!'}).json();other.headers['X-CSRF-Token']=auth['csrf']
    assert other.post(f'/api/projects/{pid}/documents/{sample["docs"]["01-components.csv"]}/review',json={'note':'Editor attempting approval.','fields':{}}).status_code==403
    assert other.post(f'/api/projects/{pid}/documents',files={'file':('editor.txt',b'Editor source evidence text')}).status_code==200

def test_structured_document_extractors_and_scanned_pdf(tmp_path):
    from docx import Document
    from openpyxl import Workbook
    from pdf_fixture import text_pdf,scanned_pdf
    path=tmp_path/'test.docx';doc=Document();doc.add_paragraph('Component code: DOCX-01');doc.save(path)
    assert 'DOCX-01' in extract(path)[0][1]
    path=tmp_path/'test.xlsx';book=Workbook();book.active.append(['Component code','XLSX-01']);book.save(path)
    assert 'XLSX-01' in extract(path)[0][1]
    path=tmp_path/'text.pdf';text_pdf(path,'Packaging specification: Component code TEXT-01, Weight 18 grams.')
    assert 'TEXT-01' in extract(path)[0][1]
    path=tmp_path/'scan.pdf';scanned_pdf(path)
    text=extract(path)[0][1];assert 'SCAN-104' in text and '18' in text

def test_macro_and_expanded_office_rejected(client):
    pid=client.post('/api/projects',json={'name':'Bad Office'}).json()['id']
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:z.writestr('word/vbaProject.bin',b'macro')
    assert client.post(f'/api/projects/{pid}/documents',files={'file':('macro.docx',data.getvalue())}).status_code==422

def test_audit_tamper_detection(client,sample):
    with db.connect(write=True) as c:c.execute("UPDATE audit SET action='tampered' WHERE id=(SELECT min(id) FROM audit)")
    assert not client.get(f'/api/projects/{sample["pid"]}/audit').json()['chain_valid']

def test_password_change_revokes_sessions(client):
    assert client.post('/api/auth/password',json={'current_password':'wrong','new_password':'A-new-password-123!'}).status_code==403
    assert client.post('/api/auth/password',json={'current_password':'Test-password-123!','new_password':'A-new-password-123!'}).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert client.post('/api/auth/login',json={'email':'owner@example.test','password':'A-new-password-123!'}).status_code==200

def test_new_implementation_receipt_does_not_revoke_an_unrelated_approval(client,scenario):
    approve(client,scenario);pid,sid=scenario['pid'],scenario['sid'];base=f'/api/projects/{pid}'
    did=client.post(base+'/documents',files={'file':('new-receipt.txt',b'Implementation receipt for the approved change, reviewed after approval.')} ).json()['id']
    process_document(did)
    r=client.post(base+'/documents/'+did+'/review',json={'note':'Reviewed new implementation receipt.','fields':{}})
    assert r.status_code==200
    assert client.get(base+'/scenarios/'+sid).json()['evaluation']['approval_current']

def test_implemented_financial_snapshot_survives_later_catalog_changes(client,scenario):
    approve(client,scenario);pid,sid=scenario['pid'],scenario['sid'];url=f'/api/projects/{pid}/scenarios/{sid}'
    client.post(url+'/request-change',json={'note':'Synthetic controlled change request.'})
    client.post(url+'/implement',json={'evidence_id':scenario['docs']['07-synthetic-implementation-receipt.txt'],'reference':'TEST-1','note':'Synthetic implementation acknowledged.'})
    with db.connect(write=True) as c:c.execute('UPDATE components SET price=10 WHERE id=?',(scenario['components']['BOT-209']['id'],))
    s=client.get(url).json()
    assert s['approved_evaluation']['financials']['first_year_net']==1840000
    assert s['evaluation']['financials']['first_year_net']!=1840000
    assert client.get(f'/api/projects/{pid}/scenarios').json()[0]['evaluation']['financials']['first_year_net']==1840000

def test_opportunity_discovery_uses_bom_and_excludes_neck_mismatch(client,sample):
    found=client.get(f'/api/projects/{sample["pid"]}/opportunities').json()
    assert len(found)==1
    row=found[0]
    assert row['baseline_code']=='BOT-104' and row['candidate_code']=='BOT-209'
    assert row['affected_skus']==3 and row['gross_annual_potential']==2400000 and row['status']=='unqualified'
