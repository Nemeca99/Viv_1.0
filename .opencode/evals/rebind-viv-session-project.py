"""Move the reported idle session into its actual project, preserving its history."""
import base64
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path('L:/LocalCoder')
SESSION = 'ses_e11dcf06dffeVzN60WocibWsG3'

def main():
    executable = Path(os.environ['APPDATA']) / 'npm/node_modules/@opencode/cli/bin/opencode.exe'
    credential = subprocess.run([str(executable), 'service', 'get', 'password'], capture_output=True, text=True, timeout=15)
    if credential.returncode:
        raise RuntimeError('Existing local service credential unavailable')
    auth = 'Basic ' + base64.b64encode(('opencode:' + credential.stdout.strip()).encode()).decode()
    def api(path, body=None):
        request = urllib.request.Request('http://127.0.0.1:28894' + path,
                 data=None if body is None else json.dumps(body).encode(),
                 headers={'Authorization': auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    prefix = '/api/session/' + SESSION
    before = api(prefix)['data']
    context_before = api(prefix + '/context')['data']
    inbox = api(prefix + '/inbox')['data']
    if inbox:
        raise RuntimeError('Pending user input exists; leave its delivery untouched')
    if not context_before or context_before[-1]['type'] != 'idle':
        raise RuntimeError('Reported session is not idle; preserve its current execution')
    if before['location']['directory'].rstrip('\\/').casefold() != 'l:':
        raise RuntimeError('Reported source location changed; inspect before moving')
    old_ids = {m['id'] for m in context_before if m.get('id')}
    assistant_ids = {m['id'] for m in context_before if m.get('type') == 'assistant'}
    result = {'session_id': SESSION, 'before': before, 'inbox_empty_before': True,
              'operation': 'native idle session.move; no prompt or resume submitted'}
    api(prefix + '/move', {'directory': str(ROOT), 'delivery': 'steer'})
    for _ in range(60):
        after = api(prefix)['data']
        if after['location']['directory'].rstrip('\\/').casefold() == str(ROOT).rstrip('\\/').casefold():
            break
        time.sleep(.25)
    else:
        raise RuntimeError('Native move did not reach its destination')
    api('/api/experimental/session/' + SESSION + '/wait', {})
    context_after = api(prefix + '/context')['data']
    new_ids = {m['id'] for m in context_after if m.get('id')}
    new_assistant_ids = {m['id'] for m in context_after if m.get('type') == 'assistant'}
    with urllib.request.urlopen('http://192.168.40.21:1234/api/v1/models', timeout=15) as response:
        models = json.load(response)
    loaded = [instance['id'] for model in models['models'] for instance in model.get('loaded_instances', [])]
    checks = {'moved_to_project': after['location']['directory'].rstrip('\\/').casefold() == str(ROOT).casefold(),
              'history_preserved': old_ids.issubset(new_ids),
              'no_assistant_generation': assistant_ids == new_assistant_ids,
              'agent_preserved': after.get('agent') == before.get('agent'),
              'model_preserved': after.get('model') == before.get('model'),
              'inbox_empty_after': not api(prefix + '/inbox')['data'],
              'lmstudio_still_unloaded': not loaded}
    result.update(after=after, checks=checks, result='PASS' if all(checks.values()) else 'FAIL')
    out = ROOT / '.opencode/evals/opencode-session-project-rebind-20261118.json'
    out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'result': result['result'], 'evidence': str(out), 'checks': checks}))
    return 0 if result['result'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
