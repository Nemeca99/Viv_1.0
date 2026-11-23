import sys
import json
from pathlib import Path

autonomy_learning = Path(r"L:\LocalCoder\workspace\autonomy\learning")
sys.path.insert(0, str(autonomy_learning))
from neuron_transition_matrix import NeuronTransitionMatrix

tm_path = Path(r"E:\Viv_Sandbox\playground\topology\transition_matrix.json")
if not tm_path.exists():
    print("Transition matrix not found!")
    sys.exit(1)

with open(tm_path, "r", encoding="utf-8") as f:
    tm_data = json.load(f)

matrix = NeuronTransitionMatrix.from_dict(tm_data)
print(f"=== BODY TOPOLOGY LOADED ===")
print(f"Vocabulary: {len(matrix.vocab)} tokens")
print(f"Total Sentences Routed: {matrix.total_sentences:,}")
print(f"Bigram Highways: {sum(len(v) for v in matrix.bigrams.values()):,}")
print(f"Trigram Channels: {len(matrix.trigrams):,}")
print()

seeds = [
    "in",
    "i",
    "the",
    "verified",
    "hardware",
    "code",
    "aios",
    "travis",
    "matrix",
    "cycle"
]

print("=== DECOUPLED BODY SPEECH (ZERO LLM / ZERO NEURAL NETWORKS) ===")
for seed in seeds:
    sentence = matrix.generate(seed, max_tokens=18)
    # Also score it
    tokens = sentence.split()
    score = matrix.score_sequence(tokens)
    print(f"Seed [{seed:>8}] -> \"{sentence}\" (conductance: {score:.2f})")
