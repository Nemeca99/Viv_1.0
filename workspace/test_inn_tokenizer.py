import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'INN'))
import torch
from inn.tokenizer import INNCharacterTokenizer
from inn import uml_character_tokenizer as uml
from inn.language import LanguageEngine
from inn.engine import DEFAULT_CONFIG


class CustomTokenizerTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)

    def test_universal_and_dense_roundtrips(self):
        for text in ('water → harvest', 'José café', '水 🌱', 'e\u0301', '\x00\U0010ffff'):
            tokenizer = INNCharacterTokenizer.from_texts([text])
            self.assertEqual(uml.decode(uml.encode(text)), text)
            self.assertEqual(tokenizer.decode(tokenizer.encode(text)), text)
            self.assertEqual(len(tokenizer.encode(text)), len(text))

    def test_frozen_manifest_integrity_and_unknown(self):
        tokenizer = INNCharacterTokenizer.from_texts(['abc'])
        self.assertEqual(INNCharacterTokenizer.from_manifest(tokenizer.manifest()).encode('cab'), [2, 0, 1])
        tampered = tokenizer.manifest()
        tampered['universal_ids'][0] += 1
        with self.assertRaises(ValueError):
            INNCharacterTokenizer.from_manifest(tampered)
        with self.assertRaises(ValueError):
            tokenizer.encode('d')
        with self.assertRaises(ValueError):
            tokenizer.encode('\ud800')

    def test_neural_update_reload_and_wrong_vocabulary_rejected(self):
        tokenizer = INNCharacterTokenizer.from_texts(['abc é→.'])
        engine = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, context_length=256)
        before = engine.model.blocks[0].qkv.weight.detach().clone()
        engine.train_joint([{'prompt': 'a→', 'target': 'é.'}], [])
        self.assertFalse(torch.equal(before, engine.model.blocks[0].qkv.weight))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'engine.pt'
            engine.save(path)
            other = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, context_length=256)
            other.load(path)
            self.assertEqual(other.speak('a→', 8), engine.speak('a→', 8))
            wrong = INNCharacterTokenizer.from_texts(['abd é→.'])
            other = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=wrong, context_length=256)
            with self.assertRaisesRegex(ValueError, 'contract'):
                other.load(path)

    def test_ascii_migration_preserves_parent_logits(self):
        parent = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), seed=42)
        tokenizer = INNCharacterTokenizer.from_texts([chr(i) for i in range(128)])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'parent.pt'
            parent.save(path)
            child = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, seed=99)
            child.migrate_byte_parent(path)
            with torch.no_grad():
                a = parent.model.language(torch.tensor([[257, 65, 66]]))
                b = child.model.language(torch.tensor([[tokenizer.BOS, *tokenizer.encode('AB')]]))
            torch.testing.assert_close(a[:, :, :128], b[:, :, :128], rtol=0, atol=0)

    def test_expanded_context_and_causal_character_attention(self):
        tokenizer = INNCharacterTokenizer.from_texts(['abc'])
        engine = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=tokenizer, context_length=512)
        with torch.no_grad():
            x = torch.tensor([[tokenizer.BOS] + tokenizer.encode('a' * 300)])
            a = engine.model.language(x)
            x[0, -1] = tokenizer.encode('b')[0]
            b = engine.model.language(x)
        self.assertTrue(torch.isfinite(a).all())
        torch.testing.assert_close(a[:, :-1], b[:, :-1], rtol=0, atol=0)
