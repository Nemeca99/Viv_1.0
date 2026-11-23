import json
import unittest

from hive_proof import (
    CAPABILITY,
    MEMBER_ID,
    MIND_MODEL,
    WORKER_MODEL,
    evidence_packet,
    run_probe,
    validate_plan,
    validate_worker,
)


class FakeBackend:
    def __init__(self):
        self.calls = []

    def ask(self, model, messages, *, gpu_layers):
        self.calls.append((model, messages, gpu_layers))
        if len(self.calls) == 1:
            return json.dumps({"member_id": MEMBER_ID, "capability": CAPABILITY, "objective": "Read hello.py"})
        if len(self.calls) == 2:
            return json.dumps({"answer": "It prints Hello, World!", "claims": [
                {"text": "The file prints Hello, World!", "kind": "retrieved_fact", "evidence_ids": ["hello-py"]}
            ]})
        return json.dumps({"summary": "hello.py prints Hello, World!; it was not executed.", "evidence_ids": ["hello-py"]})


class RepairBackend(FakeBackend):
    def ask(self, model, messages, *, gpu_layers):
        if len(self.calls) == 1:
            self.calls.append((model, messages, gpu_layers))
            return json.dumps({"answer": "Hello, World!", "claims": [
                {"text": "The file prints Hello, World!", "kind": "fact", "evidence_ids": ["hello-py"]}
            ]})
        if len(self.calls) == 2:
            self.calls.append((model, messages, gpu_layers))
            return json.dumps({"answer": "Hello, World!", "claims": [
                {"text": "The file prints Hello, World!", "kind": "retrieved_fact", "evidence_ids": ["hello-py"]}
            ]})
        return super().ask(model, messages, gpu_layers=gpu_layers)


class HiveContractTests(unittest.TestCase):
    def test_route_and_stateless_cpu_worker(self):
        backend = FakeBackend()
        receipt = run_probe(backend)
        self.assertEqual(receipt["status"], "contract_path_completed; semantic_accuracy_not_admitted")
        self.assertEqual([call[0] for call in backend.calls], [MIND_MODEL, WORKER_MODEL, MIND_MODEL])
        self.assertEqual([call[2] for call in backend.calls], [None, 0, None])
        self.assertEqual(len(backend.calls[1][1]), 2)
        worker_packet = backend.calls[1][1][1]["content"]
        self.assertNotIn("You are Viv", worker_packet)
        self.assertIn("hello-py", worker_packet)

    def test_disallowed_capability_and_disabled_member_fail_closed(self):
        plan = {"member_id": MEMBER_ID, "capability": "run-shell", "objective": "List all files"}
        with self.assertRaisesRegex(ValueError, "ungranted capability"):
            validate_plan(plan, {MEMBER_ID})
        plan["capability"] = CAPABILITY
        with self.assertRaisesRegex(ValueError, "disabled or unknown member"):
            validate_plan(plan, set())

    def test_evidence_citation_is_checked(self):
        evidence = evidence_packet()
        output = {"answer": "A", "claims": [{"text": "A", "kind": "retrieved_fact", "evidence_ids": ["unknown"]}]}
        with self.assertRaisesRegex(ValueError, "unknown evidence ID"):
            validate_worker(output, evidence)
        output["claims"][0]["evidence_ids"] = ["hello-py"]
        evidence["tier"] = "external_unverified"
        with self.assertRaisesRegex(ValueError, "lacks verified evidence"):
            validate_worker(output, evidence)

    def test_semantically_empty_worker_is_rejected(self):
        evidence = evidence_packet()
        with self.assertRaisesRegex(ValueError, "no bounded claims"):
            validate_worker({"answer": "Done", "claims": []}, evidence)

    def test_single_bounded_repair_preserves_invalid_raw_output(self):
        backend = RepairBackend()
        receipt = run_probe(backend)
        self.assertEqual(receipt["worker_validation_error"], "Worker claim kind is invalid")
        self.assertEqual([stage["stage"] for stage in receipt["stages"]],
                         ["mind_plan", "worker", "worker_repair", "mind_final"])
        self.assertIn('"kind": "fact"', receipt["stages"][1]["raw"])


if __name__ == "__main__":
    unittest.main()
