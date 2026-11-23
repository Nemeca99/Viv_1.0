import sys, json
sys.path.insert(0, r"L:\LocalCoder\workspace\autonomy\learning")
from neuron_transition_matrix import NeuronTransitionMatrix

with open(r"E:\Viv_Sandbox\playground\topology\transition_matrix.json", "r", encoding="utf-8") as f:
    tm = NeuronTransitionMatrix.from_dict(json.load(f))

print(f"Total Vocabulary in Neuron Matrix: {len(tm.vocab)}")
print(f"Total Sentences Ingested: {tm.total_sentences}")
print(f"Top 10 Word Starts: {tm.start_counts.most_common(10)}")

seeds = ["i", "the", "docker", "syntax", "adversarial", "uml", "travis"]
print("\n--- DIRECT AUTOREGRESSIVE GENERATION FROM NEURON TOPOLOGY GRAPH (ZERO LLM) ---")
for s in seeds:
    gen = tm.generate(s, max_tokens=10)
    score = tm.score_sequence(gen.split())
    print(f"Seed '{s}' -> Conductance Route: '{gen}' (log-score: {score:.2f})")
