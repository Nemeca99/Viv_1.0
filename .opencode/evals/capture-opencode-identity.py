"""Capture real installed OpenCode requests; return an explicit diagnostic error, never an AI answer."""
import argparse
import base64
import hashlib
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path('L:/LocalCoder')

def content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(content_text(item) for item in value)
    if isinstance(value, dict):
        return str(value.get('text', ''))
    return ''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='before')
    parser.add_argument('--directory', default=str(ROOT))
    parser.add_argument('--agents', nargs='+', default=['build', 'drone_build'])
    parser.add_argument('--compact', action='store_true')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination = ROOT / '.opencode/evals' / ('opencode-identity-' + args.label + '-' + stamp)
    destination.mkdir(exist_ok=False)
    received = []
    lock = threading.Lock()
    class Sink(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            if self.path not in ('/v1/models', '/api/v1/models', '/api/v0/models'):
                self.send_error(404)
                return
            with urllib.request.urlopen('http://192.168.40.21:1234' + self.path, timeout=15) as response:
                data = response.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
        def do_POST(self):
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 2_000_000:
                self.send_error(413)
                return
            body = json.loads(self.rfile.read(size))
            with lock:
                number = len(received)
                received.append({'path': self.path, 'body': body})
                (destination / f'request-{number:03d}.json').write_text(json.dumps(received[-1], indent=2), encoding='utf-8')
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"diagnostic_capture_only_no_generation","type":"diagnostic"}}')
    sink = ThreadingHTTPServer(('127.0.0.1', 0), Sink)
    threading.Thread(target=sink.serve_forever, daemon=True).start()
    token = secrets.token_hex(24)
    executable = Path(os.environ['APPDATA']) / 'npm/node_modules/@opencode/cli/bin/opencode.exe'
    model_config = json.loads((ROOT / 'opencode.json').read_text(encoding='utf-8-sig'))['providers']['lmstudio']['models']['omnicoder-2-9b']
    overlay = {'providers': {'lmstudio': {'settings': {'baseURL': f'http://127.0.0.1:{sink.server_port}/v1'},
                                        'models': {'omnicoder-2-9b': model_config}}}}
    env = dict(os.environ, OPENCODE_PASSWORD=token, OPENCODE_CONFIG_CONTENT=json.dumps(overlay))
    logs = []
    process = subprocess.Popen([str(executable), 'serve', '--port', '28911', '--hostname', '127.0.0.1'],
                               cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8')
    def consume(stream):
        for line in stream:
            logs.append(line.replace(token, '[redacted]'))
    threading.Thread(target=consume, args=(process.stdout,), daemon=True).start()
    threading.Thread(target=consume, args=(process.stderr,), daemon=True).start()
    auth = 'Basic ' + base64.b64encode(('opencode:' + token).encode()).decode()
    def api(path, body=None):
        request = urllib.request.Request('http://127.0.0.1:28911' + path,
                    data=None if body is None else json.dumps(body).encode(),
                    headers={'Authorization': auth, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=45) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    result = {'label': args.label, 'directory': args.directory, 'capture_only': True, 'model_generation_performed': False,
              'config_overlay': overlay, 'project_config_sha256': hashlib.sha256((ROOT / 'opencode.json').read_bytes()).hexdigest(),
              'cases': []}
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise RuntimeError('private OpenCode exited before readiness')
            try:
                api('/api/info')
                break
            except urllib.error.URLError:
                time.sleep(.25)
        else:
            raise RuntimeError('private OpenCode readiness deadline')
        for agent in args.agents:
            marker = 'LOCAL-IDENTITY-CAPTURE-' + agent + '-' + stamp
            session = api('/api/session', {'location': {'directory': args.directory}, 'title': 'Read-only prompt identity audit',
                                          'agent': agent, 'model': {'providerID': 'lmstudio', 'id': 'omnicoder-2-9b'}})['data']
            api('/api/session/' + session['id'] + '/prompt', {'text': marker + '\nRead-only diagnostic: identify the host software separately from the deployment name. Do not call tools.'})
            deadline = time.monotonic() + 90
            captured = None
            while time.monotonic() < deadline:
                captured = next((item for item in received if marker in json.dumps(item['body'])), None)
                if captured is not None:
                    break
                if process.poll() is not None:
                    raise RuntimeError('private OpenCode exited while capturing')
                time.sleep(.2)
            if captured is None:
                result['context_on_timeout'] = api('/api/session/' + session['id'] + '/context')
                raise RuntimeError('no actual provider request captured for ' + agent)
            body = captured['body']
            messages = body.get('messages', body.get('input', []))
            system = '\n'.join([content_text(body.get('instructions', ''))] + [
                content_text(message.get('content', '')) for message in messages if isinstance(message, dict)
                and message.get('role') in ('system', 'developer')])
            system_file = destination / (agent + '-system.txt')
            system_file.write_text(system, encoding='utf-8')
            result['cases'].append({'agent': agent, 'session_id': session['id'], 'system_file': str(system_file),
                 'system_sha256': hashlib.sha256(system.encode()).hexdigest(),
                 'custom_drone_prompt_present': 'You are Viv in the LocalCoder Drone role.' in system,
                 'runtime_context_present': '<viv_runtime_context>' in system,
                 'stale_codex_queen_claim': 'In this current coordination, Codex is the Queen.' in system,
                 'localcoder_tools': [tool.get('function', {}).get('name', tool.get('name', '')) for tool in body.get('tools', [])
                                      if tool.get('function', {}).get('name', tool.get('name', '')).startswith(('aios_router_', 'localcoder_'))],
                 'software_identity_present': any(text in system.casefold() for text in ('you are opencode', 'you are an interactive cli tool')),
                 'system_chars': len(system)})
        if args.compact:
            start = len(received)
            target = result['cases'][0]['session_id']
            api('/api/session/' + target + '/compact', {'delivery': 'steer'})
            deadline = time.monotonic() + 60
            captured = None
            while time.monotonic() < deadline:
                captured = next((item for item in received[start:] if 'Summarize this conversation for task continuation.' in json.dumps(item['body'])), None)
                if captured is not None:
                    break
                time.sleep(.2)
            if captured is None:
                result['compaction_context'] = api('/api/session/' + target + '/context')
                raise RuntimeError('No actual local compaction generation request captured')
            body = captured['body']
            messages = body.get('messages', body.get('input', []))
            system = '\n'.join([content_text(body.get('instructions', ''))] + [content_text(message.get('content', ''))
                         for message in messages if isinstance(message, dict) and message.get('role') in ('system', 'developer')])
            (destination / 'compaction-system.txt').write_text(system, encoding='utf-8')
            result['compaction_generation'] = {'runtime_context_present': '<viv_runtime_context>' in system,
                 'runtime_context_in_prompt': '<viv_runtime_context>' in json.dumps(body),
                 'system_sha256': hashlib.sha256(system.encode()).hexdigest(), 'system_chars': len(system),
                 'summary_generated': False, 'ltm_checkpoint_claimed': False}
        result['result'] = 'CAPTURED'
    except Exception as error:
        result.update(result='FAIL', error=repr(error))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        sink.shutdown()
        sink.server_close()
        result['logs'] = logs
        (destination / 'audit.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps({'result': result['result'], 'audit': str(destination / 'audit.json'),
                          'cases': result['cases'], 'compaction_generation': result.get('compaction_generation'),
                          'error': result.get('error')}))
    return 0 if result['result'] == 'CAPTURED' else 1

if __name__ == '__main__':
    raise SystemExit(main())
