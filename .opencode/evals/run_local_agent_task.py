"""Bounded task dispatch to the existing desktop service; preserves raw evidence."""
import argparse
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path('L:/LocalCoder')
CLI = Path(os.environ['APPDATA']) / 'ai.opencode.desktop/cli/2.3.0-x64/opencode-cli.exe'
JOURNAL = ROOT / 'DRONE_JOURNAL.md'
JOURNAL_LOCK = ROOT / '.opencode/evals/DRONE_JOURNAL.lock'

def append_journal(entry):
    """Append a compact receipt summary without copying prompts or reasoning."""
    JOURNAL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_LOCK.open('a+b') as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b'0')
            lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            with JOURNAL.open('a', encoding='utf-8', newline='') as journal:
                journal.write(entry)
                journal.flush()
                os.fsync(journal.fileno())
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)

def export_session_until_terminal(session_id, deadline):
    """Poll the desktop service after a CLI disconnect until the session is idle."""
    latest_data = None
    latest_raw = ''
    latest_active = False
    while True:
        remaining = deadline - time.monotonic()
        timeout = max(1, min(15, int(remaining))) if remaining > 0 else 1
        try:
            exported = subprocess.run(
                [str(CLI), 'session', 'export', session_id], cwd=ROOT,
                capture_output=True, text=True, encoding='utf-8', timeout=timeout,
            )
            try:
                data = json.loads(exported.stdout)
            except ValueError:
                data = None
            if isinstance(data, dict):
                latest_data = data
                latest_raw = exported.stdout
                info = data.get('info', {})
                session_time = info.get('time', {})
                if info.get('outcome') or session_time.get('idle'):
                    return latest_data, latest_raw, True, False
                latest_active = bool(session_time.get('busy')) and not bool(session_time.get('idle'))
        except subprocess.TimeoutExpired:
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return latest_data, latest_raw, False, latest_active
        time.sleep(min(1.0, remaining))

