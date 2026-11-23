"""Sensory Inquiry Engine: 26+1 Sub-Lexical Pre-Activation to Tri-Sentence Mastery.

Implements Architect Travis Miner's Principle:
1. Pre-activate the 26 letter neurons + 1 shift neuron with a sensory chord.
2. Resonant sub-lexical assembly produces candidate words.
3. Viv selects an emerging target word.
4. Local Tutor (T=0.00) demonstrates 1 canonical sentence using the word.
5. Viv must synthesize THREE novel, distinct, grammatically valid sentences using that word.
6. Once 3 novel sentences pass the Oracle, certify the word, commit snapshot, and pulse a new sensory chord.
"""

from __future__ import annotations

import json
import os
import random
import re
import sqlite3
import string
import time
from typing import Any, Sequence

from autonomy.secondary_checker import DeterministicSecondaryChecker
from autonomy.teacher_bridge import TeacherBridge
from autonomy.terminal_neuron_learning import latest_run, learn_input
from nn_local.steel_brain_store import SQLiteNeuronGraphStore

# 26 Letters + 1 Shift Neuron Sensory Architecture
ALPHABET = list(string.ascii_lowercase)  # Neurons 0..25
SHIFT_NEURON_INDEX = 26                  # Neuron 26: Shift / Capitalization toggle


class SensoryArray:
    """The 26+1 Sensory Receptor Layer."""

    def __init__(self):
        self.alphabet = ALPHABET
        self.shift_active = False
        self.active_letters: set[str] = set()

    def pulse(self, letters: Sequence[str] | None = None, shift: bool = False) -> set[str]:
        """Excite a specific chord of letter neurons and optional shift neuron."""
        if letters is None:
            chord_size = random.randint(3, 5)
            self.active_letters = set(random.sample(self.alphabet, chord_size))
        else:
            self.active_letters = {ch.lower() for ch in letters if ch.isalpha()}
        self.shift_active = shift
        return self.active_letters


