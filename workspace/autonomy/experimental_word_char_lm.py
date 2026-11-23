"""Small isolated causal LM consuming WordCharTokenizer's structured tokens.

Experimental only: no Viv checkpoint, admitted model, or runtime is modified.
Unicode scalars use three learned 7-bit factors, avoiding a 1.1M-row table.
"""

from __future__ import annotations

import torch
from torch import nn
import torch.nn.functional as F

from word_char_tokenizer import EncodedPiece, WordCharTokenizer


class WordCharTransformer(nn.Module):
    def __init__(self, word_count: int, *, width: int = 96, heads: int = 4,
                 layers: int = 2, max_context: int = 512):
        super().__init__()
        if word_count < 1 or width % heads:
            raise ValueError("word_count must be positive and width divisible by heads")
        self.word_count = word_count
        self.width = width
        self.max_context = max_context
        self.word_embedding = nn.Embedding(word_count, width)
        self.char_factors = nn.ModuleList(nn.Embedding(128, width) for _ in range(3))
        self.end_embedding = nn.Parameter(torch.empty(width))
        nn.init.normal_(self.end_embedding, std=0.02)
        self.kind_embedding = nn.Embedding(3, width)
        self.position_embedding = nn.Embedding(max_context, width)
        block = nn.TransformerEncoderLayer(
            d_model=width, nhead=heads, dim_feedforward=4 * width,
            batch_first=True, norm_first=True, activation="gelu",
        )
        self.blocks = nn.TransformerEncoder(block, num_layers=layers, enable_nested_tensor=False)
        self.final_norm = nn.LayerNorm(width)
        self.kind_head = nn.Linear(width, 3)
        self.word_head = nn.Linear(width, word_count)
        self.char_heads = nn.ModuleList(nn.Linear(width, 128) for _ in range(3))

    def forward(self, kinds: torch.Tensor, values: torch.Tensor) -> dict[str, torch.Tensor]:
        if kinds.ndim != 2 or values.shape != kinds.shape:
            raise ValueError("kinds and values must have matching [batch, sequence] shape")
        batch, length = kinds.shape
        if length > self.max_context:
            raise ValueError("sequence exceeds configured context")
        if torch.any((kinds < 0) | (kinds > 2)):
            raise ValueError("invalid token kind")
        x = torch.zeros(batch, length, self.width, device=kinds.device)
        word_mask = kinds == WordCharTokenizer.WORD
        char_mask = kinds == WordCharTokenizer.CHAR
        end_mask = kinds == WordCharTokenizer.FALLBACK_END
        if word_mask.any():
            ids = values[word_mask]
            if torch.any((ids < 0) | (ids >= self.word_count)):
                raise ValueError("word ID out of model vocabulary")
            x[word_mask] = self.word_embedding(ids)
        if char_mask.any():
            cp = values[char_mask]
            if torch.any((cp < 0) | (cp > 0x10FFFF) | ((cp >= 0xD800) & (cp <= 0xDFFF))):
                raise ValueError("invalid Unicode scalar ID")
            factors = (cp >> 14, (cp >> 7) & 0x7F, cp & 0x7F)
            x[char_mask] = sum(table(digit) for table, digit in zip(self.char_factors, factors))
        x[end_mask] = self.end_embedding
        x = x + self.kind_embedding(kinds)
        positions = torch.arange(length, device=kinds.device).unsqueeze(0)
        x = x + self.position_embedding(positions)
        causal_mask = torch.triu(torch.ones(length, length, device=kinds.device, dtype=torch.bool), diagonal=1)
        hidden = self.final_norm(self.blocks(x, mask=causal_mask))
        return {
            "kind": self.kind_head(hidden),
            "word": self.word_head(hidden),
            "char_factors": torch.stack([head(hidden) for head in self.char_heads], dim=2),
        }

    @torch.no_grad()
    def generate(self, tokenizer: WordCharTokenizer, prompt: str, *, max_new_pieces: int = 64) -> str:
        """Greedily continue text, preserving the tokenizer's fallback framing.

        Greedy decoding is deliberate for this first deterministic interface
        check; it is not a claim that greedy decoding is the best sampler.
        """
        if len(tokenizer.words) != self.word_count:
            raise ValueError("tokenizer/model word vocabulary size mismatch")
        if max_new_pieces < 1:
            raise ValueError("max_new_pieces must be positive")
        device = next(self.parameters()).device
        pieces = tokenizer.encode(prompt)
        if not pieces:
            raise ValueError("prompt must encode to at least one piece")
        generated: list[EncodedPiece] = []
        fallback_open = False
        self.eval()
        for _ in range(max_new_pieces):
            context = pieces + generated
            if len(context) > self.max_context:
                context = context[-self.max_context:]
            kinds = {"WORD": WordCharTokenizer.WORD, "CHAR": WordCharTokenizer.CHAR,
                     "FALLBACK_END": WordCharTokenizer.FALLBACK_END}
            kind_ids = torch.tensor([[kinds[p.kind] for p in context]], dtype=torch.long, device=device)
            values = torch.tensor([[
                p.token_id - tokenizer.char_base if p.kind == "CHAR" else p.token_id
                for p in context
            ]], dtype=torch.long, device=device)
            output = self(kind_ids, values)
            state = output["kind"][0, -1]
            if fallback_open and state[WordCharTokenizer.FALLBACK_END] >= state[WordCharTokenizer.CHAR]:
                item = EncodedPiece("FALLBACK_END", tokenizer.fallback_end_id)
                fallback_open = False
            elif not fallback_open and state[WordCharTokenizer.CHAR] >= state[WordCharTokenizer.WORD]:
                # Never emit an end marker without first emitting a character.
                if state[WordCharTokenizer.FALLBACK_END] > state[WordCharTokenizer.CHAR]:
                    word_id = int(output["word"][0, -1].argmax().item())
                    item = EncodedPiece("WORD", word_id)
                else:
                    factor_logits = output["char_factors"][0, -1]
                    scalar = sum(
                        int(factor_logits[i].argmax().item()) << shift
                        for i, shift in enumerate((14, 7, 0))
                    )
                    scalar = min(scalar, 0x10FFFF)
                    if 0xD800 <= scalar <= 0xDFFF:
                        scalar = ord("�")
                    item = EncodedPiece("CHAR", tokenizer.char_base + scalar)
                    fallback_open = True
            else:
                word_id = int(output["word"][0, -1].argmax().item())
                item = EncodedPiece("WORD", word_id)
            generated.append(item)
        if fallback_open:
            generated.append(EncodedPiece("FALLBACK_END", tokenizer.fallback_end_id))
        return tokenizer.decode(generated)


