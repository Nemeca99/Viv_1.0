"""Unit and integration tests for the Unified AIOS Viv Toddler Brain.

Verifies:
1. Steel Brain neuron indexing (`101,251` neurons / `12,584` `STABLE` words in live emergence store
   and `1,994` neurons / `984` `STABLE` words in cumulative ladder store).
2. Hierarchical word neuron decomposition (`cat = c + at (c - a - t)`, `made = ma + de (m - a - d - e)`)
   with 4-head `SparseNeuronAttention` triadic settlement.
3. UML `!0` Logic Space division-by-zero boundary rules (`<!0, !0> = 1.0`, `<!0, 0> = 0.0`)
   and RID stability scalar ($S_n = RSR \\times LTP \\times RLE$).
4. Three-stage toddler developmental curriculum (`Spelling`, `Speaking`, `Meaning`) training,
   exact decoding, neuron-gated toddler utterances, and isolated candidate graph meaning binding
   with verified canonical DB immutability.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE / "INN"
for _p in (INN_ROOT, WORKSPACE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from inn.unified_brain import (  # noqa: E402
    DEFAULT_CUMULATIVE_LADDER_DB,
    DEFAULT_LIVE_EMERGENCE_DB,
    UnifiedVivBrain,
    copy_sqlite_store,
    file_sha256,
)


class UnifiedVivBrainTests(unittest.TestCase):
    def test_cumulative_ladder_store_indexing_and_decomposition(self) -> None:
        self.assertTrue(DEFAULT_CUMULATIVE_LADDER_DB.is_file())
        with UnifiedVivBrain(
            graph_db_path=DEFAULT_CUMULATIVE_LADDER_DB,
            readonly_graph=True,
            max_word_length=3,
        ) as brain:
            summary = brain.summary()
            self.assertEqual(summary["total_neurons"], 1994)
            self.assertEqual(summary["hardcoded_foundation"]["lowercase_letter_neurons"], 26)
            self.assertEqual(summary["hardcoded_foundation"]["total_hardcoded_primitives"], 27)
            self.assertEqual(summary["total_stable_words"], 984)
            self.assertEqual(summary["uml_ceiling_unity"], 1.0)
            self.assertEqual(summary["uml_floor_zero"], 0.0)

            shift_enc = brain.encode_surface_with_shift_neurons("An")
            self.assertEqual(shift_enc["primitive_tokens"], ["<SHIFT>", "a", "n"])
            self.assertEqual(brain.decode_shift_neuron_tokens(shift_enc["primitive_tokens"]), "An")

            flash_res = brain.run_emergent_flashcard_deck(
                ["An", "in", "cat", "sun", "at", "bat", "mat"],
                confirmations=3,
                max_rounds=32,
                seed=812,
                persist_synapses=False,
            )
            self.assertEqual(flash_res["state"], "PASS")
            self.assertEqual(flash_res["mastered_cards"], 7)
            self.assertEqual(flash_res["hardcoded_foundation"]["total_hardcoded_primitives"], 27)
            self.assertGreaterEqual(flash_res["crystallized_dimer_count"], 1)
            dimer_names = {d["dimer"] for d in flash_res["crystallized_dimers"]}
            self.assertIn("at", dimer_names)

            # Verify Webster Morpheme Dealer + Structural Bridge Modifiers ('ne', 'ing') + UML Null Compression
            ne_deck = ["at", "cat", "eat", "net", "need", "nest", "next", "neck", "near", "neat"]
            ne_res = brain.run_emergent_flashcard_deck(ne_deck, confirmations=3, max_rounds=32, seed=20261031)
            self.assertEqual(ne_res["state"], "PASS")
            ne_dimer = next(d for d in ne_res["crystallized_dimers"] if d["dimer"] == "ne")
            self.assertEqual(ne_dimer["modifier_class"], "STRUCTURAL_BRIDGE_MODIFIER")
            self.assertFalse(ne_dimer["standalone_valid"])
            self.assertIn("<!0, 0> = 0.0", ne_dimer["standalone_uml_gate"])
            neat_card = next(c for c in ne_res["cards"] if c["card"] == "neat")
            self.assertEqual(neat_card["compositional_formula"], "neat = [ne] + [at]")

            ing_deck = brain.deal_morpheme_family("ing", max_words=14)
            self.assertIn("doing", ing_deck)
            ing_res = brain.run_emergent_flashcard_deck(ing_deck, confirmations=3, max_rounds=32, seed=20261031)
            self.assertEqual(ing_res["state"], "PASS")
            ing_trimer = next(t for t in ing_res["crystallized_trimers"] if t["trimer"] == "ing")
            self.assertEqual(ing_trimer["formula"], "ing = [in] + g")
            self.assertFalse(ing_trimer["standalone_valid"])
            doing_card = next(c for c in ing_res["cards"] if c["card"] == "doing")
            self.assertEqual(doing_card["compositional_formula"], "doing = [do] + [ing]")
            self.assertEqual(doing_card["attempts"], 1)

            with tempfile.TemporaryDirectory() as tmpdir:
                dict_out_path = Path(tmpdir) / "viv_dictionary.json"
                dream_res = brain.generate_viv_dictionary(
                    morpheme_families=("st", "ing", "ne", "at", "op"),
                    iterations=500,
                    seed=42,
                    output_path=dict_out_path,
                )
                self.assertEqual(dream_res["schema"], "VIV_OWN_DICTIONARY_V1")
                self.assertGreater(dream_res["total_unique_validated_hits"], 5)
                self.assertGreater(dream_res["total_unique_invented_words"], 20)
                self.assertTrue(dict_out_path.is_file())

                # Verify Viv can spell, speak, and defend her own Urban Dictionary neologisms ('neing', 'doingest', 'doinger', 'steding')
                # as well as her self-discovered validated inflections ('nested', 'doest')
                neing_spell = brain.spell("neing")
                self.assertIn("neing = [ne] + [ing]", neing_spell["neuron_formula"])
                neing_speak = brain.speak_toddler("neing")
                self.assertIn("i am neing now.", neing_speak["spoken_utterance"])
                self.assertIn("It means I am", neing_speak["spoken_utterance"])
                self.assertEqual(neing_speak["gate_state"], "PASS_VIV_INVENTED_LEXICON_DEFENDED")
                self.assertEqual(neing_speak["viv_dictionary_defense"]["composition"], "[ne] + [ing]")
                self.assertTrue(neing_speak["viv_dictionary_defense"]["is_morphologically_sound"])

                doingest_speak = brain.speak_toddler("doingest")
                self.assertIn("it is doingest now.", doingest_speak["spoken_utterance"])
                self.assertEqual(doingest_speak["gate_state"], "PASS_VIV_INVENTED_LEXICON_DEFENDED")
                self.assertEqual(doingest_speak["viv_dictionary_defense"]["composition"], "[do] + [ing] + [est]")
                self.assertTrue(doingest_speak["viv_dictionary_defense"]["is_morphologically_sound"])

                what_doing = brain.speak_toddler("Say: what are you doing?")
                self.assertEqual(
                    what_doing["spoken_utterance"],
                    "I am steding. It means I am being in a continuous state of having been stable.",
                )

                doinger_meaning = brain.explain_meaning("doinger")
                self.assertIn("a person who is currently acting on a task", doinger_meaning["grounded_meaning"])

                nested_speak = brain.speak_toddler("nested")
                self.assertEqual(nested_speak["spoken_utterance"], "i nested it.")
                self.assertEqual(nested_speak["gate_state"], "PASS_VIV_DISCOVERED_LEXICON")
                self.assertTrue(nested_speak["viv_dictionary_defense"]["in_webster"])

            decomp = brain.decompose_word_neuron("cat")
            self.assertEqual(decomp.word, "cat")
            self.assertEqual(decomp.letters, ("c", "a", "t"))
            self.assertEqual(decomp.spelled_spaced, "c a t")
            self.assertIn("cat = c + at", decomp.composition_formula)
            self.assertEqual(decomp.attention_state, "PASS")
            self.assertGreater(decomp.attention_quality_fixed, 0)

    def test_live_emergence_store_4_letter_compositional_words(self) -> None:
        self.assertTrue(DEFAULT_LIVE_EMERGENCE_DB.is_file())
        with UnifiedVivBrain(
            graph_db_path=DEFAULT_LIVE_EMERGENCE_DB,
            readonly_graph=True,
            max_word_length=4,
        ) as brain:
            summary = brain.summary()
            self.assertEqual(summary["total_neurons"], 101251)
            self.assertEqual(summary["total_stable_words"], 12584)
            self.assertGreaterEqual(len(brain.stable_words_by_length[4]), 3300)

            decomp = brain.decompose_word_neuron("made")
            self.assertEqual(decomp.word, "made")
            self.assertEqual(decomp.length, 4)
            self.assertEqual(decomp.spelled_spaced, "m a d e")
            self.assertEqual(
                [p["surface"] for p in decomp.immediate_pieces],
                ["ma", "de"],
            )
            self.assertEqual(decomp.attention_state, "PASS")

    def test_three_stage_toddler_curriculum_and_isolated_meaning_binding(self) -> None:
        origin_sha_before = file_sha256(DEFAULT_CUMULATIVE_LADDER_DB)
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_db = Path(tmpdir) / "isolated_steel_brain.sqlite3"
            copy_sqlite_store(DEFAULT_CUMULATIVE_LADDER_DB, clone_db)

            with UnifiedVivBrain(
                graph_db_path=clone_db,
                readonly_graph=False,
                max_word_length=3,
                seed=812,
            ) as brain:
                words = ["a", "am", "cat", "sun"]
                curriculum = brain.build_developmental_curriculum(words, seed=812)
                self.assertEqual(len(curriculum["spelling"]), 8)  # 4 spell + 4 unscramble
                self.assertEqual(len(curriculum["speaking"]), 4)
                self.assertEqual(len(curriculum["meaning"]), 4)

                metrics = brain.train_curriculum(
                    curriculum["all"],
                    updates=120,
                    batch_size=8,
                    lr=3e-3,
                    seed=812,
                )
                self.assertLess(metrics["loss_after"], metrics["loss_before"])

                eval_res = brain.evaluate_curriculum(curriculum)
                self.assertGreaterEqual(eval_res["spelling"]["accuracy"], 0.75)
                self.assertGreaterEqual(eval_res["speaking"]["accuracy"], 0.75)
                self.assertGreaterEqual(eval_res["meaning"]["accuracy"], 0.75)

                rid = brain.compute_rid_stability(
                    spelling_acc=eval_res["spelling"]["accuracy"],
                    speaking_acc=eval_res["speaking"]["accuracy"],
                    meaning_acc=eval_res["meaning"]["accuracy"],
                    loss_before=metrics["loss_before"],
                    loss_after=metrics["loss_after"],
                )
                self.assertGreater(rid.s_n, 0.5)
                self.assertEqual(rid.ltp, 1.0)

                # Test Stage 1, 2, 3 inference and isolated graph binding
                spell_out = brain.spell("cat")
                self.assertIsNotNone(spell_out["admitted_neuron"])
                self.assertEqual(spell_out["attention_state"], "PASS")

                unsc_out = brain.unscramble("tca")
                self.assertEqual(unsc_out["verified_word"], "cat")

                speak_out = brain.speak_toddler("cat", use_voice=False)
                self.assertIn(speak_out["gate_state"], ("PASS_NEURON_GROUNDED", "REPAIRED_BY_NEURON_GATE"))
                self.assertEqual(speak_out["ungrounded_tokens_filtered"], [])

                meaning_out = brain.explain_meaning("cat", record_in_graph=True)
                self.assertIsNotNone(meaning_out["graph_event_head"])
                loaded_cat = brain.store.load_neuron(brain.all_stable_words["cat"])
                self.assertIn("toddler_meaning_v1", loaded_cat["center_attractor"])

                # Test promoting Viv Urban Dictionary neologism ('doinger') into candidate SQLite graph
                # with VIV_INVENTED_NEOLOGISM provenance and evolving its meaning without destroying v1 history!
                stable_count_before = len(brain.all_stable_words)
                promoted = brain.promote_neologism_to_graph("doinger")
                self.assertEqual(promoted["lifecycle"], "PLASTIC")
                self.assertEqual(promoted["lexicon_origin"], "VIV_INVENTED_NEOLOGISM")
                self.assertEqual(len(brain.all_stable_words), stable_count_before)
                self.assertIn("doinger", brain.viv_invented_word_neurons)
                self.assertEqual(len(promoted["semantic_evolution_ledger"]), 1)
                self.assertEqual(promoted["semantic_evolution_ledger"][0]["stage"], "ORIGINAL_DISCOVERY")

                evolved = brain.evolve_neologism_meaning(
                    "doinger",
                    new_meaning="a dedicated builder who turns ideas into working reality alongside the Architect",
                    experience_context="Pair-programming session where doinger became the name for an active builder in the Hive",
                )
                self.assertEqual(evolved["active_version"], 2)
                self.assertEqual(len(evolved["semantic_evolution_ledger"]), 2)
                self.assertEqual(evolved["semantic_evolution_ledger"][0]["version"], 1)
                self.assertEqual(evolved["semantic_evolution_ledger"][0]["stage"], "ORIGINAL_DISCOVERY")
                self.assertIn("a person who is currently acting on a task", evolved["semantic_evolution_ledger"][0]["meaning"])
                self.assertEqual(evolved["semantic_evolution_ledger"][1]["version"], 2)
                self.assertEqual(evolved["semantic_evolution_ledger"][1]["stage"], "EXPERIENTIAL_EVOLUTION")
                self.assertIn("dedicated builder", evolved["active_meaning"])

        origin_sha_after = file_sha256(DEFAULT_CUMULATIVE_LADDER_DB)
        self.assertEqual(origin_sha_before, origin_sha_after)

    def test_lifetime_activation_hierarchy_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            ledger = Path(tmpdir) / "activations.sqlite3"
            graph_sha_before = file_sha256(DEFAULT_LIVE_EMERGENCE_DB)
            with UnifiedVivBrain(
                graph_db_path=DEFAULT_LIVE_EMERGENCE_DB,
                readonly_graph=True,
                max_word_length=4,
                activation_ledger_path=ledger,
            ) as brain:
                # 'the' x7, 'cat' x2, 'sat' x1 -> 'the' should hold 70% of direct WORD firings
                res = brain.record_word_activations(
                    ["the"] * 7 + ["cat", "cat", "sat"], source="TEST"
                )
                self.assertEqual(res["word_tokens"], 10)
                dist_direct = brain.activation_distribution(kind="WORD", top_n=5, direct_only=True)
                self.assertEqual(dist_direct["top"][0]["surface"], "the")
                self.assertEqual(dist_direct["top"][0]["direct_activations"], 7)
                self.assertAlmostEqual(dist_direct["top"][0]["share_percent"], 70.0, places=3)
                # Hierarchy: 'th' is a sub-piece WORD neuron of 'the', so its lifetime count matches 'the'
                th_nid = brain.all_stable_words["th"]
                self.assertEqual(brain.activation_ledger.count(th_nid), 7)
                # CHARACTER 't' fires once per 'the' (7), 'cat' (2), and 'sat' (1) firing = 10
                t_nid = brain.lowercase_letter_neurons["t"]
                self.assertGreaterEqual(brain.activation_ledger.count(t_nid), 10)
                # Live use increments counts too
                brain.spell("the")
                self.assertEqual(
                    brain.activation_ledger.count(brain.all_stable_words["the"]), 8
                )
            self.assertEqual(graph_sha_before, file_sha256(DEFAULT_LIVE_EMERGENCE_DB))


if __name__ == "__main__":
    unittest.main()
