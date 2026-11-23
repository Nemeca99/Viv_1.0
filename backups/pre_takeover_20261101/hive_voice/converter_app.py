"""Local, RAM-buffered text-to-WAV utility using Viv's selected voices."""

from __future__ import annotations

import json
import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT.parent
BODY_PYTHON = Path(r"L:\.venv\Scripts\python.exe")
MAX_TEXT_CHARS = 6_000
MAX_REQUEST_BYTES = 64_000
MAX_WAV_BYTES = 64 * 1024 * 1024
MAX_TICKETS = 4
TICKET_TTL_SECONDS = 24 * 60 * 60
RANGE_PATTERN = re.compile(r"^bytes=(\d+)-(\d*)$")

PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Viv Voice Converter</title>
<style>
body{font:16px system-ui;max-width:48rem;margin:3rem auto;padding:0 1rem;color:#222}
textarea{box-sizing:border-box;width:100%;min-height:16rem;padding:1rem;font:inherit}
select,button{font:inherit;margin:.75rem .5rem .75rem 0;padding:.5rem}
#status{min-height:1.5em} audio{display:block;margin:1rem 0;width:100%}
</style>
<h1>Text to WAV</h1>
<textarea id="text" maxlength="6000" aria-label="Text to convert"></textarea><br>
<label for="voice">Voice</label>
<select id="voice"><option value="human">Queen (8B) — default voice</option><option value="logic">Drones (1.7B) — faster voice</option></select>
<button id="render">Render</button><button id="resume" disabled>Resume download</button><button id="download" disabled>Download WAV</button>
<p id="status" role="status"></p><audio id="preview" controls hidden></audio>
<script>
let currentUrl=null, currentBlob=null, downloadUrl=null, received=[];
const status=document.querySelector('#status'), button=document.querySelector('#render');
const resume=document.querySelector('#resume');
document.querySelector('#download').onclick=()=>{
  if(!currentBlob)return; const link=document.createElement('a');
  link.href=currentUrl; link.download='viv-voice.wav'; link.click();
};
async function collectWav(){
  if(!downloadUrl)return;
  resume.disabled=true; button.disabled=true; status.textContent='Receiving WAV…';
  const offset=received.reduce((size,part)=>size+part.byteLength,0);
  try{
    const headers=offset?{Range:`bytes=${offset}-`}:{};
    const response=await fetch(downloadUrl,{headers});
    if(!response.ok)throw new Error('The download token expired or delivery was unavailable.');
    const reader=response.body.getReader();
    while(true){const {done,value}=await reader.read();if(done)break;received.push(value)}
    currentBlob=new Blob(received,{type:'audio/wav'});
    if(currentUrl)URL.revokeObjectURL(currentUrl);
    currentUrl=URL.createObjectURL(currentBlob);
    const preview=document.querySelector('#preview');preview.src=currentUrl;preview.hidden=false;
    document.querySelector('#download').disabled=false;downloadUrl=null;received=[];
    status.textContent='Ready.';
  }catch(error){status.textContent='Transfer interrupted. Resume when connected.';resume.disabled=false}
  finally{button.disabled=false}
}
resume.onclick=collectWav;
button.onclick=async()=>{
  button.disabled=true; document.querySelector('#download').disabled=true;
  status.textContent='Rendering…';
  try{
    const response=await fetch('/generate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({text:document.querySelector('#text').value,mode:document.querySelector('#voice').value})});
    if(!response.ok)throw new Error((await response.json()).error||'Render held');
    const ticket=await response.json();downloadUrl=ticket.download_url;
    await collectWav();
  }catch(error){status.textContent=error.message||'Render failed.'}
  finally{button.disabled=false}
};
</script></html>"""


@dataclass
class AudioTicket:
    audio: bytes
    mode: str
    expires_at: float
    delivered: list[tuple[int, int]]


class RamTicketStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._tickets: dict[str, AudioTicket] = {}
        self._stop = threading.Event()
        self._sweeper = threading.Thread(target=self._sweep_loop, daemon=True)
        self._sweeper.start()

    def create(self, audio: bytes, mode: str) -> str:
        if not audio or len(audio) > MAX_WAV_BYTES:
            raise ValueError("rendered WAV is empty or exceeds the RAM limit")
        with self._lock:
            self._expire_locked()
            if len(self._tickets) >= MAX_TICKETS:
                raise RuntimeError("RAM delivery queue is full; collect an existing WAV first")
            token = secrets.token_urlsafe(32)
            self._tickets[token] = AudioTicket(
                audio=audio, mode=mode, expires_at=self._clock() + TICKET_TTL_SECONDS,
                delivered=[],
            )
            return token

    def get(self, token: str) -> AudioTicket | None:
        with self._lock:
            self._expire_locked()
            return self._tickets.get(token)

    def delete(self, token: str) -> None:
        with self._lock:
            self._tickets.pop(token, None)

    def record_delivery(self, token: str, start: int, end: int) -> bool:
        with self._lock:
            self._expire_locked()
            ticket = self._tickets.get(token)
            if ticket is None:
                return False
            ranges = sorted([*ticket.delivered, (start, end)])
            merged: list[list[int]] = []
            for range_start, range_end in ranges:
                if merged and range_start <= merged[-1][1] + 1:
                    merged[-1][1] = max(merged[-1][1], range_end)
                else:
                    merged.append([range_start, range_end])
            ticket.delivered = [(low, high) for low, high in merged]
            if ticket.delivered and ticket.delivered[0][0] == 0 and ticket.delivered[0][1] >= len(ticket.audio) - 1:
                del self._tickets[token]
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._tickets.clear()
        self._stop.set()

    def _sweep_loop(self) -> None:
        while not self._stop.wait(60):
            with self._lock:
                self._expire_locked()

    def _expire_locked(self) -> None:
        now = self._clock()
        for token in [key for key, ticket in self._tickets.items() if ticket.expires_at <= now]:
            del self._tickets[token]


def body_runtime_allow() -> None:
    result = subprocess.run(
        [str(BODY_PYTHON), "-m", "aios_rebuild.main_core.mind_runtime_gate"],
        cwd=WORKSPACE_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        verdict = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RuntimeError("AIOS body gate returned no valid decision") from error
    if result.returncode != 0 or not (
        verdict.get("allowed") is True
        and verdict.get("disposition") == "ALLOW_MIND_RUNTIME"
        and verdict.get("authority") == "deterministic_aios_body_rust"
    ):
        raise RuntimeError("AIOS body authority held voice rendering")


def render_viv_wav(text: str, mode: str) -> bytes:
    from speak import render_wav

    return render_wav(text, mode)


def make_handler(
    *,
    render: Callable[[str, str], bytes] = render_viv_wav,
    body_gate: Callable[[], None] = body_runtime_allow,
    tickets: RamTicketStore | None = None,
):
    ticket_store = tickets or RamTicketStore()
    render_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def _is_local_request(self) -> bool:
            port = self.server.server_port
            allowed_hosts = {
                f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}",
            }
            if self.headers.get("Host", "").lower() not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            return origin in {f"http://{host}" for host in allowed_hosts}

        def _send_json(self, status: int, payload: dict[str, str]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            if not self._is_local_request():
                self._send_json(403, {"error": "Loopback requests only"})
                return
            path = urlsplit(self.path).path
            if path == "/":
                encoded = PAGE.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; media-src blob:")
                self.end_headers()
                self.wfile.write(encoded)
                return
            if not path.startswith("/download/"):
                self._send_json(404, {"error": "Not found"})
                return
            token = path.removeprefix("/download/")
            ticket = ticket_store.get(token)
            if ticket is None:
                self._send_json(404, {"error": "Download token expired or already collected"})
                return
            total = len(ticket.audio)
            start, end, status = 0, total - 1, 200
            range_header = self.headers.get("Range")
            if range_header:
                match = RANGE_PATTERN.fullmatch(range_header.strip())
                if not match:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                start = int(match.group(1))
                end = min(int(match.group(2)) if match.group(2) else total - 1, total - 1)
                if start >= total or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = 206
            body = memoryview(ticket.audio)[start:end + 1]
            self.send_response(status)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Disposition", f'attachment; filename="viv-{ticket.mode}.wav"')
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.end_headers()
            try:
                for offset in range(0, len(body), 64 * 1024):
                    block = body[offset:offset + 64 * 1024]
                    written = self.wfile.write(block)
                    if written != len(block):
                        return
                    ticket_store.record_delivery(
                        token, start + offset, start + offset + written - 1,
                    )
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
                return

        def do_POST(self) -> None:
            if not self._is_local_request():
                self._send_json(403, {"error": "Loopback requests only"})
                return
            if urlsplit(self.path).path != "/generate":
                self._send_json(404, {"error": "Not found"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                content_length = -1
            if content_length < 0 or content_length > MAX_REQUEST_BYTES:
                self._send_json(413, {"error": "Request size is outside the allowed limit"})
                return
            body = self.rfile.read(content_length)
            try:
                request = json.loads(body)
                text = request.get("text") if isinstance(request, dict) else None
                mode = request.get("mode") if isinstance(request, dict) else None
                if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
                    self._send_json(400, {"error": "Enter 1 to 6,000 characters of text"})
                    return
                if mode is None:
                    mode = "human"
                if mode not in {"human", "logic"}:
                    self._send_json(400, {"error": "Select one of Viv's available voices"})
                    return
                body_gate()
                with render_lock:
                    audio = render(text, mode)
                token = ticket_store.create(audio, mode)
                self._send_json(201, {"download_url": f"/download/{token}"})
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"error": "Request must be valid UTF-8 JSON"})
            except Exception:
                self._send_json(503, {"error": "Rendering is held or unavailable; no WAV was retained"})
            finally:
                body = b""
                if "text" in locals():
                    text = ""
                if "request" in locals():
                    request = None

    Handler.ticket_store = ticket_store
    return Handler


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("voice converter may bind only to loopback")
    server = ThreadingHTTPServer((host, port), make_handler())
    try:
        print(f"Viv Voice Converter: http://{host}:{port}/")
        server.serve_forever()
    finally:
        server.server_close()
        server.RequestHandlerClass.ticket_store.clear()


if __name__ == "__main__":
    serve()
