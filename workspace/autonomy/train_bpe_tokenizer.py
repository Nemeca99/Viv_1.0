"""Train Viv's byte-level BPE tokenizer (character + word).

Byte-level BPE is the tokenizer Travis specified: per character AND per word.
  - Byte level: every byte (letters, apostrophe, period, exclamation) is a base
    token, so she can compose any word from characters and keep punctuation as
    single tokens ("viv" + "'" + "s" = "viv's", "really" + "!" = "really!").
  - BPE merges: common character sequences merge into whole-word tokens, so
    common words are one efficient token instead of a string of bytes.

Trained on her own corpus (neuron vocabulary + grammar + identity) so the
vocabulary is hers. Lossless: every byte is reachable, so any unseen word can
still be decomposed to bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", nargs="*", default=[
        "L:/LocalCoder/models/viv_neuron_corpus.txt",
        "L:/LocalCoder/models/viv_grammar_corpus.txt",
    ])
    ap.add_argument("--vocab-size", type=int, default=8192)
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_bpe_tokenizer.json"))
    args = ap.parse_args()

    tokenizer = Tokenizer(models.BPE(unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tokenizer.decoder = decoders.ByteLevel()
    trainer = trainers.BpeTrainer(
        vocab_size=args.vocab_size,
        special_tokens=["<unk>", "<s>", "</s>", "<pad>"],
        min_frequency=2,
        show_progress=True,
    )
    tokenizer.train([str(p) for p in args.corpus if Path(p).is_file()], trainer)
    tokenizer.save(str(args.out))

    vocab = tokenizer.get_vocab()
    size = tokenizer.get_vocab_size()
    print(json.dumps({
        "vocab_size": size,
        "path": str(args.out),
        "corpus": [str(p) for p in args.corpus if Path(p).is_file()],
    }, indent=2))
    # show a few merged word tokens (multi-byte) to confirm word-level merges
    words = sorted([t for t in vocab if len(t) > 2 and t.isalpha()], key=len, reverse=True)[:15]
    print("longest merged tokens:", words)


if __name__ == "__main__":
    raise SystemExit(main())
