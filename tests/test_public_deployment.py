from fastapi.testclient import TestClient
from backend import main

def test_untrusted_hosts_are_rejected(client):
    assert client.get('/api/health',headers={'Host':'attacker.example'}).status_code==400

def test_https_session_cookie_and_transport_headers(client,monkeypatch):
    monkeypatch.setattr(main,'SECURE',True)
    with TestClient(main.app,base_url='https://localhost:8015') as secure:
        r=secure.post('/api/auth/login',json={'email':'owner@example.test','password':'Test-password-123!'})
        assert r.status_code==200,r.text
        cookie=r.headers['set-cookie'].lower()
        assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
        assert secure.get('/api/auth/me').status_code==200
        assert 'max-age=31536000' in r.headers['strict-transport-security']
        assert r.headers['x-robots-tag']=='noindex, nofollow, noarchive'

def test_www_canonical_redirect_is_same_site_only(client,monkeypatch):
    monkeypatch.setattr(main,'PUBLIC_URL','https://packaging.example')
    r=client.get('/portal?view=specs',headers={'Host':'www.packaging.example'},follow_redirects=False)
    assert r.status_code==308 and r.headers['location']=='https://packaging.example/portal?view=specs'
    assert client.get('/portal',headers={'Host':'www.attacker.example'},follow_redirects=False).status_code==400
    assert client.get('/robots.txt').text=='User-agent: *\nDisallow: /\n'
