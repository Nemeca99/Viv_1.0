"""Unit tests for Multi-Daemon Concept-Partitioned Cognitive Orchestrator."""

import pytest
import sys
import hashlib
import json
import random
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.multi_daemon_orchestrator import MultiDaemonOrchestrator, CONCEPT_DOMAINS, commit_sentence_with_retry
from autonomy import terminal_neuron_learning
from autonomy import multi_daemon_orchestrator as orchestrator_module
from autonomy.fractal_cognitive_engine import ontology_definition_facts, ontology_composed_facts


class TestPrivacy:
    def authorize_file_write(self, path):
        return {"allowed": True, "reason": "test_scope"}


def test_concept_domain_orthogonality():
    """Verify that semantic concept domains have zero word overlaps."""
    all_words: list[str] = []
    for domain_key, domain in CONCEPT_DOMAINS.items():
        assert "name" in domain
        assert "words" in domain
        assert len(domain["words"]) > 0
        for word in domain["words"]:
            assert word not in all_words, f"Overlap detected: word '{word}' in multiple concept domains"
            all_words.append(word)


def test_dry_run_parallel_execution(tmp_path):
    """Verify concurrent multi-daemon execution across domains in dry-run mode (no disk writes)."""
    random.seed(0)
    custom_domains = {
        "sensory_test": {
            "name": "Sensory Test Domain",
            "description": "Thermal test concepts",
            "words": ["warm"],
        },
        "kinematic_test": {
            "name": "Kinematic Test Domain",
            "description": "Motion test concepts",
            "words": ["glide"],
        },
    }

    orchestrator = MultiDaemonOrchestrator(domains=custom_domains,
                                          status_file=tmp_path / "multi_daemon_status.json",
                                          status_privacy_core=TestPrivacy())
    report = orchestrator.run_parallel_test(words_per_domain=1, enable_commits=False)

    assert report["total_attempted"] == 2
    # Unsupported domain words must fail closed rather than receive a
    # fabricated composition from a sentence template.
    assert report["total_sentences_synthesized"] == 0
    assert len(report["per_daemon_telemetry"]) == 2

    # Verify both daemons executed without errors
    for domain_k, telem in report["per_daemon_telemetry"].items():
        assert len(telem["errors"]) == 0
        assert telem["words_attempted"] == 1
        assert len(telem["receipts"]) == 1
        receipt = telem["receipts"][0]
        assert receipt["tri_mastery"] is False
        assert receipt["sentences"] == []


def test_bloom_composition_requires_independent_sqlite_relation_chain():
    grounded = ontology_definition_facts("bloom", "botanical_living")
    composed = ontology_composed_facts("bloom", grounded)

    assert len(grounded) >= 3
    assert all(item["grounding"] == "lexicon_ontology.raw_definition" for item in grounded[:3])
    assert composed
    candidate = composed[0]
    assert candidate["sentence"] == "A bloom is part of a plant."
    assert candidate["grounding"] == "lexicon_ontology.semantic_relation_chain"
    assert candidate["sentence"] not in {item["sentence"] for item in grounded}
    assert [step["relation"] for step in candidate["relation_path"]] == ["IS_A", "IS_A", "PART_OF"]
    assert all("relation_id" in step for step in candidate["relation_path"][1:])


def test_commit_retry_replays_pending_sentence_from_verified_parent():
    calls = []
    waits = []

    def commit(sentence, *, resume, attempts):
        calls.append((sentence, resume, attempts))
        if len(calls) == 1:
            raise RuntimeError("Lock busy: terminal_neuron_learning.lock")
        if len(calls) == 2:
            raise ValueError("Route snapshot hash mismatch: neuron_graph.sqlite3")
        return {"run": "verified-new-run"}

    receipt, retries = commit_sentence_with_retry(
        "pending sentence", commit_fn=commit, sleep_fn=waits.append,
        jitter_fn=lambda low, high: 0.0)
    assert receipt["run"] == "verified-new-run"
    assert calls == [("pending sentence", "latest_verified", 6)] * 3
    assert [event["attempt"] for event in retries] == [1, 2]
    assert waits == [0.2, 0.4]


def test_commit_retry_does_not_retry_authority_denial():
    calls = []

    def denied(*args, **kwargs):
        calls.append(1)
        raise PermissionError("Rust lease denied")

    with pytest.raises(PermissionError):
        commit_sentence_with_retry("pending sentence", commit_fn=denied,
                                   sleep_fn=lambda _: None)
    assert len(calls) == 1


def test_latest_verified_parent_skips_hash_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal_neuron_learning, "RUNS", tmp_path)
    for suffix, corrupt in (("20260101T000000000000Z", False),
                            ("20260102T000000000000Z", True)):
        run = tmp_path / f"language-routes-{suffix}"
        run.mkdir()
        graph = b"graph"
        curriculum = b"curriculum"
        (run / "neuron_graph.sqlite3").write_bytes(graph + (b"changed" if corrupt else b""))
        (run / "curriculum.sqlite3").write_bytes(curriculum)
        (run / "learning.json").write_text(json.dumps({
            "schema": "viv_terminal_neuron_learning_v1", "snapshot_verified": True,
            "snapshot_hashes": {
                "neuron_graph.sqlite3": hashlib.sha256(graph).hexdigest(),
                "curriculum.sqlite3": hashlib.sha256(curriculum).hexdigest(),
            },
        }), encoding="utf-8")
    selected = terminal_neuron_learning.latest_verified_run()
    assert selected.name == "language-routes-20260101T000000000000Z"
    assert (tmp_path / "language-routes-20260102T000000000000Z").exists()


def test_transient_body_hold_releases_without_quarantining_word(tmp_path, monkeypatch):
    class FakeEngine:
        def execute_fractal_mastery_cycle(self, word, domain_hint=None, use_teacher_context=False):
            return {
                "tri_sentence_mastery": True,
                "novel_sentences": ["The word moves."],
                    "sentence_details": [{
                        "sentence": "The word moves.",
                        "novel_to_history": True,
                        "type": "COMPOSED_FACT",
                        "relation_path": [
                            {"source": "word", "relation": "IS_A", "target": "thing"},
                            {"source": "thing", "relation": "PART_OF", "target": "world"},
                        ],
                    }],
                "synthesis_count": 1,
                "polarity_result": {"rectifier": {"status": "OPEN_CIRCUIT"}},
            }

    class FakeBodyHold(RuntimeError):
        verdict = {"allowed": False, "reasons": ["gpu_memory_at_or_above_limit_or_unavailable"]}

    def held(*args, **kwargs):
        raise FakeBodyHold("body hold")

    monkeypatch.setattr(orchestrator_module, "FractalCognitiveEngine", FakeEngine)
    monkeypatch.setattr(orchestrator_module, "commit_sentence_with_retry", held)
    orchestrator = MultiDaemonOrchestrator(
        domains={"test": {"name": "Test", "description": "Test", "words": ["probe"]}},
        status_file=tmp_path / "status.json", status_privacy_core=TestPrivacy())
    monkeypatch.setattr(orchestrator.stop_event, "wait", lambda seconds: True)
    result = orchestrator.run_parallel_test(words_per_domain=1, enable_commits=True)
    assert result["total_attempted"] == 1
    assert result["total_graduated"] == 0
    assert "probe" not in orchestrator.quarantined_words
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert not status["running"]
    assert status["per_daemon"]["test"]["commit_retry_count"] == 1
    assert "gpu_memory_at_or_above_limit_or_unavailable" in result["per_daemon_telemetry"]["test"]["errors"][0]
