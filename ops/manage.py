"""Local operator recovery; no remote password-reset backdoor."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.db import connect,audit
from backend.security import password_hash

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['users','reset-password']);parser.add_argument('--email');args=parser.parse_args()
    if args.action=='users':
        with connect() as c:
            for row in c.execute('SELECT id,name,email,admin,active FROM users'): print(dict(row))
    else:
        if not args.email: parser.error('--email is required')
        first=getpass.getpass('New password (12+ characters): ');second=getpass.getpass('Confirm new password: ')
        if len(first)<12 or first!=second: raise SystemExit('Password length or confirmation failed; no change made')
        with connect(write=True) as c:
            row=c.execute('SELECT id FROM users WHERE email=?',(args.email.lower(),)).fetchone()
            if not row: raise SystemExit('User not found')
            c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(first),row['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
            audit(c,None,None,'password.operator_reset',row['id'])
        print('Password reset; all sessions for the user revoked.')
