import hashlib
import hmac
import os
import secrets
import time
from fastapi import HTTPException, Request
from .db import connect, audit

SESSION_SECONDS = 8*3600
SECURE = os.getenv('AXIOM_SECURE_COOKIES','0') == '1'
ORIGINS = set(os.getenv('AXIOM_ORIGINS','http://localhost:8015,http://127.0.0.1:8015').split(','))

def password_hash(password):
    salt = secrets.token_bytes(16)
    return 'pbkdf2$600000$' + salt.hex() + '$' + hashlib.pbkdf2_hmac('sha256',password.encode(),salt,600000).hex()

def password_ok(password, encoded):
    try:
        _, rounds, salt, expected = encoded.split('$')
        actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError,TypeError):
        return False

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def current(request: Request):
    token = request.cookies.get('axiom_session','')
    with connect() as c:
        r = c.execute('SELECT u.*,s.csrf,s.expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.hash=? AND s.expires>? AND u.active=1',(digest(token),time.time())).fetchone()
    if not r:
        raise HTTPException(401,'Sign in to continue')
    return dict(r)

def csrf(request, user):
    if not hmac.compare_digest(request.headers.get('x-csrf-token',''), user['csrf']):
        raise HTTPException(403,'Missing or invalid CSRF token; refresh and try again')

def access(c, user, project, write=False, review=False):
    p = c.execute('SELECT * FROM projects WHERE id=?',(project,)).fetchone()
    role = c.execute('SELECT role FROM members WHERE project_id=? AND user_id=?',(project,user['id'])).fetchone()
    if not p or (not role and not user['admin']):
        raise HTTPException(404,'Project not found')
    value = 'reviewer' if user['admin'] else role['role']
    if (write and value=='viewer') or (review and value!='reviewer'):
        raise HTTPException(403,'Reviewer permission required' if review else 'Editor permission required')
    if p['archived'] and (write or review):raise HTTPException(409,'Project is archived and read-only; restore it before making changes')
    return dict(p), value

def admin(user):
    if not user['admin']:
        raise HTTPException(403,'Administrator permission required')

def login(c, request, email, password):
    key = digest((request.client.host if request.client else 'local')+'|'+email.lower())
    row = c.execute('SELECT * FROM login_attempts WHERE key=?',(key,)).fetchone()
    now=time.time()
    if row and row['reset']>now and row['attempts']>=8:
        raise HTTPException(429,'Too many attempts. Try again in 15 minutes.')
    u=c.execute('SELECT * FROM users WHERE email=? AND active=1',(email.lower(),)).fetchone()
    # Always perform an expensive hash on unknown accounts too.
    valid=password_ok(password,u['password']) if u else password_ok(password, DUMMY)
    if not valid:
        n = row['attempts']+1 if row and row['reset']>now else 1
        c.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(key,n,now+900))
        c.commit()
        raise HTTPException(401,'Email or password is incorrect')
    c.execute('DELETE FROM login_attempts WHERE key=?',(key,))
    c.execute('DELETE FROM sessions WHERE expires<?',(now,))
    token=secrets.token_urlsafe(48)
    token_csrf=secrets.token_urlsafe(32)
    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),u['id'],token_csrf,now+SESSION_SECONDS))
    audit(c,None,u['id'],'session.created')
    return token, token_csrf, dict(u)

DUMMY=password_hash('unusable-random-'+secrets.token_hex(24))