def tensorize(tokenizer: WordCharTokenizer, pieces: list[EncodedPiece], *, device: str = "cpu") -> tuple[torch.Tensor, torch.Tensor]:
    kinds = {"WORD": WordCharTokenizer.WORD, "CHAR": WordCharTokenizer.CHAR,
             "FALLBACK_END": WordCharTokenizer.FALLBACK_END}
    kind_ids = torch.tensor([[kinds[p.kind] for p in pieces]], dtype=torch.long, device=device)
    values = [p.token_id - tokenizer.char_base if p.kind == "CHAR" else p.token_id for p in pieces]
    value_ids = torch.tensor([values], dtype=torch.long, device=device)
    return kind_ids, value_ids


def next_piece_loss(model: WordCharTransformer, pieces: list[EncodedPiece]) -> torch.Tensor:
    """Teacher-forced next-piece objective for one unpadded sequence."""
    if len(pieces) < 2:
        raise ValueError("at least two pieces are required for next-piece training")
    kinds = {"WORD": WordCharTokenizer.WORD, "CHAR": WordCharTokenizer.CHAR,
             "FALLBACK_END": WordCharTokenizer.FALLBACK_END}
    in_kind = torch.tensor([[kinds[p.kind] for p in pieces[:-1]]], dtype=torch.long)
    in_value = torch.tensor([[p.token_id if p.kind != "CHAR" else p.token_id - model.word_count
                              for p in pieces[:-1]]], dtype=torch.long)
    target_kind = torch.tensor([kinds[p.kind] for p in pieces[1:]], dtype=torch.long)
    outputs = model(in_kind, in_value)
    kind_loss = F.cross_entropy(outputs["kind"][0], target_kind)
    word_positions = torch.nonzero(target_kind == WordCharTokenizer.WORD, as_tuple=True)[0]
    if word_positions.numel():
        word_targets = torch.tensor([pieces[i + 1].token_id for i in word_positions.tolist()])
        kind_loss = kind_loss + F.cross_entropy(outputs["word"][0, word_positions], word_targets)
    char_positions = torch.nonzero(target_kind == WordCharTokenizer.CHAR, as_tuple=True)[0]
    if char_positions.numel():
        scalar_targets = torch.tensor([pieces[i + 1].token_id - model.word_count for i in char_positions.tolist()])
        for factor, shift in enumerate((14, 7, 0)):
            targets = (scalar_targets >> shift) & 0x7F
            kind_loss = kind_loss + F.cross_entropy(
                outputs["char_factors"][0, char_positions, factor], targets
            )
    return kind_loss

