"""Read existing local session history for the Architect's reported identity response."""
import base64
import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path('L:/LocalCoder')

def visible(value):
    if isinstance(value, list):
        return [visible(item) for item in value if not isinstance(item, dict) or item.get('type') not in ('reasoning', 'thinking')]
    if isinstance(value, dict):
        return {key: visible(item) for key, item in value.items() if key not in ('reasoning_content', 'thinking')}
    return value

def main():
    executable = Path(os.environ['APPDATA']) / 'npm/node_modules/@opencode/cli/bin/opencode.exe'
    credential = subprocess.run([str(executable), 'service', 'get', 'password'], capture_output=True, text=True, timeout=15)
    if credential.returncode:
        raise RuntimeError('Could not obtain the existing local service credential')
    token = credential.stdout.strip()
    auth = 'Basic ' + base64.b64encode(('opencode:' + token).encode()).decode()
    sessions = json.loads((ROOT / '.opencode/evals/opencode-identity-session-list-20261118.json').read_text(encoding='utf-8-sig'))['data']
    records = []
    for session in sessions:
        title = session.get('title', '')
        if any(word in title.casefold() for word in ('bounded', 'prompt identity audit', 'continuity', 'memory', 'smoke', 'diagnostic')):
            continue
        request = urllib.request.Request('http://127.0.0.1:28894/api/session/' + session['id'] + '/context',
                                         headers={'Authorization': auth})
        with urllib.request.urlopen(request, timeout=30) as response:
            context = visible(json.load(response))
        matches = []
        for message in context.get('data', []):
            if message.get('type') != 'assistant':
                continue
            text = '\n'.join(part.get('text', '') for part in message.get('content', []) if part.get('type') == 'text')
            if any(term in text.casefold() for term in ('sovereign autonomous system', 'not viv', 'phase 1 while you were away')):
                matches.append({'message_id': message.get('id'), 'text': text})
        record = {'id': session['id'], 'title': title, 'agent': session.get('agent'),
                  'model': session.get('model'), 'location': session.get('location'), 'matches': matches}
        records.append(record)
        if matches:
            destination = ROOT / '.opencode/evals' / ('opencode-original-identity-context-' + session['id'] + '.json')
            destination.write_text(json.dumps(context, indent=2), encoding='utf-8')
            record['context_file'] = str(destination)
    destination = ROOT / '.opencode/evals/opencode-identity-history-audit-20261118.json'
    destination.write_text(json.dumps({'sessions': records}, indent=2), encoding='utf-8')
    print(json.dumps({'audit': str(destination), 'searched': len(records),
                      'matches': [{**row, 'matches': [{'message_id': m['message_id'], 'excerpt': m['text'][:220]} for m in row['matches']]}
                                  for row in records if row['matches']]}))

if __name__ == '__main__':
    main()
