import unittest
from unittest.mock import patch

from autonomy import inn_candidate_lease


class FakeRustCore:
    def __init__(self):
        self.requests = []

    def begin_training_lease(self, raw):
        import json
        request = json.loads(raw)
        self.requests.append(request)
        run_id = request['run_id']
        return {'allowed': True, 'lease_token': 'opaque-token',
                'staging_root': f'L:/LocalCoder/workspace/autonomy/learning/neural_candidate_staging/{run_id}',
                'final_root': f'L:/LocalCoder/workspace/autonomy/learning/neural_runs/{run_id}'}

    def commit_training_lease(self, token, raw):
        import json
        request = json.loads(raw)
        self.requests.append(request)
        return {'allowed': True, 'final_root': request['paths'][1]}

    def training_lease_active(self, token):
        return True

    def write_inn_candidate_artifact(self, token, relative_path, payload):
        self.requests.append({'token': token, 'relative_path': relative_path, 'payload': payload})

    def authorize_training(self, raw):
        import json
        request = json.loads(raw)
        self.requests.append(request)
        return {'allowed': True}

    def publish_inn_pointer(self, token, raw, payload):
        import json
        request = json.loads(raw)
        self.requests.append({**request, 'token': token, 'payload': json.loads(payload)})
        return {'allowed': True}

    def write_inn_candidate_receipt(self, raw, payload):
        import json
        request = json.loads(raw)
        self.requests.append({**request, 'payload': json.loads(payload)})
        return {'allowed': True}


class InnCandidateLeaseTests(unittest.TestCase):
    def test_candidate_artifacts_are_sent_to_rust_as_relative_create_only_writes(self):
        core = FakeRustCore()
        with patch.object(inn_candidate_lease, '_rust_core', return_value=core):
            lease = inn_candidate_lease.InnCandidateLease.begin('test-run', ['a' * 64], 1.0)
            lease.write_json(lease.stage_root / 'metrics' / 'training.json', {'step': 1})
        write = core.requests[-1]
        self.assertEqual(write['token'], 'opaque-token')
        self.assertEqual(write['relative_path'].replace('\\', '/'), 'metrics/training.json')
        self.assertEqual(write['payload'], b'{"step":1}\n')

    def test_begin_and_commit_use_bound_rust_lease_contract(self):
        core = FakeRustCore()
        with patch.object(inn_candidate_lease, '_rust_core', return_value=core):
            lease = inn_candidate_lease.InnCandidateLease.begin(
                'test-run', ['a' * 64], 1.0, 'body-permit', 2)
            final_root = lease.commit()
        self.assertEqual(final_root, lease.final_root)
        self.assertEqual([item['action'] for item in core.requests],
                         ['BEGIN_INN_CANDIDATE', 'COMMIT_INN_CANDIDATE'])
        self.assertEqual(core.requests[0]['paths'][0].split('/')[-1], 'test-run')
        self.assertEqual(core.requests[0]['body_runtime_permit'], 'body-permit')
        self.assertEqual(core.requests[0]['body_requested_threads'], 2)
        self.assertEqual(core.requests[1]['paths'][1].split('/')[-1], 'test-run')

    def test_pointer_adapter_rejects_admission_and_arbitrary_files(self):
        core = FakeRustCore()
        with patch.object(inn_candidate_lease, '_rust_core', return_value=core):
            lease = inn_candidate_lease.InnCandidateLease.begin('test-run', ['a' * 64], 1.0)
            with self.assertRaises(PermissionError):
                lease.authorize_pointer(inn_candidate_lease.WORKSPACE / 'autonomy/learning/neural_admitted.json')
            with self.assertRaises(PermissionError):
                lease.authorize_pointer(inn_candidate_lease.WORKSPACE / 'autonomy/learning/unlisted.json')
        self.assertEqual(len(core.requests), 1)

    def test_pointer_publication_uses_rust_writer_without_authorize_then_python_write(self):
        core = FakeRustCore()
        path = inn_candidate_lease.WORKSPACE / 'autonomy/learning/neural_status.json'
        value = {'run': 'L:/LocalCoder/workspace/autonomy/learning/neural_runs/test-run'}
        with patch.object(inn_candidate_lease, '_rust_core', return_value=core):
            lease = inn_candidate_lease.InnCandidateLease.begin('test-run', ['a' * 64], 1.0)
            lease.publish_pointer(path, value)
        self.assertEqual(core.requests[-1]['action'], 'PUBLISH_INN_POINTER')
        self.assertEqual(core.requests[-1]['payload'], value)
        self.assertEqual(sum('token' in request for request in core.requests), 1)

    def test_denied_begin_fails_closed(self):
        class DeniedCore(FakeRustCore):
            def begin_training_lease(self, raw):
                return {'allowed': False, 'rule': 'body_hold', 'reason': 'held'}

        with patch.object(inn_candidate_lease, '_rust_core', return_value=DeniedCore()):
            with self.assertRaises(PermissionError):
                inn_candidate_lease.InnCandidateLease.begin('test-run', ['a' * 64], 1.0)

    def test_runtime_guard_fails_when_rust_lease_expires(self):
        class ExpiredCore(FakeRustCore):
            def training_lease_active(self, token):
                return False

        with patch.object(inn_candidate_lease, '_rust_core', return_value=ExpiredCore()):
            lease = inn_candidate_lease.InnCandidateLease.begin('test-run', ['a' * 64], 1.0)
            with self.assertRaises(inn_candidate_lease.InnCandidateLeaseExpired):
                lease.assert_active()

    def test_runtime_guard_checks_body_before_lease_and_skips_after_commit(self):
        events = []

        class BodyGuard:
            last_verdict = {'allowed': True}

            def check(self, *, force=False):
                events.append('body')
                return self.last_verdict

        class Lease:
            committed = False

            def assert_active(self):
                events.append('lease')

        lease = Lease()
        guard = inn_candidate_lease.LeaseAwareRuntimeGuard(BodyGuard(), lease)
        guard.check(force=True)
        self.assertEqual(events, ['body', 'lease'])
        lease.committed = True
        guard.check(force=True)
        self.assertEqual(events, ['body', 'lease', 'body'])

    def test_verification_receipt_is_bound_to_candidate_hashes_and_exact_run_path(self):
        core = FakeRustCore()
        candidate = {'engine_sha256': 'a' * 64, 'evaluation_sha256': 'b' * 64}
        receipt = {'passed': False, 'original_gate_reproduced': True, 'checkpoint_unchanged': True}
        with patch.object(inn_candidate_lease, '_rust_core', return_value=core):
            inn_candidate_lease.write_verification_receipt(
                inn_candidate_lease.WORKSPACE / 'autonomy/learning/neural_runs/test-run',
                candidate, receipt, 0.8)
        request = core.requests[0]
        self.assertEqual(request['action'], 'WRITE_INN_CANDIDATE_RECEIPT')
        self.assertEqual(request['paths'], [
            'L:/LocalCoder/workspace/autonomy/learning/neural_runs/test-run/recheck.json'])
        self.assertEqual(request['source_hashes'], [candidate['engine_sha256'], candidate['evaluation_sha256']])
        self.assertEqual(request['payload'], receipt)


if __name__ == '__main__':
    unittest.main()
