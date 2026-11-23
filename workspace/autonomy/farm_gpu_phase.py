"""Bounded GPU handoff using existing Hive controls and inference lock."""
from contextlib import contextmanager
import json
import time
import subprocess
import os
from urllib.request import Request
from viv_autonomy import Store, STATE, MODEL, file_lock, worker_alive, start_worker


def _body_runtime_guard():
    from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard

    return RuntimeBodyGuard(requested_threads=2)


def run_gpu_child(command, cwd, timeout, *, body_guard=None):
    """Bound the entire Windows launcher tree before restoring inference."""
    body_guard = body_guard or _body_runtime_guard()
    body_guard.check(force=True)
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                      | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    try:
        deadline = time.monotonic() + timeout
        while True:
            body_guard.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                code = process.wait(timeout=min(1.0, remaining))
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise subprocess.TimeoutExpired(command, timeout)
    except BaseException:
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                    check=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                process.kill()
            process.wait(timeout=30)
        raise
    if code:
        raise subprocess.CalledProcessError(code, command)
    return code


def ollama(path, body=None, timeout=60):
    request = Request('http://127.0.0.1:11434/api/' + path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json'})
    from aios_rebuild.main_core.mind_runtime_gate import open_authorized_model_request

    with open_authorized_model_request(request, timeout=timeout, requested_threads=2) as response:
        return json.load(response)


@contextmanager
def gpu_training_phase(resume_farm=False):
    body_guard = _body_runtime_guard()
    body_guard.check(force=True)
    store = Store()
    with file_lock(STATE / 'farm_gpu_phase.lock'):
        body_guard.check(force=True)
        previous = {'enabled': store.get('enabled'), 'worker_mode': store.get('worker_mode')}
        started = time.time()
        store.event('farm_gpu_phase_started', previous)
        store.set('farm_gpu_phase', {'stage': 'pausing_inference', 'started': started, 'previous': previous})
        store.set('enabled', False)
        try:
            deadline = time.monotonic() + 300
            while worker_alive():
                body_guard.check()
                if time.monotonic() >= deadline:
                    raise TimeoutError('Hive worker did not finish its current cycle within 300 seconds')
                time.sleep(.5)
            # Keep the shared inference lock for the whole training phase.
            with file_lock(STATE / 'inference.lock', wait=300):
                body_guard.check(force=True)
                store.set('gpu_training_active', True)
                residents = ollama('ps').get('models', [])
                others = [row['name'] for row in residents if row['name'] != MODEL]
                if others:
                    raise RuntimeError('Another Ollama model occupies the GPU: ' + ', '.join(others))
                ollama('generate', {'model': MODEL, 'keep_alive': 0, 'stream': False})
                if any(row.get('size_vram', 0) for row in ollama('ps').get('models', [])):
                    raise RuntimeError('Ollama did not release its GPU allocation')
                store.set('farm_gpu_phase', {'stage': 'training', 'started': started, 'previous': previous})
                store.event('farm_gpu_phase_gpu_released', {'model': MODEL})
                yield body_guard
        finally:
            # The training subprocess has exited before this path runs.
            resume_requested = bool(resume_farm and previous['enabled'])
            resume = False
            store.set('farm_gpu_phase', {'stage': 'restoring_queen' if resume_requested else 'releasing_gpu',
                                        'started': started, 'previous': previous})
            restore_error = None
            try:
                if resume_requested:
                    body_guard.check(force=True)
                    ollama('generate', {'model': MODEL, 'keep_alive': '30m', 'stream': False}, timeout=180)
                    resume = True
            except Exception as exc:
                restore_error = f'{type(exc).__name__}: {exc}'
            finally:
                store.set('gpu_training_active', False)
                store.set('worker_mode', previous['worker_mode'])
                store.set('enabled', resume)
                if resume:
                    start_worker()
                restored = {'stage': ('restored' if resume else 'paused') if restore_error is None else 'restore_error',
                            'started': started, 'finished': time.time(), 'previous': previous,
                            'farm_resumed': resume, 'finish_policy': 'resume' if resume_farm else 'leave_paused',
                            'error': restore_error}
                store.set('farm_gpu_phase', restored)
                store.event('farm_gpu_phase_finished', restored)
