import contextlib
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

ROOT = Path(os.getenv('AXIOM_DATA', str(Path(__file__).resolve().parents[1] / 'data'))).resolve()
DB = ROOT / 'axiompack.sqlite3'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied REAL NOT NULL);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, admin INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset REAL NOT NULL);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, name TEXT NOT NULL, synthetic INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS members(project_id INTEGER REFERENCES projects(id), user_id INTEGER REFERENCES users(id), role TEXT NOT NULL CHECK(role IN ('viewer','editor','reviewer')), PRIMARY KEY(project_id,user_id));
CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL, error TEXT, created REAL NOT NULL, created_by INTEGER REFERENCES users(id), reviewed_by INTEGER REFERENCES users(id), reviewed_at REAL, UNIQUE(project_id,sha256));
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, page INTEGER NOT NULL, text TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_search USING fts5(text, content='chunks', content_rowid='id', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN INSERT INTO chunk_search(rowid,text) VALUES(new.id,new.text); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN INSERT INTO chunk_search(chunk_search,rowid,text) VALUES('delete',old.id,old.text); END;
CREATE TABLE IF NOT EXISTS fields(id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, name TEXT NOT NULL, proposed TEXT NOT NULL, value TEXT NOT NULL, unit TEXT NOT NULL DEFAULT '', page INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'proposed', reviewed_by INTEGER REFERENCES users(id));
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, created REAL NOT NULL, started REAL, finished REAL);
CREATE TABLE IF NOT EXISTS components(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), code TEXT NOT NULL, name TEXT NOT NULL, supplier TEXT NOT NULL DEFAULT '', material TEXT NOT NULL, capacity_ml REAL NOT NULL, neck TEXT NOT NULL, weight_g REAL NOT NULL, price REAL NOT NULL, currency TEXT NOT NULL, revision TEXT NOT NULL, evidence_id TEXT NOT NULL REFERENCES documents(id), state TEXT NOT NULL CHECK(state IN ('approved','candidate')), version INTEGER NOT NULL DEFAULT 1, UNIQUE(project_id,code));
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), sku TEXT NOT NULL, name TEXT NOT NULL, annual_units INTEGER NOT NULL, plant TEXT NOT NULL, formula TEXT NOT NULL, UNIQUE(project_id,sku));
CREATE TABLE IF NOT EXISTS catalog_versions(id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), entity TEXT NOT NULL, entity_id INTEGER NOT NULL, snapshot TEXT NOT NULL, actor INTEGER REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS benefits(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), scenario_id TEXT NOT NULL REFERENCES scenarios(id), evidence_id TEXT NOT NULL REFERENCES documents(id), period_start TEXT NOT NULL, period_end TEXT NOT NULL, actual_units INTEGER NOT NULL, baseline_price REAL NOT NULL, actual_price REAL NOT NULL, actual_extra REAL NOT NULL, actual_transition REAL NOT NULL, note TEXT NOT NULL, recorded_by INTEGER NOT NULL REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bom(product_id INTEGER REFERENCES products(id) ON DELETE CASCADE, component_id INTEGER REFERENCES components(id), quantity REAL NOT NULL CHECK(quantity>0), PRIMARY KEY(product_id,component_id));
CREATE TABLE IF NOT EXISTS scenarios(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, baseline_id INTEGER NOT NULL REFERENCES components(id), candidate_id INTEGER NOT NULL REFERENCES components(id), inputs TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'draft', qualifications TEXT NOT NULL DEFAULT '{}', approved_by INTEGER REFERENCES users(id), approved_at REAL, approved_fingerprint TEXT, implementation TEXT, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS approval_snapshots(id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenarios(id), version INTEGER NOT NULL, snapshot TEXT NOT NULL, approved_by INTEGER NOT NULL REFERENCES users(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS programmes(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, description TEXT NOT NULL, scenario_ids TEXT NOT NULL, shared_transition_cost REAL NOT NULL, cost_note TEXT NOT NULL, evidence_id TEXT NOT NULL REFERENCES documents(id), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sample_requests(user_id INTEGER NOT NULL REFERENCES users(id),request_key TEXT NOT NULL,project_id INTEGER NOT NULL REFERENCES projects(id),PRIMARY KEY(user_id,request_key));
CREATE TABLE IF NOT EXISTS connectors(id TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('folder','http_json','webhook')), config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0, interval_seconds INTEGER NOT NULL DEFAULT 300, next_run REAL NOT NULL DEFAULT 0, last_success REAL, last_error TEXT, failures INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS connector_runs(id TEXT PRIMARY KEY, connector_id TEXT NOT NULL REFERENCES connectors(id), status TEXT NOT NULL, counts TEXT NOT NULL DEFAULT '{}', error TEXT, started REAL NOT NULL, finished REAL);
CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY, connector_id TEXT NOT NULL REFERENCES connectors(id), scenario_id TEXT NOT NULL REFERENCES scenarios(id), payload TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT, remote_status INTEGER, created REAL NOT NULL, finished REAL, UNIQUE(connector_id,scenario_id,payload));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, project_id INTEGER REFERENCES projects(id), actor INTEGER REFERENCES users(id), action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL, created REAL NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS documents_project ON documents(project_id,status);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
CREATE INDEX IF NOT EXISTS audit_project ON audit(project_id,id);
'''

@contextlib.contextmanager
def connect(write=False):
    conn = sqlite3.connect(DB, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    if write:
        conn.execute('BEGIN IMMEDIATE')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def initialize():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('uploads','inbox','backups','logs'):
        (ROOT/name).mkdir(exist_ok=True, mode=0o700)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript(SCHEMA)
        columns={r['name'] for r in c.execute('PRAGMA table_info(components)')}
        for column in ('price_valid_from','price_valid_until'):
            if column not in columns:
                c.execute('ALTER TABLE components ADD COLUMN '+column+" TEXT NOT NULL DEFAULT ''")
        for column,default in [('component_type','bottle'),('uom','piece'),('attributes','{}')]:
            if column not in columns:
                c.execute('ALTER TABLE components ADD COLUMN '+column+" TEXT NOT NULL DEFAULT '"+default+"'")
        c.execute('INSERT OR IGNORE INTO schema_versions VALUES(1,?)', (time.time(),))
        c.execute('INSERT OR IGNORE INTO schema_versions VALUES(2,?)', (time.time(),))
        c.execute('INSERT OR IGNORE INTO schema_versions VALUES(3,?)', (time.time(),))
        for table,fields in [('projects',{'archived':'INTEGER NOT NULL DEFAULT 0','sample_template':"TEXT NOT NULL DEFAULT ''"}),('products',{'archived':'INTEGER NOT NULL DEFAULT 0','version':'INTEGER NOT NULL DEFAULT 1'})]:
            present={r['name'] for r in c.execute('PRAGMA table_info('+table+')')}
            for name,kind in fields.items():
                if name not in present:c.execute('ALTER TABLE '+table+' ADD COLUMN '+name+' '+kind)
        c.execute("UPDATE projects SET sample_template='clearcare' WHERE synthetic=1 AND name='ClearCare • synthetic case study' AND sample_template=''")
        c.execute('INSERT OR IGNORE INTO schema_versions VALUES(4,?)',(time.time(),))
        c.execute("UPDATE jobs SET status='queued', error='Recovered after process restart' WHERE status='running'")
        c.execute("UPDATE connector_runs SET status='interrupted',error='Service restarted',finished=? WHERE status='running'", (time.time(),))
        c.execute("UPDATE deliveries SET status='retry',error='Service restarted; same idempotency key retained' WHERE status='sending'")
    os.chmod(DB, 0o600)

def audit(c, project, actor, action, target='', detail=None):
    # Hash chain detects accidental modification, not a substitute for external immutable logs.
    previous = c.execute('SELECT hash FROM audit ORDER BY id DESC LIMIT 1').fetchone()
    prev = previous['hash'] if previous else '0'*64
    stamp = time.time()
    body = json.dumps(detail or {}, sort_keys=True, separators=(',',':'))
    raw = json.dumps([project,actor,action,str(target),body,stamp,prev], separators=(',',':'))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    c.execute('INSERT INTO audit(project_id,actor,action,target,detail,created,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?)', (project,actor,action,str(target),body,stamp,prev,digest))

def verify_audit(c):
    prev = '0'*64
    for r in c.execute('SELECT * FROM audit ORDER BY id'):
        raw = json.dumps([r['project_id'],r['actor'],r['action'],r['target'],r['detail'],r['created'],r['prev_hash']],separators=(',',':'))
        if r['prev_hash'] != prev or hashlib.sha256(raw.encode()).hexdigest() != r['hash']:
            return False
        prev = r['hash']
    return True
