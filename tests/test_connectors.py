import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from backend import db,connectors
from backend.connectors import run_connector,send_delivery,resolve_url
from conftest import approve

@pytest.fixture
def remote(monkeypatch):
    state={'records':[],'posts':[],'status':200}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data=json.dumps({'records':state['records']}).encode()
            self.send_response(state['status']);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            body=self.rfile.read(int(self.headers['Content-Length']))
            state['posts'].append({'key':self.headers.get('Idempotency-Key'),'body':json.loads(body)})
            self.send_response(202);self.end_headers();self.wfile.write(b'{"accepted":true}')
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('AXIOM_TEST_HTTP','1');monkeypatch.setenv('AXIOM_CONNECTOR_HOSTS','127.0.0.1')
    yield state,f'http://127.0.0.1:{server.server_port}/api'
    server.shutdown();server.server_close();thread.join()

def test_folder_connector_deduplicates_and_tracks_runs(client,sample):
    pid=sample['pid'];base=f'/api/projects/{pid}/connectors'
    cid=client.post(base,json={'name':'Supplier inbox','kind':'folder','config':{'folder':'supplier-a'}}).json()['id']
    folder=db.ROOT/'inbox'/str(pid)/'supplier-a';(folder/'new.txt').write_text('Component code: FOLDER-01\nWeight: 18 g\n')
    run_connector(cid);run_connector(cid)
    data=client.get(base).json()[0]
    assert len(data['runs'])==2 and all(r['status']=='succeeded' for r in data['runs'])
    with db.connect() as c:assert c.execute("SELECT count(*) n FROM documents WHERE project_id=? AND name='new.txt'",(pid,)).fetchone()['n']==1
    assert client.post(base,json={'name':'Traversal','kind':'folder','config':{'folder':'../../other'}}).status_code==422

def test_http_import_mapping_failure_rollback_and_retry(client,sample,remote):
    state,url=remote;pid=sample['pid']
    record=sample['components']['BOT-104'].copy()
    for key in ('id','project_id','version'):record.pop(key)
    record['price']=5.1;state['records']=[record]
    body={'name':'Customer JSON source','kind':'http_json','enabled':True,'config':{'url':url,'record_type':'components','records_path':'records','mapping':{}}}
    r=client.post(f'/api/projects/{pid}/connectors',json=body);assert r.status_code==200,r.text
    cid=r.json()['id'];run_connector(cid)
    # Remote records are staged for source review, never silently promoted to the controlled catalog.
    with db.connect() as c:assert c.execute('SELECT price FROM components WHERE id=?',(sample['components']['BOT-104']['id'],)).fetchone()['price']==5.2
    con=client.get(f'/api/projects/{pid}/connectors').json()[0]
    did=json.loads(con['runs'][0]['counts'])['document_id']
    from backend.documents import process_document
    process_document(did)
    assert client.post(f'/api/projects/{pid}/documents/{did}/review',json={'note':'Reviewed staged connector records.','fields':{}}).status_code==200
    assert client.post(f'/api/projects/{pid}/catalog/import',json={'document_id':did,'record_type':'components'}).status_code==200
    with db.connect() as c:assert c.execute('SELECT price FROM components WHERE id=?',(sample['components']['BOT-104']['id'],)).fetchone()['price']==5.1
    state['records']=[{**record,'price':99},{**record,'code':'BAD','weight_g':-1}]
    with pytest.raises(ValueError):run_connector(cid)
    with db.connect() as c:assert c.execute('SELECT price FROM components WHERE id=?',(sample['components']['BOT-104']['id'],)).fetchone()['price']==5.1
    cons=client.get(f'/api/projects/{pid}/connectors').json()[0]
    assert cons['failures']==1 and cons['last_error'] and cons['next_run']>cons['last_success']
    state['records']=[record];run_connector(cid)
    assert client.get(f'/api/projects/{pid}/connectors').json()[0]['failures']==0
    state['status']=302
    with pytest.raises(ValueError,match='redirects'):run_connector(cid)

def test_outbound_delivery_idempotency_and_stale_approval_guard(client,scenario,remote):
    state,url=remote;pid,sid=scenario['pid'],scenario['sid'];base=f'/api/projects/{pid}'
    cid=client.post(base+'/connectors',json={'name':'Customer change API','kind':'webhook','enabled':True,'config':{'url':url}}).json()['id']
    assert client.post(base+f'/scenarios/{sid}/deliver',json={'connector_id':cid}).status_code==409
    approve(client,scenario)
    assert client.post(base+f'/scenarios/{sid}/request-change',json={'note':'Approved synthetic integration test.'}).status_code==200
    r=client.post(base+f'/scenarios/{sid}/deliver',json={'connector_id':cid});assert r.status_code==200,r.text
    did=r.json()['id'];send_delivery(did)
    assert len(state['posts'])==1 and state['posts'][0]['key']==did
    assert state['posts'][0]['body']['schema']=='axiompack.change.v1'
    assert client.post(base+f'/scenarios/{sid}/deliver',json={'connector_id':cid}).json()['duplicate']
    assert client.get(base+f'/scenarios/{sid}').json()['status']=='change_requested'
    # A queued delivery cannot bypass a subsequently reopened qualification source.
    with db.connect(write=True) as c:c.execute("UPDATE deliveries SET status='queued' WHERE id=?",(did,))
    client.post(base+'/documents/'+scenario['docs']['06-synthetic-trial-evidence.txt']+'/reopen',json={'note':'Revalidate test source after approval.'})
    send_delivery(did)
    assert len(state['posts'])==1

def test_ssrf_blocking(monkeypatch):
    monkeypatch.setenv('AXIOM_TEST_HTTP','0');monkeypatch.setenv('AXIOM_CONNECTOR_HOSTS','127.0.0.1')
    with pytest.raises(ValueError,match='blocked'):resolve_url('https://127.0.0.1/private')
    with pytest.raises(ValueError,match='allowlist'):resolve_url('https://not-allowed.example/api')
    with pytest.raises(ValueError):resolve_url('https://user:password@127.0.0.1/')