def interrupt_session(session_id, directory, filename='interrupt.txt'):
    stopped = subprocess.run(
        [str(CLI), 'api', 'POST', f'/api/session/{session_id}/interrupt', '--data', '{}'],
        cwd=ROOT, capture_output=True, text=True, timeout=15,
    )
    (directory / filename).write_text(stopped.stdout + stopped.stderr, encoding='utf-8')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('prompt_file', type=Path)
    parser.add_argument('--seconds', type=int, default=120)
    parser.add_argument('--session')
    parser.add_argument('--agent', choices=('build', 'drone_read', 'drone_build'), default='build')
    parser.add_argument('--visible', action='store_true',
                        help='Create a titled OpenCode session visible in the desktop session list')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory = ROOT / '.opencode/evals/task_runs' / stamp
    directory.mkdir(parents=True)
    prompt = args.prompt_file.read_text(encoding='utf-8-sig')
    (directory / 'prompt.txt').write_text(prompt, encoding='utf-8')
    command = [str(CLI), 'run', '--format', 'json', '--agent', args.agent]
    if args.session:
        # Keep continuations on the exact agent profile that created the session.
        command += ['--session', args.session]
    else:
        if args.visible:
            command += ['--title', f'LocalCoder Drone {stamp}']
        else:
            command.append('--archived')
    command.append(prompt)
    # Capture request metadata through the existing bridge hook. The trace omits
    # message bodies and records only model/tool names, character counts, hashes,
    # memory-injection status, and provider response metadata.
    child_env = os.environ.copy()
    child_env['LOCALCODER_TRACE_LLM'] = '1'
    child_env['LOCALCODER_TRACE_LLM_PATH'] = str(directory / 'provider-trace.jsonl')
    start = time.monotonic()
    deadline = start + max(args.seconds, 1)
    timed_out = False
    background_interrupted = False
    with (directory / 'events.jsonl').open('w', encoding='utf-8') as out, (directory / 'stderr.txt').open('w', encoding='utf-8') as err:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=child_env)
        try:
            code = process.wait(timeout=args.seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Stop the server-side task, not just the observer CLI.
            ids = []
            for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
                try:
                    value = json.loads(line)
                    if value.get('sessionID'): ids.append(value['sessionID'])
                except ValueError:
                    pass
            sid = args.session or next(iter(ids), None)
            if sid:
                interrupt_session(sid, directory)
                background_interrupted = True
            process.terminate()
            code = process.wait(timeout=10)
    records = []
    for line in (directory / 'events.jsonl').read_text(encoding='utf-8').splitlines():
        try: records.append(json.loads(line))
        except ValueError: pass
    # OpenCode 2.3 may persist a complete session and then emit an ECONNRESET
    # event instead of its normal JSON stream. Recover the ID from either shape.
    sessions = list(dict.fromkeys(
        sid for r in records
        for sid in (r.get('sessionID'), r.get('data', {}).get('sessionID'), r.get('error', {}).get('sessionID'))
        if sid
    ))
    exports = []
    export_terminal_states = []
    for sid in sessions:
        recovery_deadline = time.monotonic() + 5 if timed_out else deadline
        data, raw, terminal, active = export_session_until_terminal(sid, recovery_deadline)
        if active and not terminal and not timed_out:
            if raw:
                (directory / f'{sid}.pre-interrupt.json').write_text(raw, encoding='utf-8')
            timed_out = True
            background_interrupted = True
            interrupt_session(sid, directory, 'interrupt-after-transport-exit.txt')
            data, raw, terminal, active = export_session_until_terminal(sid, time.monotonic() + 5)
        export_path = directory / f'{sid}.json'
        if raw:
            export_path.write_text(raw, encoding='utf-8')
        if data is not None:
            exports.append(data)
        export_terminal_states.append(terminal)
    assistant_messages = [m for data in exports for m in data.get('messages', []) if m.get('type') == 'assistant']
    session_outcomes = [data.get('info', {}).get('outcome') for data in exports if data.get('info', {}).get('outcome')]
    model_ids = list(dict.fromkeys(m.get('model', {}).get('id') for m in assistant_messages if m.get('model', {}).get('id')))
    visible_final_text = []
    for message in reversed(assistant_messages):
        if message.get('finish') != 'stop':
            continue
        visible_final_text = [part.get('text', '') for part in message.get('content', [])
                              if part.get('type') == 'text' and part.get('text', '').strip()]
        if visible_final_text:
            break
    session_tools = [dict(tool=part.get('name'), status=part.get('state', {}).get('status'))
                     for message in assistant_messages for part in message.get('content', [])
                     if part.get('type') == 'tool']
    event_tools = [dict(tool=r['part'].get('tool'), status=r.get('part', {}).get('state', {}).get('status'))
                   for r in records if r.get('type') == 'tool_use']
    tools_used = session_tools or event_tools
    shell_checks = []
    for message in assistant_messages:
        for part in message.get('content', []):
            if part.get('type') != 'tool' or part.get('name') != 'shell':
                continue
            state = part.get('state', {})
            output = '\n'.join(c.get('text', '').strip() for c in state.get('content', []) if c.get('type') == 'text').strip()
            shell_checks.append(dict(status=state.get('status'), exit=state.get('metadata', {}).get('exit'),
                                     output=output[:500]))
    # The CLI JSON stream can report ECONNRESET after the server has already
    # committed a successful assistant turn. Session export is authoritative
    # for the completed turn; keep the transport exit as separate evidence.
    transport_exit_code = code
    session_succeeded = bool(session_outcomes) and all(value == 'succeeded' for value in session_outcomes)
    session_exports_terminal = bool(sessions) and all(export_terminal_states)
    tool_errors = [item for item in tools_used if item.get('status') != 'completed']
    shell_check_errors = [item for item in shell_checks
                          if item.get('status') != 'completed' or item.get('exit') != 0]
    final_shell_check_passed = bool(shell_checks) and shell_checks[-1].get('status') == 'completed' and shell_checks[-1].get('exit') == 0
    verification_tools = {'localcoder_add_python', 'localcoder_write_exact', 'localcoder_patch', 'write', 'edit', 'patch'}
    verification_required = any(str(item.get('tool') or '').lower() in verification_tools for item in tools_used)
    task_errors = []
    blocked_tool_response = any(text.strip().lower().startswith('blocked ') for text in visible_final_text)
    if not tools_used: task_errors.append('tool_action_missing')
    if blocked_tool_response: task_errors.append('tool_request_blocked')
    if timed_out: task_errors.append('timed_out')
    if not session_succeeded: task_errors.append('session_outcome_not_succeeded')
    if not session_exports_terminal: task_errors.append('session_export_not_terminal')
    if not visible_final_text: task_errors.append('visible_final_text_missing')
    if tool_errors: task_errors.append('tool_error')
    if verification_required and not shell_checks: task_errors.append('verification_check_missing')
    elif shell_checks and not final_shell_check_passed: task_errors.append('shell_check_failed')
    task_succeeded = not task_errors
    effective_exit_code = 0 if task_succeeded else (code or 1)
    report = dict(agent=args.agent, elapsed_seconds=round(time.monotonic()-start, 3), exit_code=effective_exit_code,
                  transport_exit_code=transport_exit_code, session_outcomes=session_outcomes, timed_out=timed_out,
                  sessions=sessions, visibility=('desktop' if args.visible else 'archived'),
                  prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                  tools=tools_used,
                  model_ids=model_ids, shell_checks=shell_checks,
                  task_succeeded=task_succeeded, task_errors=task_errors,
                  tool_errors=tool_errors, shell_check_errors=shell_check_errors,
                  final_shell_check_passed=final_shell_check_passed,
                  final_text=visible_final_text, session_exports_terminal=session_exports_terminal,
                  background_interrupted=background_interrupted, evidence=str(directory))
    (directory / 'receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    tools = ', '.join(f"{item['tool']}:{item['status']}" for item in report['tools']) or 'none'
    checks = '; '.join(f"exit={item['exit']} output={item['output']!r}" for item in shell_checks) or 'none'
    result = ('task succeeded' if task_succeeded else
              'task incomplete: ' + ', '.join(task_errors))
    if task_succeeded and transport_exit_code:
        result += f'; CLI transport exited {transport_exit_code}'
    final_state = 'present' if visible_final_text else 'missing from visible text channel'
    next_step = ('Continue with the next Architect-assigned bounded task.'
                 if task_succeeded else
                 f'Review this task receipt and task_errors={",".join(task_errors)}; prepare one bounded repair step.')
    journal_entry = (
        f"\n## {stamp} — Bounded Drone task\n"
        f"- Agenda: execute the submitted bounded task; prompt SHA-256 `{report['prompt_sha256']}`.\n"
        f"- Verified state: model `{', '.join(model_ids) or 'unreported'}`; tools `{tools}`; shell check `{checks}`; {result}.\n"
        f"- Visible final response: {final_state}. No model reasoning was copied into this journal.\n"
        f"- Evidence: `{directory}`.\n"
        f"- Next self-prompt: {next_step}\n"
    )
    append_journal(journal_entry)
    print(json.dumps(report, indent=2))
    return 1 if timed_out or effective_exit_code else 0

if __name__ == '__main__':
    raise SystemExit(main())
