import json
import logging
import subprocess
import sys
import threading
import time
from .db import connect, audit
from .documents import process_document
from .connectors import run_connector, send_delivery

log=logging.getLogger('axiom.worker')

class Worker:
    def __init__(self): self.stop=threading.Event(); self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.loop,name='axiom-jobs',daemon=True)
        self.thread.start()
    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=5)
    def tick(self):
        with connect(write=True) as c:
            job=c.execute("SELECT j.* FROM jobs j JOIN projects p ON p.id=j.project_id WHERE j.status='queued' AND p.archived=0 ORDER BY j.created LIMIT 1").fetchone()
            if job:
                job=dict(job)
                c.execute("UPDATE jobs SET status='running',attempts=attempts+1,started=? WHERE id=?",(time.time(),job['id']))
        if job:
            try:
                if job['kind']=='document':
                    # Isolate parsers/OCR with memory/CPU and wall-clock limits.
                    result=subprocess.run([sys.executable,'-m','backend.worker','document',job['target']],capture_output=True,text=True,timeout=360)
                    if result.returncode: raise ValueError(result.stdout.strip()[:400] or 'Document processing failed')
                elif job['kind']=='connector': run_connector(job['target'])
                elif job['kind']=='delivery': send_delivery(job['target'])
                with connect(write=True) as c: c.execute("UPDATE jobs SET status='succeeded',finished=? WHERE id=?",(time.time(),job['id']))
            except Exception as ex:
                msg=str(ex)[:400] if isinstance(ex,(ValueError,subprocess.TimeoutExpired)) else type(ex).__name__+': processing failed'
                with connect(write=True) as c:
                    c.execute("UPDATE jobs SET status='failed',error=?,finished=? WHERE id=?",(msg,time.time(),job['id']))
                    if job['kind']=='document': c.execute("UPDATE documents SET status='failed',error=? WHERE id=?",(msg,job['target']))
                    audit(c,job['project_id'],None,'job.failed',job['id'],{'error':msg})
            return
        with connect(write=True) as c:
            now=time.time()
            con=c.execute("SELECT id FROM connectors WHERE enabled=1 AND kind!='webhook' AND next_run<=? AND project_id IN (SELECT id FROM projects WHERE archived=0) AND id NOT IN (SELECT target FROM jobs WHERE status IN ('queued','running')) ORDER BY next_run LIMIT 1",(now,)).fetchone()
            if con:
                import uuid
                pid=c.execute('SELECT project_id FROM connectors WHERE id=?',(con['id'],)).fetchone()['project_id']
                c.execute('INSERT INTO jobs(id,project_id,kind,target,status,created) VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,pid,'connector',con['id'],'queued',now))
            delivery=c.execute("SELECT d.* FROM deliveries d JOIN connectors con ON con.id=d.connector_id JOIN projects p ON p.id=con.project_id WHERE d.status='retry' AND p.archived=0 AND con.enabled=1 AND d.attempts<3 AND COALESCE(d.finished,0)<? AND d.id NOT IN (SELECT target FROM jobs WHERE status IN ('queued','running')) LIMIT 1",(now-60,)).fetchone()
            if delivery:
                import uuid
                pid=c.execute('SELECT project_id FROM connectors WHERE id=?',(delivery['connector_id'],)).fetchone()['project_id']
                c.execute('INSERT INTO jobs(id,project_id,kind,target,status,created) VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,pid,'delivery',delivery['id'],'queued',now))
    def loop(self):
        while not self.stop.is_set():
            try: self.tick()
            except Exception: log.exception('Worker cycle failed')
            self.stop.wait(1)

if __name__=='__main__':
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
    resource.setrlimit(resource.RLIMIT_CPU,(300,300))
    try: process_document(sys.argv[2])
    except Exception as ex:
        print(str(ex)[:400] if isinstance(ex,ValueError) else type(ex).__name__+': unable to extract document')
        sys.exit(1)
