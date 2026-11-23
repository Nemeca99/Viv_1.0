"""Compact neural view of the Architect's universal UML character IDs.

Universal IDs never change. A frozen manifest maps a run's active characters
to dense embedding rows; changing that manifest requires a new checkpoint.
"""
import hashlib
import json
from . import uml_character_tokenizer as uml


class INNCharacterTokenizer:
    schema = 'inn_uml_character_view_v1'

    def __init__(self, characters):
        ids = [uml.character_to_token_id(c) for c in characters]
        if not ids or len(set(ids)) != len(ids) or ids != sorted(ids):
            raise ValueError('Characters must be unique and in universal ID order')
        self.characters = tuple(characters)
        self.universal_ids = tuple(ids)
        self.stoi = {c: i for i, c in enumerate(self.characters)}
        self.PAD, self.BOS, self.EOS = len(ids), len(ids) + 1, len(ids) + 2
        self.size = len(ids) + 3

    @classmethod
    def from_texts(cls, texts):
        chars = set()
        for text in texts:
            if not isinstance(text, str):
                raise TypeError('Tokenizer source must be text')
            chars.update(text)
        return cls(sorted(chars, key=uml.character_to_token_id))

    def encode(self, text):
        # Validate Unicode scalars using the original tokenizer, even on misses.
        uml.encode(text)
        try:
            return [self.stoi[c] for c in text]
        except KeyError as exc:
            raise ValueError(f'Character outside frozen neural vocabulary: U+{ord(exc.args[0]):04X}') from None

    def decode(self, tokens):
        chars = []
        for token in tokens:
            if type(token) is not int or not 0 <= token < len(self.characters):
                raise ValueError('Expected character ID, not special or invalid token')
            chars.append(uml.token_id_to_character(self.universal_ids[token]))
        return ''.join(chars)

    def manifest(self):
        body = {'schema': self.schema, 'characters': list(self.characters),
                'universal_ids': list(self.universal_ids), 'size': self.size,
                'special_ids': {'PAD': self.PAD, 'BOS': self.BOS, 'EOS': self.EOS},
                'universal_vocab_sha256': uml.VOCAB_SHA256}
        body['sha256'] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
        return body

    @classmethod
    def from_manifest(cls, manifest):
        tokenizer = cls(manifest['characters'])
        if tokenizer.manifest() != manifest:
            raise ValueError('Tokenizer manifest identity mismatch')
        return tokenizer
