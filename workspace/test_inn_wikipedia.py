import copy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parent / 'INN'))
import torch
from inn.engine import DEFAULT_CONFIG
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.wiki_stream import article_chunks, prepare_segment


class WikipediaTests(unittest.TestCase):
    def test_full_body_and_bounded_chunks(self):
        text = 'Title: Water\nWater has hydrogen and oxygen in its familiar liquid form.\n== History ==\n' + ('Later sections retain their prose and order in the training examples. ' * 30)
        rows = article_chunks(text)
        self.assertTrue(any('Later sections' in r['original'] for r in rows))
        self.assertTrue(all(len(r['original']) <= 240 for r in rows))
        self.assertTrue(any(r['removed'] for r in rows))

    def test_cursor_traverses_without_repeating_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for b in range(2):
                batch = root / f'batch_{b:04d}'
                batch.mkdir()
                for i in range(3):
                    (batch / f'{i:06d}.txt').write_text(f'Title: Article\nBuilding number {b}-{i} contains walls and windows above the entrance.', encoding='utf-8')
            first = prepare_segment(root, articles=2)
            second = prepare_segment(root, first['next_cursor'], articles=4)
            self.assertFalse(first['exhausted'])
            self.assertTrue(second['exhausted'])
            self.assertEqual(len(first['sources']) + len(second['sources']), 6)
            self.assertFalse({s['path'] for s in first['sources']} & {s['path'] for s in second['sources']})

    def test_inline_export_headings_do_not_enter_targets(self):
        rows = article_chunks('Title: Water\nWater contains hydrogen and oxygen in its familiar liquid form. == History == Later sections retain their prose and order in the training examples.')
        self.assertTrue(any('Later sections' in r['original'] for r in rows))
        self.assertFalse(any('==' in r['original'] for r in rows))

    def test_expansion_resumes_adam_moments_and_steps(self):
        torch.set_num_threads(1)
        old = INNCharacterTokenizer.from_texts(['abc'])
        parent = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=old, context_length=512, seed=1)
        parent.train_joint([{'prompt': '', 'target': 'abc'}], [])
        new = INNCharacterTokenizer.from_texts(['0abcé'])
        child = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=new, context_length=512, seed=2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'engine.pt'
            parent.save(path)
            child.resume_character_parent(path)
        self.assertEqual(child.optimizer_steps, parent.optimizer_steps)
        for name in ('token.weight', 'lm_head.weight', 'lm_head.bias'):
            a = dict(parent.model.named_parameters())[name]
            b = dict(child.model.named_parameters())[name]
            for key in ('exp_avg', 'exp_avg_sq'):
                for c in old.characters:
                    torch.testing.assert_close(parent.optimizer.state[a][key][old.stoi[c]],
                        child.optimizer.state[b][key][new.stoi[c]], rtol=0, atol=0)
                self.assertEqual(float(child.optimizer.state[b][key][new.stoi['é']].abs().sum()), 0.)
        child.train_joint([{'prompt': '', 'target': 'éabc'}], [])
        self.assertEqual(child.optimizer_steps, 2)

    def test_same_vocabulary_resume_has_identical_next_update(self):
        torch.set_num_threads(1)
        tokenizer = INNCharacterTokenizer.from_texts(['abc'])
        a = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, seed=1)
        example = [{'prompt': '', 'target': 'abc'}]
        a.train_joint(example, [])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'engine.pt'
            a.save(path)
            b = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, seed=5)
            b.resume_character_parent(path)
        a.train_joint(example, [])
        b.train_joint(example, [])
        for x, y in zip(a.model.parameters(), b.model.parameters()):
            torch.testing.assert_close(x, y, rtol=0, atol=0)
