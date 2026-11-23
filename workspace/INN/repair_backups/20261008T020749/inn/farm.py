import ctypes
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Farm:
    """Persistent in-process Rust farm; no subprocess or disk I/O per tick."""

    def __init__(self, state=None):
        self.dll = ctypes.CDLL(str(ROOT / 'farm_rust/target/release/inn_farm.dll'))
        self.dll.farm_new.restype = ctypes.c_void_p
        self.dll.farm_drop.argtypes = [ctypes.c_void_p]
        self.dll.farm_request.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.dll.farm_request.restype = ctypes.c_void_p
        self.dll.farm_free.argtypes = [ctypes.c_void_p]
        self.handle = self.dll.farm_new()
        if state is not None:
            self.call('load', state=state)

    def call(self, op, **kwargs):
        request = json.dumps(dict(op=op, **kwargs), allow_nan=False).encode()
        ptr = self.dll.farm_request(self.handle, request)
        try:
            answer = json.loads(ctypes.string_at(ptr))
        finally:
            self.dll.farm_free(ptr)
        if 'error' in answer:
            raise RuntimeError(answer['error'])
        return answer['result']

    def close(self):
        if self.handle:
            self.dll.farm_drop(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
