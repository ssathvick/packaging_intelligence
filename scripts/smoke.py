"""Isolated real HTTP/worker smoke check; never reads the deployment .env."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='packaging-smoke-') as temporary:
        data = Path(temporary) / 'data'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {**os.environ, 'AXIOM_DATA': str(data), 'AXIOM_WORKER': '1',
               'AXIOM_TEST_HTTP': '0', 'AXIOM_SECURE_COOKIES': '0',
               'AXIOM_PUBLIC_URL': '', 'AXIOM_ALLOWED_HOSTS': '127.0.0.1,localhost',
               'AXIOM_ORIGINS': f'http://127.0.0.1:{port}', 'AXIOM_CONNECTOR_HOSTS': ''}
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                [sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
                 '--port', str(port), '--workers', '1', '--no-access-log'],
                cwd=root, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=10) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError('Isolated app failed to start')
                        try:
                            health = client.get('/api/health')
                            if health.is_success:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.2)
                    else:
                        raise RuntimeError('Isolated app startup timed out')
                    assert health.json()['worker']
                    assert client.get('/api/projects').status_code == 401
                    assert client.get('/').status_code == 200
                    assert client.get('/assets/app.js').status_code == 200
                    setup = client.post('/api/auth/setup', json={
                        'name': 'Synthetic Smoke Operator', 'email': 'smoke@example.test',
                        'password': secrets.token_urlsafe(24),
                        'token': (data / 'setup-token').read_text()})
                    setup.raise_for_status()
                    client.headers['X-CSRF-Token'] = setup.json()['csrf']
                    project = client.post('/api/projects', json={'name': 'Synthetic smoke', 'synthetic': True})
                    project.raise_for_status()
                    base = f'/api/projects/{project.json()["id"]}/documents'
                    uploaded = client.post(base, files={'file': ('synthetic.txt', b'SYNTHETIC\nComponent code: DEMO-1\nWeight: 18 g\n')})
                    uploaded.raise_for_status()
                    url = base + '/' + uploaded.json()['id']
                    for _ in range(100):
                        document = client.get(url).json()
                        if document['status'] == 'review':
                            break
                        if document['status'] == 'failed':
                            raise RuntimeError('Real document worker failed')
                        time.sleep(0.2)
                    else:
                        raise RuntimeError('Document worker timed out')
                    assert any(field['name'] == 'weight_g' for field in document['fields'])
                    reviewed = client.post(url + '/review', json={'fields': {}, 'note': 'Verified generated synthetic source in isolated smoke.'})
                    reviewed.raise_for_status()
                    backup = subprocess.run([sys.executable, 'ops/backup.py', 'create',
                                             str(Path(temporary) / 'backups')],
                                            cwd=root, env=env, check=True, capture_output=True, text=True)
                    result = json.loads(backup.stdout)
                    assert result['verified'] and result['documents'] == 1
                    restored = subprocess.run([sys.executable, 'ops/backup.py', 'restore', result['path'],
                                               '--target', str(Path(temporary) / 'restored')],
                                              cwd=root, env=env, check=True, capture_output=True, text=True)
                    assert json.loads(restored.stdout)['sessions_revoked']
                    print(json.dumps({'status': 'passed', 'version': health.json()['version'],
                                      'checks': ['HTTP startup', 'protected API', 'static UI', 'owner setup',
                                                 'real document subprocess', 'source review', 'backup verification',
                                                 'isolated restore with session revocation']}))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
