import sys
import json
import random
import math
from pathlib import Path
from collections import Counter

autonomy_learning = Path(r"L:\LocalCoder\workspace\autonomy\learning")
sys.path.insert(0, str(autonomy_learning))
from neuron_transition_matrix import NeuronTransitionMatrix

tm_path = Path(r"E:\Viv_Sandbox\playground\topology\transition_matrix.json")
with open(tm_path, "r", encoding="utf-8") as f:
    tm_data = json.load(f)

matrix = NeuronTransitionMatrix.from_dict(tm_data)

def body_speak(matrix: NeuronTransitionMatrix, seed: str, max_tokens: int = 25, temperature: float = 0.7, repetition_penalty: float = 1.4) -> str:
    tokens = seed.lower().split()
    seen = Counter(tokens)
    
    for _ in range(max_tokens - len(tokens)):
        preds = matrix.predict_next(tokens, top_k=20)
        if not preds:
            break
            
        words, probs = zip(*preds)
        # Apply repetition penalty & temperature
        adjusted = []
        for w, p in zip(words, probs):
            count = seen[w]
            adj_p = p / (repetition_penalty ** count) if count > 0 else p
            # temperature scaling
            adj_p = adj_p ** (1.0 / max(0.01, temperature))
            adjusted.append(adj_p)
            
        total = sum(adjusted)
        if total == 0:
            break
        norm_probs = [p / total for p in adjusted]
        
        # Sample
        next_word = random.choices(words, weights=norm_probs, k=1)[0]
        tokens.append(next_word)
        seen[next_word] += 1
        
        # Stop at natural terminal punctuation or end-words
        if matrix.end_counts.get(next_word, 0) > 20 and len(tokens) >= 8 and random.random() < 0.4:
            break
            
    return " ".join(tokens)

print("=== DECOUPLED BODY SPEECH WITH CONDUCTANCE SAMPLING (NO GPU / NO LLM) ===\n")
random.seed(42)
seeds = ["in", "the", "i", "hardware", "code", "aios", "travis", "matrix", "during"]
for s in seeds:
    for t in [0.4, 0.7]:
        speech = body_speak(matrix, s, max_tokens=22, temperature=t, repetition_penalty=1.5)
        print(f"[{s:>8}] (T={t:.1f}) -> \"{speech}\"")
    print()
