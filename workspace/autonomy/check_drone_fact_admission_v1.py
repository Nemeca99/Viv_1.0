"""Independent bounded admission contract check; no persistent database writes."""
import importlib.util
from pathlib import Path


def main():
    path = Path(__file__).with_name('drone_fact_admission_v1.py')
    spec = importlib.util.spec_from_file_location('candidate', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    admit = module.admit_fact
    calls = []
    def verify(receipt):
        calls.append('verify')
        return True
    def authorize():
        calls.append('authorize')
        return True
    import hashlib
    result = admit(' fact ', 'A' * 64, 'receipt', authorize, verify)
    assert result == ('fact', 'a' * 64, hashlib.sha256(b'receipt').hexdigest())
    assert calls == ['verify', 'authorize']
    cases = [('', 'a'*64, 'r'), ('  ', 'a'*64, 'r'),
             (None, 'a'*64, 'r'), ('x', 'g'*64, 'r'),
             ('x', 'a'*63, 'r'), ('x', None, 'r'), ('x', 'a'*64, None)]
    for args in cases:
        calls.clear()
        try:
            admit(*args, authorize, verify)
        except (ValueError, PermissionError):
            pass
        else:
            raise AssertionError('invalid input accepted')
        assert calls == [], 'callback ran before input validation'
    def explode(*args):
        raise RuntimeError('callback failed')
    for callback in [lambda *args: False, lambda *args: 1, lambda *args: None, explode]:
        for auth, verifier in [(authorize, callback), (callback, verify)]:
            try:
                admit('fact', 'a'*64, 'receipt', auth, verifier)
            except (ValueError, PermissionError):
                pass
            else:
                raise AssertionError('callback denial accepted')
    print('PASS: admission validation, callback order, strict True, exceptions')


if __name__ == '__main__':
    main()
