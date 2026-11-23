import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from autonomy.farm_gpu_phase import gpu_training_phase


class AllowingBodyGuard:
    def check(self, *, force=False):
        return {"allowed": True, "force": force}


class FarmGpuPhaseTests(unittest.TestCase):
    def test_child_timeout_stops_launcher_tree_before_returning(self):
        import subprocess
        from autonomy.farm_gpu_phase import run_gpu_child
        process = Mock(pid=8675309)
        process.wait.side_effect = [subprocess.TimeoutExpired(['trainer'], 1), 0]
        process.poll.return_value = None
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=AllowingBodyGuard()), \
             patch('autonomy.farm_gpu_phase.time.monotonic', side_effect=[0.0, 0.0, 1.1]), \
             patch('autonomy.farm_gpu_phase.subprocess.Popen', return_value=process), \
             patch('autonomy.farm_gpu_phase.subprocess.run') as kill:
            with self.assertRaises(subprocess.TimeoutExpired):
                run_gpu_child(['trainer'], cwd='L:/LocalCoder/workspace', timeout=1)
            self.assertEqual(kill.call_args.args[0], ['taskkill', '/PID', '8675309', '/T', '/F'])
            self.assertEqual(process.wait.call_count, 2)

    def test_body_hold_prevents_gpu_child_launch(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        guard = Mock()
        guard.check.side_effect = BodyRuntimeHold({"allowed": False})
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=guard), \
             patch('autonomy.farm_gpu_phase.subprocess.Popen') as popen:
            with self.assertRaises(BodyRuntimeHold):
                from autonomy.farm_gpu_phase import run_gpu_child
                run_gpu_child(['trainer'], cwd='L:/LocalCoder/workspace', timeout=1)
        popen.assert_not_called()

    def test_body_withdrawal_terminates_gpu_child_tree(self):
        import subprocess
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from autonomy.farm_gpu_phase import run_gpu_child
        guard = Mock()
        guard.check.side_effect = [None, BodyRuntimeHold({"allowed": False})]
        process = Mock(pid=8675309)
        process.poll.return_value = None
        process.wait.return_value = 0
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=guard), \
             patch('autonomy.farm_gpu_phase.subprocess.Popen', return_value=process), \
             patch('autonomy.farm_gpu_phase.subprocess.run') as kill:
            with self.assertRaises(BodyRuntimeHold):
                run_gpu_child(['trainer'], cwd='L:/LocalCoder/workspace', timeout=10)
        self.assertEqual(kill.call_args.args[0], ['taskkill', '/PID', '8675309', '/T', '/F'])
        process.wait.assert_called_once_with(timeout=30)

    def phase(self, body_fails=False, resume_farm=True):
        store = Mock()
        body_guard = AllowingBodyGuard()
        saved = {'enabled': True, 'worker_mode': 'farm_continuous'}
        store.get.side_effect = lambda key: saved.get(key)
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=body_guard), \
             patch('autonomy.farm_gpu_phase.Store', return_value=store), \
             patch('autonomy.farm_gpu_phase.file_lock', side_effect=lambda *a, **k: nullcontext()), \
             patch('autonomy.farm_gpu_phase.worker_alive', return_value=False), \
             patch('autonomy.farm_gpu_phase.start_worker') as start, \
             patch('autonomy.farm_gpu_phase.ollama', side_effect=[{'models': []}, {}, {'models': []}, {}]) as ollama:
            if body_fails:
                with self.assertRaisesRegex(RuntimeError, 'failed optimizer'):
                    with gpu_training_phase(resume_farm=True) if resume_farm else gpu_training_phase():
                        raise RuntimeError('failed optimizer')
            else:
                with gpu_training_phase(resume_farm=True) if resume_farm else gpu_training_phase():
                    pass
            store.set.assert_any_call('enabled', False)
            store.set.assert_any_call('gpu_training_active', True)
            store.set.assert_any_call('gpu_training_active', False)
            store.set.assert_any_call('worker_mode', 'farm_continuous')
            if resume_farm:
                store.set.assert_any_call('enabled', True)
                start.assert_called_once()
                self.assertEqual(ollama.call_args_list[-1].args[1]['keep_alive'], '30m')
            else:
                self.assertNotIn(unittest.mock.call('enabled', True), store.set.call_args_list)
                start.assert_not_called()
                self.assertEqual(ollama.call_count, 3)
                phase = [call.args[1] for call in store.set.call_args_list if call.args[0] == 'farm_gpu_phase'][-1]
                self.assertEqual(phase['stage'], 'paused')

    def test_body_hold_prevents_phase_side_effects(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        guard = Mock()
        guard.check.side_effect = BodyRuntimeHold({"allowed": False})
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=guard), \
             patch('autonomy.farm_gpu_phase.Store') as store:
            with self.assertRaises(BodyRuntimeHold):
                with gpu_training_phase():
                    self.fail('held Body must not start the phase')
        store.assert_not_called()

    def test_body_hold_during_restore_keeps_farm_paused(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        store = Mock()
        store.get.side_effect = lambda key: {
            'enabled': True,
            'worker_mode': 'farm_continuous',
        }.get(key)
        guard = Mock()
        guard.check.side_effect = [None, None, None, BodyRuntimeHold({"allowed": False})]
        with patch('autonomy.farm_gpu_phase._body_runtime_guard', return_value=guard), \
             patch('autonomy.farm_gpu_phase.Store', return_value=store), \
             patch('autonomy.farm_gpu_phase.file_lock', side_effect=lambda *a, **k: nullcontext()), \
             patch('autonomy.farm_gpu_phase.worker_alive', return_value=False), \
             patch('autonomy.farm_gpu_phase.ollama', side_effect=[{'models': []}, {}, {'models': []}]), \
             patch('autonomy.farm_gpu_phase.start_worker') as start:
            with gpu_training_phase(resume_farm=True):
                pass
        store.set.assert_any_call('enabled', False)
        self.assertNotIn(unittest.mock.call('enabled', True), store.set.call_args_list)
        start.assert_not_called()
        phase = [call.args[1] for call in store.set.call_args_list
                 if call.args[0] == 'farm_gpu_phase'][-1]
        self.assertEqual(phase['stage'], 'restore_error')

    def test_ollama_requests_use_the_shared_body_and_privacy_gate(self):
        from contextlib import nullcontext
        from io import BytesIO
        from autonomy.farm_gpu_phase import ollama
        response = BytesIO(b'{"models":[]}')
        with patch('aios_rebuild.main_core.mind_runtime_gate.open_authorized_model_request',
                   return_value=nullcontext(response)) as authorized:
            self.assertEqual(ollama('ps'), {'models': []})
        request = authorized.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/ps')
        self.assertEqual(authorized.call_args.kwargs, {'timeout': 60, 'requested_threads': 2})

    def test_ollama_body_hold_prevents_direct_network_request(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from autonomy.farm_gpu_phase import ollama
        hold = BodyRuntimeHold({'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME'})
        with patch('aios_rebuild.main_core.mind_runtime_gate.open_authorized_model_request',
                   side_effect=hold) as authorized:
            with self.assertRaises(BodyRuntimeHold):
                ollama('ps')
        authorized.assert_called_once()

    def test_farm_evaluation_worker_checks_body_before_torch_runtime_setup(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from autonomy import evaluate_farm_adapter
        guard = Mock()
        guard.check.side_effect = BodyRuntimeHold({'allowed': False})
        with patch.object(evaluate_farm_adapter, '_body_runtime_guard', return_value=guard), \
             patch.object(evaluate_farm_adapter, '_load_model_stack') as load_model_stack:
            with self.assertRaises(BodyRuntimeHold):
                evaluate_farm_adapter.main()
        load_model_stack.assert_not_called()

    def test_bounded_phase_leaves_farm_paused(self):
        self.phase(resume_farm=False)

    def test_bounded_phase_failure_leaves_farm_paused(self):
        self.phase(body_fails=True, resume_farm=False)

    def test_restores_after_success(self):
        self.phase()

    def test_restores_after_training_failure(self):
        self.phase(body_fails=True)

    def test_inference_refuses_gpu_training_phase(self):
        from viv_autonomy import ask_model
        with patch('viv_autonomy.Store') as store:
            store.return_value.get.return_value = True
            with self.assertRaisesRegex(RuntimeError, 'paused'):
                ask_model([{'role': 'user', 'content': 'hello'}])