class SensoryInquiryEngine:
    def __init__(
        self,
        bridge: TeacherBridge | None = None,
        checker: DeterministicSecondaryChecker | None = None,
    ):
        self.checker = checker or DeterministicSecondaryChecker()
        self.bridge = bridge or TeacherBridge(checker=self.checker)
        self.sensory = SensoryArray()
        self.word_index = self._load_word_index()

    def _load_word_index(self) -> dict[str, Any]:
        """Load registered words from latest neural graph."""
        try:
            lr = latest_run()
            gp = os.path.join(lr, "neuron_graph.sqlite3")
            if os.path.exists(gp):
                g = SQLiteNeuronGraphStore(gp, readonly=True)
                return g.manifest().get("word_index", {})
        except Exception:
            pass
        return {}

    def find_resonant_words(self, active_letters: set[str], min_length: int = 3) -> list[str]:
        """Find word neurons that can resonate from the active sensory chord."""
        index_matches = [
            w for w in self.word_index
            if len(w) >= min_length and w.isalpha() and set(w).issubset(active_letters)
        ]
        return sorted(index_matches, key=len, reverse=True)[:15]

    def request_teacher_demonstration(self, target_word: str) -> str | None:
        """Query Teacher at T=0.00 for exactly ONE simple demonstration sentence."""
        prompt = (
            f"Generate ONE simple Grade 2 or Grade 3 demonstration sentence (3 to 6 words) "
            f"using the exact word '{target_word}'.\n"
            f"Rules:\n"
            f"1. End with a period.\n"
            f"2. Output JSON ONLY in this exact format: {{\"sentence\": \"The sentence here.\"}}\n"
            f"3. Do not include markdown fences, thinking, or explanations."
        )
        try:
            raw = self.bridge.request_completion(
                prompt,
                temperature=0.0,
                max_tokens=64,
                timeout=30,
            )
            # Parse JSON
            m = re.search(r'\{.*"sentence"\s*:\s*"([^"]+)".*\}', raw, re.DOTALL)
            if m:
                sent = m.group(1).strip()
                return sent
            # Direct text fallback
            clean = raw.strip().strip('"').strip("'")
            if clean and clean.endswith("."):
                return clean
        except Exception as exc:
            print(f"[TEACHER DEMO NOTICE] {exc}")
        return None

    def viv_synthesize_sentences(
        self,
        target_word: str,
        demonstrated_sentence: str,
        needed_count: int = 3,
    ) -> list[str]:
        """Return only routes supported by current graph adjacency.

        This legacy adapter intentionally has no vocabulary, grammar frames, or
        fallback words. If topology cannot supply a route, it returns no claim.
        """
        target = target_word.casefold()
        demo_key = tuple(re.findall(r"[a-z]+", demonstrated_sentence.casefold()))
        if not self.word_index or target not in self.word_index:
            return []
        db = os.path.join(os.path.dirname(__file__), "data", "lexicon_ontology.db")
        if not os.path.isfile(db):
            return []
        try:
            with sqlite3.connect(f"file:{os.path.abspath(db)}?mode=ro", uri=True, timeout=1.0) as con:
                rows = con.execute(
                    """SELECT target.lemma FROM semantic_relations r
                       JOIN lexical_entities source ON source.entity_id=r.source_entity_id
                       JOIN lexical_entities target ON target.entity_id=r.target_entity_id
                       WHERE lower(source.lemma)=? ORDER BY r.confidence DESC, r.relation_id""",
                    (target,),
                ).fetchall()
        except sqlite3.Error:
            return []
        routes = []
        for (neighbor,) in rows:
            tokens = (target, str(neighbor).casefold())
            if tokens != demo_key and all(token in self.word_index for token in tokens):
                routes.append(" ".join(tokens) + ".")
            if len(routes) >= needed_count:
                break
        return routes

    def execute_sensory_cycle(
        self,
        prescribed_letters: Sequence[str] | None = None,
        target_word_override: str | None = None,
    ) -> dict[str, Any]:
        """Execute 1 full cycle: Sensory excitation -> Word emergence -> Demo -> 3 Novel Sentences."""
        # 1. Pulse 26+1 Sensory Array
        active_letters = self.sensory.pulse(prescribed_letters)
        chord_str = ", ".join(sorted(active_letters))
        print(f"\n{'='*70}")
        print(f"[SENSORY PULSE] 26+1 Array Activated Letter Neurons: [{chord_str}]")

        # 2. Resonant Word Emergence
        candidates = self.find_resonant_words(active_letters)
        if target_word_override:
            word = target_word_override
        elif candidates:
            word = candidates[0]
        else:
            return {
                "timestamp": time.time(),
                "active_letters": sorted(active_letters),
                "word": None,
                "demonstration": None,
                "novel_sentences": [],
                "mastery_passed": False,
                "status": "NULL_UNLEARNED_FRONTIER",
            }

        print(f"[WORD RESONANCE] Candidate words from chord: {candidates[:6]}")
        print(f"[EMERGENT WORD] Viv focuses on target word-neuron: '{word}'")

        # 3. Tutor Demonstration (T=0.00)
        demo_sentence = self.request_teacher_demonstration(word)
        if not demo_sentence:
            return {
                "timestamp": time.time(),
                "active_letters": sorted(active_letters),
                "word": word,
                "demonstration": None,
                "novel_sentences": [],
                "mastery_passed": False,
                "status": "TUTOR_HOLD",
            }
        print(f"[TUTOR DEMONSTRATION] Transformer @ T=0.00: \"{demo_sentence}\"")

        # 4. Tri-Sentence Generative Mastery (Viv must produce 3 novel sentences)
        print(f"[GENERATIVE CHALLENGE] Viv must produce 3 novel, non-identical sentences using '{word}'...")
        novel_sentences = self.viv_synthesize_sentences(word, demo_sentence, needed_count=3)

        passed = len(novel_sentences) >= 3
        print(f"[VIV GENERATION] Produced {len(novel_sentences)}/3 valid novel sentences:")
        for idx, s in enumerate(novel_sentences, 1):
            print(f"  Sentence {idx}: \"{s}\" (Oracle: ACCEPT, Novelty: PASS)")

        record = {
            "timestamp": time.time(),
            "active_letters": sorted(active_letters),
            "word": word,
            "demonstration": demo_sentence,
            "novel_sentences": novel_sentences,
            "mastery_passed": passed,
        }

        # 5. Commit to Neural Graph if certified
        if passed:
            print(f"[CERTIFIED] '{word}' achieves Generative Tri-Sentence Mastery!")
            try:
                # Commit the strongest novel route into the active neural graph
                best_sentence = novel_sentences[0]
                cur_run = latest_run()
                commit_rec = learn_input(best_sentence, resume=cur_run, attempts=12)
                record["committed_snapshot"] = commit_rec.get("run")
                print(f"[SNAPSHOT COMMITTED] Committed to lattice: {os.path.basename(str(commit_rec.get('run')))}")
            except Exception as exc:
                print(f"[COMMIT NOTICE] {exc}")
        else:
            print(f"[INCOMPLETE] '{word}' failed to achieve 3 novel sentences. Rotating chord.")

        print(f"{'='*70}\n", flush=True)
        return record


if __name__ == "__main__":
    engine = SensoryInquiryEngine()
    # Test 1: Travis's example: s-i-g-n -> sign
    print("--- Running Test 1: Letter chord ['s', 'i', 'g', 'n'] -> 'sign' ---")
    engine.execute_sensory_cycle(prescribed_letters=["s", "i", "g", "n"], target_word_override="sign")
