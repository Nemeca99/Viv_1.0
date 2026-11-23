import copy
import json
import tempfile
import unittest
from pathlib import Path
from autonomy.farm_corpus import publish, verify
from autonomy.farm_adapter import base_preflight


class SharedFarmCorpusTests(unittest.TestCase):
    def setUp(self):
        self.fact = {'prompt': 'plot=2 stage=BARREN tool=SEED\nDescribe:\n',
                     'target': 'SEED is illegal on BARREN.',
                     'provenance': 'live Rust counterfactual', 'state_sha256': 'a' * 64}
        self.action = {'items': [{'t': 'SEED', 'a': 2, 'b': 0, 'stage': 'BARREN'}],
                       'legal': [0], 'best': 0, 'oracle_improved': False, 'oracle_horizon': 0}

    def test_two_views_share_facts_and_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = publish([self.fact, self.fact], [self.action], Path(temp))
            manifest = verify(folder)
            rows = [json.loads(line) for line in (folder / 'model_train.jsonl').read_text().splitlines()]
            self.assertEqual(manifest['language_facts'], 1)
            self.assertTrue(any(row['messages'][-1]['content'] == self.fact['target'] for row in rows))
            self.assertEqual(folder, publish([self.fact], [self.action], Path(temp)))

    def test_reserved_identity_rejected(self):
        for plot in (21, 41):
            with tempfile.TemporaryDirectory() as temp:
                fact = dict(self.fact, prompt=self.fact['prompt'].replace('plot=2 ', f'plot={plot} '))
                with self.assertRaises(ValueError):
                    publish([fact], [], Path(temp))

    def test_queen_prose_is_not_ground_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                publish([dict(self.fact, provenance='Queen said so')], [], Path(temp))

    def test_conflicting_labels_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                publish([self.fact, dict(self.fact, target='SEED is legal on BARREN.')], [], Path(temp))

    def test_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = publish([self.fact], [], Path(temp))
            (folder / 'model_train.jsonl').write_text('{}\n')
            with self.assertRaises(ValueError):
                verify(folder)

    def test_unmeasured_parent_choice_is_not_strategy_target(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = publish([], [self.action], Path(temp))
            target = json.loads(json.loads((folder / 'model_train.jsonl').read_text())['messages'][-1]['content'])
            self.assertEqual(target, {'legal': [False]})

    def test_measured_improvement_is_a_strategy_target(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = publish([], [dict(self.action, legal=[1], oracle_improved=True, oracle_horizon=12)], Path(temp))
            target = json.loads(json.loads((folder / 'model_train.jsonl').read_text())['messages'][-1]['content'])
            self.assertEqual(target['best_index_over_12_ticks'], 0)

    def test_missing_and_smaller_model_cannot_train_queen_adapter(self):
        self.assertFalse(base_preflight(None)['queen_compatible'])
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / 'config.json').write_text(json.dumps({'model_type': 'qwen3', 'hidden_size': 2048, 'num_hidden_layers': 28}))
            (base / 'model.safetensors').write_bytes(b'fake')
            self.assertFalse(base_preflight(base)['queen_compatible'])


if __name__ == '__main__':
    unittest.main()
