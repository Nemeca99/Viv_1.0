import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'INN'))
import torch
from inn.engine import DEFAULT_CONFIG
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.wiki_sentence_corpus import lead_sentences, reduce_sentence, prepare


class SentenceTests(unittest.TestCase):
    def test_redirect_is_not_training_text(self):
        self.assertEqual(lead_sentences('Title: Alias\n#REDIRECT [[Other article]]'), [])

    def test_markup_cleanup_keeps_article_prose(self):
        raw = 'Title: Water\n{{Short description|Liquid}} Water contains [[hydrogen]] and [[oxygen]], forming a familiar liquid.<ref>Unwanted citation text.</ref>\n== History ==\nIgnore the later section entirely.'
        rows = lead_sentences(raw)
        self.assertEqual(rows, ['Water contains hydrogen and oxygen, forming a familiar liquid.'])

    def test_removal_records_offsets_and_preserves_negation(self):
        text = 'Boy does not fall and snake does not win.'
        reduced, removed = reduce_sentence(text)
        self.assertEqual(reduced, 'Boy does not fall snake does not win.')
        self.assertEqual([text[r['start']:r['end']] for r in removed], ['and'])

    def test_article_split_and_duplicate_exclusion(self):
        with tempfile.TemporaryDirectory() as folder:
            batch = Path(folder) / 'batch_0000'
            batch.mkdir()
            for i in range(30):
                (batch / f'{i:06d}.txt').write_text(f'Title: Article {i}\nBuilding number {i} has solid walls and a roof above its entrance.', encoding='utf-8')
            (batch / '999999.txt').write_text((batch/'000000.txt').read_text(), encoding='utf-8')
            corpus = prepare(folder, article_limit=100)
            self.assertEqual(len(corpus['sources']), 30)
            splits = {}
            for row in corpus['rows']:
                splits.setdefault(row['article_id'], set()).add(row['split'])
            self.assertTrue(all(len(x) == 1 for x in splits.values()))

    def test_character_expansion_copies_existing_rows_by_identity(self):
        torch.set_num_threads(1)
        old = INNCharacterTokenizer.from_texts(['abc'])
        parent = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=old, seed=42)
        new = INNCharacterTokenizer.from_texts(['0abcé'])
        child = LanguageEngine(copy.deepcopy(DEFAULT_CONFIG), tokenizer=new, seed=99)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'engine.pt'
            parent.save(path)
            child.migrate_character_parent(path)
        for char in old.characters:
            torch.testing.assert_close(parent.model.token.weight[old.stoi[char]], child.model.token.weight[new.stoi[char]], rtol=0, atol=0)
        for a,b in zip(parent.model.blocks.parameters(), child.model.blocks.parameters()):
            torch.testing.assert_close(a,b,rtol=0,atol=0)
