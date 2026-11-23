from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from .converter_app import MAX_TEXT_CHARS, RamTicketStore, make_handler


class ConverterAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.render_calls: list[tuple[str, str]] = []
        self.gate_calls = 0
        self.store = RamTicketStore()

        def render(text: str, mode: str) -> bytes:
            self.render_calls.append((text, mode))
            return b"RIFF-test-wav"

        def gate() -> None:
            self.gate_calls += 1

        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(render=render, body_gate=gate, tickets=self.store),
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.store.clear()

    def wait_for_ticket_removal(self, token: str) -> None:
        deadline = time.monotonic() + 1
        while self.store.get(token) is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNone(self.store.get(token))

    def post(self, payload: dict[str, object]):
        request = urllib.request.Request(
            self.base + "/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as error:
            return error

    def test_render_and_full_download_removes_ram_ticket(self) -> None:
        response = self.post({"text": "Hello Viv", "mode": "human"})
        self.assertEqual(response.status, 201)
        ticket_url = self.base + json.loads(response.read())["download_url"]
        audio = urllib.request.urlopen(ticket_url, timeout=3)
        self.assertEqual(audio.status, 200)
        self.assertEqual(audio.read(), b"RIFF-test-wav")
        self.assertEqual(self.render_calls, [("Hello Viv", "human")])
        self.assertEqual(self.gate_calls, 1)
        with self.assertRaises(urllib.error.HTTPError) as expired:
            urllib.request.urlopen(ticket_url, timeout=3)
        self.assertEqual(expired.exception.code, 404)

    def test_range_download_keeps_ticket_until_final_bytes(self) -> None:
        token = self.store.create(b"0123456789", "logic")
        ticket_url = f"{self.base}/download/{token}"
        first = urllib.request.Request(ticket_url, headers={"Range": "bytes=0-3"})
        first_response = urllib.request.urlopen(first, timeout=3)
        self.assertEqual(first_response.status, 206)
        self.assertEqual(first_response.read(), b"0123")
        self.assertIsNotNone(self.store.get(token))
        remainder = urllib.request.Request(ticket_url, headers={"Range": "bytes=4-"})
        final_response = urllib.request.urlopen(remainder, timeout=3)
        self.assertEqual(final_response.read(), b"456789")
        self.wait_for_ticket_removal(token)

    def test_last_range_first_does_not_delete_missing_prefix(self) -> None:
        token = self.store.create(b"0123456789", "logic")
        ticket_url = f"{self.base}/download/{token}"
        suffix = urllib.request.Request(ticket_url, headers={"Range": "bytes=5-"})
        self.assertEqual(urllib.request.urlopen(suffix, timeout=3).read(), b"56789")
        self.assertIsNotNone(self.store.get(token))
        prefix = urllib.request.Request(ticket_url, headers={"Range": "bytes=0-4"})
        self.assertEqual(urllib.request.urlopen(prefix, timeout=3).read(), b"01234")
        self.wait_for_ticket_removal(token)

    def test_body_hold_prevents_tts_render(self) -> None:
        def held() -> None:
            raise RuntimeError("held")

        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        handler = make_handler(render=lambda *_: self.fail("TTS must not run"), body_gate=held)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        response = self.post({"text": "Hello Viv", "mode": "human"})
        self.assertEqual(response.status, 503)

    def test_input_limit_rejects_before_body_gate(self) -> None:
        response = self.post({"text": "x" * (MAX_TEXT_CHARS + 1), "mode": "human"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.gate_calls, 0)
        self.assertEqual(self.render_calls, [])

    def test_rejects_non_loopback_host_header(self) -> None:
        request = urllib.request.Request(self.base + "/", headers={"Host": "attacker.example"})
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(rejected.exception.code, 403)

    def test_ticket_expiry_is_enforced_on_lookup(self) -> None:
        now = [0.0]
        store = RamTicketStore(clock=lambda: now[0])
        token = store.create(b"wav", "human")
        now[0] = 24 * 60 * 60 + 1
        self.assertIsNone(store.get(token))
        store.clear()


if __name__ == "__main__":
    unittest.main()
