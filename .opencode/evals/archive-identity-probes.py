"""Archive only this task's capture-only diagnostic sessions; retain their history."""
import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path('L:/LocalCoder')
exe = Path(os.environ['APPDATA']) / 'npm/node_modules/@opencode/cli/bin/opencode.exe'
credential = subprocess.run([str(exe), 'service', 'get', 'password'], capture_output=True, text=True, timeout=15)
if credential.returncode:
    raise RuntimeError('Existing local service credential unavailable')
auth = 'Basic ' + base64.b64encode(('opencode:' + credential.stdout.strip()).encode()).decode()
def api(path, body=None, method=None):
    request = urllib.request.Request('http://127.0.0.1:28894' + path,
        data=None if body is None else json.dumps(body).encode(), method=method,
        headers={'Authorization': auth, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None
ids = set()
for path in (ROOT / '.opencode/evals').glob('opencode-identity-*/audit.json'):
    audit = json.loads(path.read_text())
    if audit.get('capture_only'):
        ids.update(case['session_id'] for case in audit.get('cases', []))
archived = []
for sid in sorted(ids):
    info = api('/api/session/' + sid)['data']
    if info.get('title') != 'Read-only prompt identity audit':
        raise RuntimeError('Unexpected session title; leave it untouched: ' + sid)
    api('/api/session/' + sid + '/interrupt', {})
    api('/api/session/' + sid, {'archived': True}, method='PATCH')
    archived.append(sid)
record = {'result': 'PASS', 'archived': archived, 'history_deleted': False,
          'original_user_session_untouched': 'ses_e11dcf06dffeVzN60WocibWsG3' not in archived}
(ROOT / '.opencode/evals/identity-probe-cleanup-20261118.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps({'result': 'PASS', 'archived_count': len(archived), 'history_deleted': False}))
