import json
import sqlite3
import pytest
from backend import db

def test_backup_verify_restore_and_corruption_guard(client,sample,tmp_path,monkeypatch):
    from ops import backup
    monkeypatch.setattr(backup,'ROOT',db.ROOT);monkeypatch.setattr(backup,'DB',db.DB)
    destination=backup.backup(tmp_path/'backups')
    assert backup.verify(destination)['documents']==8
    restored=tmp_path/'restored'
    assert backup.restore(destination,restored)['sessions_revoked']
    with sqlite3.connect(restored/'axiompack.sqlite3') as c:
        assert c.execute('SELECT count(*) FROM products').fetchone()[0]==20
        assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
    with pytest.raises(RuntimeError,match='empty'):backup.restore(destination,restored)
    from pathlib import Path
    manifest=Path(destination)/'manifest.json';m=json.loads(manifest.read_text());m['database_sha256']='bad';manifest.write_text(json.dumps(m))
    with pytest.raises(RuntimeError,match='hash'):backup.verify(destination)

def test_worker_restart_requeues_interrupted_jobs(client,sample):
    with db.connect(write=True) as c:
        jid=c.execute('SELECT id FROM jobs LIMIT 1').fetchone()['id']
        c.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
    db.initialize()
    with db.connect() as c:assert c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()['status']=='queued'

def test_source_record_persists_across_connections(client,sample):
    with db.connect() as c: first=c.execute('SELECT sha256 FROM documents WHERE project_id=? ORDER BY id',(sample['pid'],)).fetchall()
    db.initialize()
    with db.connect() as c: second=c.execute('SELECT sha256 FROM documents WHERE project_id=? ORDER BY id',(sample['pid'],)).fetchall()
    assert [r['sha256'] for r in first]==[r['sha256'] for r in second]
