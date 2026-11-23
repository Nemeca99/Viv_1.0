import copy
import sys
import tempfile
import unittest
import json
from unittest.mock import patch, Mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'INN'))
import torch
from inn.engine import DEFAULT_CONFIG
from inn.language import ByteTokenizer, LanguageEngine


class NeuralINNTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.engine = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), seed=42)

    def test_byte_roundtrip(self):
        text = 'water → harvest'
        self.assertEqual(ByteTokenizer.decode(ByteTokenizer.encode(text)), text)

    def test_future_tokens_cannot_change_prefix(self):
        with torch.no_grad():
            first = self.engine.model.language(torch.tensor([[257, 65, 66, 67]]))
            second = self.engine.model.language(torch.tensor([[257, 65, 90, 91]]))
        torch.testing.assert_close(first[:, :2], second[:, :2], rtol=0, atol=0)

    def test_shared_attention_receives_language_gradient(self):
        before = self.engine.model.blocks[0].qkv.weight.detach().clone()
        self.engine.train_joint([{'prompt': 'tool=TILL\n', 'target': 'TILL is legal.'}], [])
        self.assertFalse(torch.equal(before, self.engine.model.blocks[0].qkv.weight))

    def test_counterfactual_coverage_counts_only_measured_improvement_targets(self):
        from autonomy.train_neural_inn import center_counterfactual_scores, counterfactual_coverage
        context = [
            {'t': 'TILL', 'a': 7, 'b': 0, 'stage': 'BARREN', 'x': 0.25},
            {'t': 'SEED', 'a': 7, 'b': 0, 'stage': 'BARREN', 'x': 0.5},
        ]
        coverage = counterfactual_coverage([
            {'items': context, 'oracle_horizon': 12, 'oracle_improved': True, 'best': 1,
             'counterfactual_score_deltas': [0, 1], 'counterfactual_score_advantages': [0, 1],
             'counterfactual_score_trials': [[0, 0, 1], [0, 0, 0]]},
            {'items': context, 'oracle_horizon': 12, 'oracle_improved': False, 'best': 0,
             'counterfactual_score_deltas': [-1, 0], 'counterfactual_score_advantages': [0, -1],
             'counterfactual_score_trials': [[0, 0, -1], [0, 0, 0]]},
            {'items': context, 'oracle_horizon': 0, 'oracle_improved': False, 'best': 0,
             'counterfactual_score_deltas': [5, 5], 'counterfactual_score_advantages': [5, 5],
             'counterfactual_score_trials': [[5, 5, 5], [5, 5, 5]]},
        ])
        self.assertEqual(coverage['total_action_samples'], 3)
        self.assertEqual(coverage['measured_counterfactual_samples'], 2)
        self.assertEqual(coverage['oracle_improved_samples'], 1)
        self.assertEqual(coverage['unique_model_contexts'], 1)
        self.assertEqual(coverage['improved_targets_by_tool'], {'SEED': 1})
        self.assertEqual(coverage['horizon_samples'], {'12': 2})
        self.assertEqual(coverage['measured_action_outcomes'], 4)
        self.assertEqual(coverage['measured_rollout_evaluations'], 12)
        self.assertEqual(coverage['score_delta_outcomes'], {'negative': 1, 'neutral': 2, 'positive': 1})
        self.assertEqual(coverage['trial_score_delta_outcomes'],
                         {'negative': 1, 'neutral': 10, 'positive': 1})
        self.assertEqual(coverage['parent_relative_advantages'],
                         {'negative': 1, 'neutral': 2, 'positive': 1})
        self.assertEqual(center_counterfactual_scores([(1, 3.0, 0.0), (1, 1.0, 0.0)], 0), [0.0, -2.0])

    def test_counterfactual_advantages_rank_values_and_keep_parent_anchor(self):
        from inn.language import counterfactual_rank_loss
        better_ranked = counterfactual_rank_loss(torch.tensor([2.0, 0.0]), [1.0, 0.0], [1, 1])
        worse_ranked = counterfactual_rank_loss(torch.tensor([0.0, 2.0]), [1.0, 0.0], [1, 1])
        self.assertLess(float(better_ranked), float(worse_ranked))
        context = [
            {'t': 'TILL', 'a': 1, 'b': 0, 'stage': 'BARREN', 'x': [0.25] * 5},
            {'t': 'IDLE', 'a': 0, 'b': 0, 'stage': 'GLOBAL', 'x': [0.5] * 5},
        ]
        example = [{'prompt': 'tool=TILL\n', 'target': 'TILL is legal on BARREN.'}]

        def action_loss(scores):
            engine = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), seed=42)
            torch.manual_seed(123)
            result = engine.train_joint(example, [{
                'items': context,
                'legal': [1, 1],
                'best': 0,
                'oracle_improved': False,
                'parent_raw': [0.0, 0.0],
                'counterfactual_score_advantages': scores,
            }])
            self.assertEqual(engine.optimizer_steps, 1)
            return result['action_loss']

        self.assertGreater(action_loss([1.0, 0.0]), action_loss([0.0, 0.0]))

    def test_checkpoint_restores_generation_and_optimizer(self):
        example = {'prompt': 'tool=TILL\n', 'target': 'TILL is legal.'}
        self.engine.train_joint([example], [])
        text = self.engine.speak(example['prompt'], max_new=8)
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'engine.pt'
            self.engine.save(file)
            restored = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), seed=99)
            restored.load(file)
            self.assertEqual(restored.speak(example['prompt'], max_new=8), text)
            self.assertEqual(restored.optimizer_steps, 1)
            self.engine.train_joint([example], [])
            restored.train_joint([example], [])
            for a, b in zip(self.engine.model.parameters(), restored.model.parameters()):
                torch.testing.assert_close(a, b, rtol=0, atol=0)

    def test_zero_volume_language_remains_causal_and_finite(self):
        logits = self.engine.model.language(torch.tensor([[257, 65, 66]]), volume=0.)
        self.assertTrue(torch.isfinite(logits).all())

    def test_hive_proposal_text_comes_from_admitted_neural_model(self):
        from autonomy import inn_hive as coupling
        from inn.farm import Farm
        class Store:
            def get(self, key, default=None):
                return default
            def event(self, *args):
                pass
            def set(self, *args):
                pass
        policy = json.loads((Path(__file__).parent / 'autonomy/learning/verified_recovery_policy.json').read_text())
        with Farm() as farm:
            state = farm.call('state')
        state.update(config=copy.deepcopy(DEFAULT_CONFIG), **policy['engine'])
        state['candidate_engine'] = copy.deepcopy(policy['engine'])
        state['distillation'] = {'lessons': 1}
        state['behavioral_admission'] = {'accepted': True, 'improved': False}
        seen = []
        def ask(messages, json_mode=False):
            request = json.loads(messages[-1]['content'])
            seen.append(request)
            return json.dumps({'candidate_id': request['inn_drone_proposal']['candidate_id'],
                               'response_to_drone': 'Verified your neural proposal.', 'rationale': 'Rust checks the action.'})
        # Use a real own NN with a verified proposal fixture. Its inference is still neural.
        neural = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), policy['engine'])
        shadow = {'admitted': True, 'offline_gate_passed': True, 'text_exact': True,
                  'rust_legal': True, 'generated_text': 'TILL is legal on BARREN.',
                  'checkpoint_sha256': 'fixture', 'mode': 'shadow_only'}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / 'state.json'
            state_path.write_text(json.dumps(state))
            (root / 'autonomy/learning').mkdir(parents=True)
            with patch.object(coupling, 'STATE_PATH', state_path), \
                 patch.object(coupling, 'EXPERIENCE_PATH', root/'experience.jsonl'), \
                 patch.object(coupling, 'WORKSPACE', root), \
                 patch.object(coupling, '_NEURAL_CACHE', ('fixture', neural)), \
                 patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                       return_value={'allowed': True}), \
                 patch.object(coupling, '_neural_shadow', return_value=shadow):
                result = coupling.run_farm_learning_cycle(Store(), ask)
            self.assertEqual(seen[0]['inn_drone_proposal']['message'], shadow['generated_text'])
            self.assertEqual(result['inn_proposal_source'], 'own_neural_inn')
            self.assertEqual(result['distillation_lesson']['student'], 'legacy_farm_candidate')
            self.assertEqual(result['neural_shadow']['mode'], 'admitted_drone_proposal')

    def test_failed_neural_proposal_uses_explicit_legacy_fallback(self):
        from autonomy.inn_hive import _neural_proposal_admitted
        # Admission requires all three facts, not just a pointer marked passed.
        for shadow in ({'admitted': False, 'offline_gate_passed': True, 'text_exact': True, 'rust_legal': True},
                       {'admitted': True, 'offline_gate_passed': True, 'text_exact': False, 'rust_legal': True}):
            self.assertFalse(_neural_proposal_admitted(shadow))

    def test_neural_shadow_records_body_hold_without_loading_checkpoint(self):
        from autonomy import inn_hive as coupling
        class Store:
            def __init__(self):
                self.events = []
            def event(self, kind, data):
                self.events.append((kind, data))
        store = Store()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            learning = root / 'autonomy/learning'
            learning.mkdir(parents=True)
            (learning / 'neural_admitted.json').write_text('{}')
            with patch.object(coupling, 'WORKSPACE', root), \
                 patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                       return_value={'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                                     'reasons': ['cpu_temperature_at_or_above_limit']}):
                result = coupling._neural_shadow([], [], store)
        self.assertEqual(result['mode'], 'body_held')
        self.assertEqual(store.events[0][0], 'inn_neural_inference_held')

    def test_failed_candidate_diagnostic_holds_before_loading_checkpoints(self):
        from autonomy import diagnose_failed_neural_candidate as diagnostic
        from autonomy import train_neural_inn as trainer
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        with patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                   return_value={'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                                 'authority': 'deterministic_aios_body_rust',
                                 'reasons': ['privacy_core_unverified']}), \
                patch.object(trainer, '_load_training_stack') as load_training_stack:
            with self.assertRaises(BodyRuntimeHold):
                diagnostic.main()
            load_training_stack.assert_not_called()

    def test_language_probe_checks_body_guard_before_each_generation(self):
        from autonomy.train_neural_inn import language_probe
        class Guard:
            def __init__(self):
                self.checks = 0
            def check(self):
                self.checks += 1
        class Engine:
            def speak(self, prompt):
                return prompt
        examples = [{'prompt': 'first', 'target': 'first'},
                    {'prompt': 'second', 'target': 'second'}]
        guard = Guard()
        result = language_probe(Engine(), examples, guard)
        self.assertEqual(result['exact'], 2)
        self.assertEqual(guard.checks, 2)

    def test_candidate_body_gate_evidence_is_persisted_without_lease_permit(self):
        from autonomy.train_neural_inn import persist_body_gate
        class Lease:
            def __init__(self):
                self.run_id = 'candidate-run'
                self.writes = []
            def write_json(self, path, value):
                self.writes.append((Path(path), value))
        lease = Lease()
        verdict = {'allowed': True, 'disposition': 'ALLOW_MIND_RUNTIME',
                   'authority': 'deterministic_aios_body_rust',
                   'schema': 'aios_mind_runtime_gate_v1', 'gate': 'rust',
                   'execution_boundary': 'wsl_docker', 'body_image': 'sha256:fixture',
                   'stability_sn': 0.8, 'requested_threads': 2,
                   'body_runtime_permit': 'secret-permit'}
        persist_body_gate(lease, Path('run'), verdict)
        self.assertEqual(lease.writes, [(Path('run/body_gate.json'), {
            'allowed': True, 'disposition': 'ALLOW_MIND_RUNTIME',
            'authority': 'deterministic_aios_body_rust', 'requested_threads': 2,
            'schema': 'aios_mind_runtime_gate_v1', 'gate': 'rust',
            'execution_boundary': 'wsl_docker', 'body_image': 'sha256:fixture',
            'stability_sn': 0.8, 'candidate_run_id': lease.run_id})])
        self.assertEqual(verdict['body_runtime_permit'], 'secret-permit')

    def test_scheduler_launches_one_bounded_cpu_job(self):
        from autonomy import inn_hive as coupling
        class Store:
            def __init__(self):
                self.values = {}
                self.events = []
            def get(self, key, default=None):
                return self.values.get(key, default)
            def set(self, key, value):
                self.values[key] = value
            def event(self, kind, data):
                self.events.append((kind, data))
        store = Store()
        store.values['neural_training_last_lesson'] = 0
        process = Mock(pid=123, poll=Mock(return_value=None))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            learning = root / 'autonomy/learning'
            learning.mkdir(parents=True)
            (learning / 'neural_admitted.json').write_text('{}')
            with patch.object(coupling, 'WORKSPACE', root), \
                 patch.object(coupling, '_NEURAL_TRAINER', None), \
                 patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                       return_value={'allowed': True}), \
                 patch.object(coupling.subprocess, 'Popen', return_value=process) as launch:
                coupling._schedule_neural_training(store, 249)
                launch.assert_not_called()
                coupling._schedule_neural_training(store, 250)
                coupling._schedule_neural_training(store, 250)
                launch.assert_called_once()
                command = launch.call_args.args[0]
                self.assertEqual(command[0], r'L:\.venv\Scripts\python.exe')
                self.assertEqual(command[-7:], ['--updates', '500', '--collect-steps', '1200', '--threads', '2',
                                                 '--voice-progress'])
                self.assertEqual(launch.call_args.kwargs['env']['OMP_NUM_THREADS'], '2')
                self.assertEqual(store.values['neural_training_last_lesson'], 250)

    def test_scheduler_records_body_hold_without_launching_training(self):
        from autonomy import inn_hive as coupling
        class Store:
            def __init__(self):
                self.values = {'neural_training_last_lesson': 0}
                self.events = []
            def get(self, key, default=None):
                return self.values.get(key, default)
            def set(self, key, value):
                self.values[key] = value
            def event(self, kind, data):
                self.events.append((kind, data))
        store = Store()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            learning = root / 'autonomy/learning'
            learning.mkdir(parents=True)
            (learning / 'neural_admitted.json').write_text('{}')
            with patch.object(coupling, 'WORKSPACE', root), \
                 patch.object(coupling, '_NEURAL_TRAINER', None), \
                 patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                       return_value={'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                                     'reasons': ['ram_at_or_above_limit']}), \
                 patch.object(coupling.subprocess, 'Popen') as launch:
                coupling._schedule_neural_training(store, 250)
        launch.assert_not_called()
        self.assertEqual(store.values['neural_training_last_hold_lesson'], 250)
        self.assertEqual(store.events[0][0], 'inn_neural_training_held')

    def test_real_hive_settings_default_preserves_explicit_false(self):
        from viv_autonomy import Store
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            self.assertTrue(store.get('neural_training_enabled', True))
            self.assertIsNone(store.get('missing'))
            store.set('neural_training_enabled', False)
            self.assertFalse(store.get('neural_training_enabled', True))

    def test_farm_failure_changes_retention_only_for_same_parent(self):
        from autonomy.train_neural_inn import retention_after_failure
        previous = {'receipt': {'passed': False, 'farm_retained': False,
                    'protocol': {'parent_checkpoint_sha256': 'parent-a', 'retention_weight': .1}}}
        self.assertEqual(retention_after_failure(previous, 'parent-a'), .2)
        self.assertEqual(retention_after_failure(previous, 'parent-b'), .1)

    def test_neural_candidate_admission_requires_explicit_flag(self):
        from autonomy.train_neural_inn import verifier_command
        self.assertNotIn('--admit', verifier_command())
        self.assertEqual(verifier_command(admit=True)[-1], '--admit')

    def test_training_exits_with_body_hold_before_candidate_work(self):
        from autonomy import train_neural_inn as trainer
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from aios_rebuild.privacy_core.privacy_core import PrivacyCore
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            learning = root / 'learning'
            learning.mkdir(parents=True)
            status = learning / 'neural_status.json'
            status.write_text(json.dumps({'stage': 'previous_complete'}))
            candidate_pointer = learning / 'neural_candidate.json'
            candidate_pointer.write_text(json.dumps({'run': 'previous-candidate'}))
            receipt_root = root / 'privacy-memory' / 'body_gate_holds'
            privacy = PrivacyCore.__new__(PrivacyCore)
            privacy.config = {
                'file_write_boundary': {
                    'allowed_directories': [str(root / 'privacy-memory')],
                    'blocked_extensions': ['.exe', '.bat', '.sh'],
                },
            }
            with patch.object(trainer, 'LEARNING', learning), \
                 patch.object(trainer, 'STATUS', status), \
                 patch.object(trainer, 'BODY_HOLD_RECEIPT_ROOT', receipt_root), \
                 patch.object(trainer, 'PrivacyCore', return_value=privacy), \
                 patch.object(sys, 'argv', ['train_neural_inn.py', '--threads', '2', '--voice-progress']), \
                 patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                       return_value={'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                                     'reasons': ['core_health_unverified:privacy_core']}), \
                 patch.object(trainer, '_load_training_stack') as load_training_stack, \
                 patch.object(trainer.InnCandidateLease, 'begin') as candidate_lease_begin, \
                 patch.object(trainer, 'VoiceProgress') as voice_progress:
                with self.assertRaises(BodyRuntimeHold):
                    trainer.main()
                load_training_stack.assert_not_called()
                voice_progress.assert_not_called()
                candidate_lease_begin.assert_not_called()
            self.assertEqual(json.loads(status.read_text()), {'stage': 'previous_complete'})
            self.assertFalse((learning / 'neural_runs').exists())
            receipts = list(receipt_root.glob('*.json'))
            self.assertEqual(len(receipts), 1)
            record = json.loads(receipts[0].read_text())
            self.assertEqual(record['stage'], 'body_held')
            self.assertFalse(record['active_policy_changed'])
            self.assertEqual(record['body_gate']['reasons'], ['core_health_unverified:privacy_core'])
            self.assertEqual(json.loads(candidate_pointer.read_text()), {'run': 'previous-candidate'})

    def test_reverification_hold_writes_receipt_without_admission(self):
        from autonomy import verify_neural_inn as verifier
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        with tempfile.TemporaryDirectory() as folder:
            learning = Path(folder) / 'learning'
            run = learning / 'run'
            run.mkdir(parents=True)
            pointer = {'run': str(run)}
            (learning / 'neural_candidate.json').write_text(json.dumps(pointer))
            def record_receipt(target, candidate, receipt, stability_sn):
                (target / 'recheck.json').write_text(json.dumps(receipt))
            with patch.object(verifier, 'LEARNING', learning), \
                 patch.object(verifier, '_main', side_effect=BodyRuntimeHold(
                     {'allowed': False, 'reasons': ['ram_at_or_above_limit']})), \
                 patch.object(verifier, 'write_verification_receipt', side_effect=record_receipt) as write_receipt:
                with self.assertRaises(BodyRuntimeHold):
                    verifier.main()
                write_receipt.assert_called_once()
            record = json.loads((run / 'recheck.json').read_text())
            self.assertTrue(record['body_held'])
            self.assertFalse(record['admitted_proposals'])

    def test_verifier_does_not_load_neural_stack_when_body_holds(self):
        from autonomy import train_neural_inn as trainer
        from autonomy import verify_neural_inn as verifier
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(verifier, 'LEARNING', Path(folder)), \
                    patch.object(sys, 'argv', ['verify_neural_inn.py']), \
                    patch('aios_rebuild.main_core.mind_runtime_gate.query_body_gate',
                          return_value={'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                                        'reasons': ['privacy_core_unverified']}), \
                    patch.object(trainer, '_load_training_stack') as load_training_stack:
                with self.assertRaises(BodyRuntimeHold):
                    verifier.main()
                load_training_stack.assert_not_called()

    def test_action_sampler_balances_plot_identity_groups(self):
        from autonomy.train_neural_inn import action_identity_group, action_sampling_weights
        samples = [
            {'items': [{'a': 1}, {'a': 1}, {'a': 0}]} for _ in range(3)
        ] + [
            {'items': [{'a': 2}, {'a': 0}]},
            {'items': [{'a': 1}, {'a': 2}, {'a': 0}]},
        ]
        weights = action_sampling_weights(samples)
        self.assertEqual(action_identity_group(samples[0]), (1,))
        self.assertEqual(action_identity_group(samples[-1]), (1, 2))
        self.assertAlmostEqual(sum(weights[:3]), 1.0)
        self.assertAlmostEqual(weights[3], 1.0)
        self.assertAlmostEqual(weights[4], 1.0)

    def test_failed_candidate_trace_finds_first_action_divergence(self):
        from autonomy.diagnose_failed_neural_candidate import first_action_divergence
        parent = [
            {'step': 1, 'action': {'t': 'TILL', 'a': 21, 'b': 0}, 'outcome': {'executed': True}, 'state': {'decays': 0}},
            {'step': 2, 'action': {'t': 'SEED', 'a': 21, 'b': 0}, 'outcome': {'executed': True}, 'state': {'decays': 0}},
        ]
        candidate = [
            {'step': 1, 'action': {'t': 'TILL', 'a': 21, 'b': 0}, 'outcome': {'executed': True}, 'state': {'decays': 0}},
            {'step': 2, 'action': {'t': 'WATER', 'a': 21, 'b': 0}, 'outcome': {'executed': False}, 'state': {'decays': 1}},
        ]
        result = first_action_divergence(parent, candidate)
        self.assertEqual(result['action_identity_differences'], 1)
        self.assertEqual(result['first_divergence']['step'], 2)
        self.assertEqual(result['first_outcome_divergence']['step'], 2)
        self.assertEqual(result['first_state_divergence']['candidate_state']['decays'], 1)

    def test_uml_neural_gate_protects_neurons_against_zero_and_nan_gradients(self):
        from inn.uml_neural_gate import (
            uml_safe_scalar_div,
            uml_safe_tensor_div,
            uml_clip_and_stabilize_gradients,
        )
        # 1. Scalar 0/0 -> <!0, !0> = 1.0 ceiling snap
        val, tag = uml_safe_scalar_div(0.0, 0.0)
        self.assertEqual(val, 1.0)
        self.assertEqual(tag, "!0 (Singularity Bounded)")
        # 2. Scalar x/0 -> <!0, 0> = 0.0 floor
        val_floor, tag_floor = uml_safe_scalar_div(0.5, 0.0)
        self.assertEqual(val_floor, 0.0)
        self.assertEqual(tag_floor, "Zero Division Floor")
        # 3. Autograd tensor division across [0/0, 5/0, 6/2]
        num = torch.tensor([0.0, 5.0, 6.0], requires_grad=True)
        den = torch.tensor([0.0, 0.0, 2.0], requires_grad=True)
        out = uml_safe_tensor_div(num, den)
        torch.testing.assert_close(out, torch.tensor([1.0, 0.0, 3.0]))
        out.sum().backward()
        self.assertTrue(torch.isfinite(num.grad).all())
        self.assertTrue(torch.isfinite(den.grad).all())
        # 4. Inject NaN gradient into INNTransformer neurons and verify UML sanitizer recovers
        for p in self.engine.model.parameters():
            p.grad = torch.zeros_like(p)
        first_param = next(self.engine.model.parameters())
        first_param.grad.view(-1)[0] = float('nan')
        first_param.grad.view(-1)[1] = float('inf')
        telemetry = uml_clip_and_stabilize_gradients(self.engine.model.parameters(), max_norm=1.0, loss_value=0.0)
        self.assertEqual(telemetry['sanitized_elements'], 2)
        self.assertEqual(telemetry['state_tag'], "!0 (Singularity Bounded)")
        for p in self.engine.model.parameters():
            self.assertTrue(torch.isfinite(p.grad).all())


if __name__ == '__main__':
    unittest.main()
