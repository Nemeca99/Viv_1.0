from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from io import BytesIO
import json
from unittest.mock import patch

from viv_autonomy import (DEFAULT_TASK_LIST, Store, choose_task, file_lock,
                          normalize_index_response, plan, queen_repair_messages,
                          queue_curiosity_question, run_autonomous_task,
                          seed_task, update_curiosity_question, validate_spec)
from viv_project_builder import queue_project, scheduler_spec
from autonomy.agent_index import validate_index_proposal


class DurableAutonomyTests(unittest.TestCase):
    def test_queen_repair_prompt_preserves_source_and_marks_expert_output_untrusted(self):
        evidence = {"source": {"path": r"L:\demo\module.py", "line": 4,
                                "sha256": "a" * 64, "snippet": "def load_sensor():"},
                    "existing_ancestor_choices": ["demo"],
                    "sense_audit_for_this_layer": {"sight": "source text"}}
        messages = [{"role": "system", "content": "index source"},
                    {"role": "user", "content": json.dumps(evidence)}]
        repaired = queen_repair_messages(
            messages, '{"status":"OBSERVED","result":"bad"}',
            "follow-up is not anchored")
        payload = json.loads(repaired[-1]["content"])
        self.assertEqual(payload["source"], evidence["source"])
        self.assertEqual(payload["existing_ancestor_choices"], ["demo"])
        self.assertIn("load_sensor", payload["required_followup_anchor_terms"])
        self.assertEqual(payload["queen_repair_diagnostic"]["validator_rejection"],
                         "follow-up is not anchored")
        self.assertEqual(payload["queen_repair_diagnostic"]["rejected_expert_response"]["trust"],
                         "untrusted_diagnostic_only")
        self.assertIn("five curiosity summary labels", repaired[-2]["content"])
        self.assertIn("verbatim token from required_followup_anchor_terms",
                      repaired[-2]["content"])

    def test_queen_repair_prompt_omits_unsafe_expert_output(self):
        messages = [{"role": "user", "content": json.dumps({"source": {"path": "L:/x", "line": 1}})}]
        repaired = queen_repair_messages(
            messages, "password=example", "unsafe output",
            include_rejected_response=False)
        diagnostic = json.loads(repaired[-1]["content"])["queen_repair_diagnostic"]
        self.assertNotIn("password=example", repaired[-1]["content"])
        self.assertEqual(diagnostic["rejected_expert_response"]["omitted"],
                         "credential-sensitive or unavailable")

    def test_premature_json_close_recovery_keeps_index_validator_authoritative(self):
        source = {"path": r"L:\demo\readme.md", "line": 2,
                  "sha256": "a" * 64, "snippet": "parse_value handles source reports"}
        citation = f"{source['path']}:{source['line']}"
        summary = (
            f"Sense/source: file text at {citation}; "
            "Observation: parse_value reads a report; "
            "Investigate: check parse_value call sites; "
            "Architect learns: call sites show how reports flow; "
            "Follow-up question: Where is parse_value defined?")
        first = json.dumps({
            "status": "OBSERVED",
            "result": f"Project path: demo; category: documentation; summary: {summary}",
        })
        remaining = json.dumps({"evidence": [citation], "unknowns": []})
        malformed = first + "," + remaining[1:]

        normalized, reason = normalize_index_response(
            malformed, source, "L", ["demo"])
        self.assertEqual(
            reason, "rejoined_fields_after_premature_json_object_close")
        entry = validate_index_proposal(
            "L", source, normalized, require_curiosity=True)
        self.assertEqual(entry["status"], "OBSERVED")
        self.assertEqual(entry["evidence"], [citation])

    def test_premature_json_close_recovery_rejects_trailing_commentary(self):
        first = json.dumps({"status": "OBSERVED", "result": "untrusted"})
        malformed = first + " commentary"
        normalized, reason = normalize_index_response(
            malformed,
            {"path": r"L:\demo\readme.md", "line": 2},
            "L", ["demo"])
        self.assertEqual(normalized, malformed)
        self.assertIsNone(reason)

    def test_curiosity_question_persists_source_and_recursive_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            source = {"path": r"L:\Projects\AIOS\README.md", "line": 4,
                      "sha256": "a" * 64, "snippet": "The API is described here."}
            parent, added = queue_curiosity_question(
                store, "Which module implements the API?", "L", source,
                parent_id="root-observation", depth=1)
            self.assertTrue(added)
            again, added_again = queue_curiosity_question(
                store, "Which module implements the API?", "L", source,
                parent_id="root-observation", depth=1)
            self.assertFalse(added_again)
            self.assertEqual(again["id"], parent["id"])
            self.assertEqual(Store(tmp).get("curiosity_questions")[0]["source"],
                             {key: source[key] for key in ("path", "line", "sha256")})
            self.assertEqual(Store(tmp).status()["open_curiosity_question_count"], 1)

    def test_curiosity_followup_records_investigation_and_architect_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            source = {"path": r"L:\Projects\AIOS\README.md", "line": 4,
                      "sha256": "a" * 64, "snippet": "The API is described here."}
            question, _ = queue_curiosity_question(store, "Where is the API defined?", "L", source)
            attempted = {"path": r"L:\Projects\AIOS\api.py", "line": 17,
                         "sha256": "b" * 64}
            update_curiosity_question(store, question["id"], source=attempted,
                                      status="needs_architect", relation="UNRESOLVED")
            status = store.status()
            self.assertEqual(status["open_curiosity_question_count"], 0)
            self.assertEqual(status["curiosity_questions_needing_architect"], 1)
            saved = store.get("curiosity_questions")[0]
            self.assertEqual(saved["attempted_sources"], [attempted])
            self.assertEqual(saved["last_relation"], "UNRESOLVED")

    def test_generic_curiosity_question_is_handed_to_architect(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            source = {"path": r"L:\\docs\\delete-your-account.md", "line": 12,
                      "sha256": "c" * 64, "snippet": "Warning"}
            question, added = queue_curiosity_question(
                store, "What is the purpose of this file?", "L", source)
            self.assertTrue(added)
            self.assertEqual(question["status"], "needs_architect")
            self.assertFalse(question["question_source_anchored"])
            status = store.status()
            self.assertEqual(status["open_curiosity_question_count"], 0)
            self.assertEqual(status["curiosity_questions_needing_architect"], 1)

    def test_tasks_and_objective_survive_new_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Store(tmp)
            first.set("objective", "Build useful tools")
            task_id = first.add(seed_task())
            second = Store(tmp)
            self.assertEqual(second.get("objective"), "Build useful tools")
            self.assertEqual(second.status()["tasks"][0]["id"], task_id)
            second.add(seed_task())
            self.assertEqual(len(second.status()["tasks"]), 1)

    def test_pause_is_durable(self):
        with tempfile.TemporaryDirectory() as tmp:
            Store(tmp).set("enabled", False)
            self.assertFalse(Store(tmp).get("enabled"))

    def test_worker_lock_rejects_competing_owner_and_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "worker.lock"
            with file_lock(path):
                with self.assertRaises(RuntimeError):
                    with file_lock(path):
                        self.fail("Second lock owner admitted")
            with file_lock(path):
                pass

    def test_invalid_task_cannot_enter_queue(self):
        invalid = seed_task()
        invalid["cases"] = []
        with self.assertRaises(ValueError):
            validate_spec(invalid)

    def test_contradictory_or_duplicate_inputs_cannot_enter_queue(self):
        invalid = seed_task()
        value = {"data": ["ready"], "options": {"limit": 1}}
        invalid["cases"] = [
            {"input": value, "expected": ["task-a"]},
            {"input": value, "expected": ["task-b"]},
            {"input": {"data": [], "options": {}}, "expected": []},
        ]
        with self.assertRaisesRegex(ValueError, "Contradictory expected outputs"):
            validate_spec(invalid)
        invalid["cases"][1]["expected"] = ["task-a"]
        with self.assertRaisesRegex(ValueError, "Duplicate test input"):
            validate_spec(invalid)

    def test_dependency_readiness_plan_must_include_current_task_states(self):
        invalid = {"title": "Choose dependency-ready tasks",
                   "requirement": "Select runnable tasks using dependency resolution and current system state.",
                   "cases": []}
        tasks = [{"task": "compile", "dependencies": ["install"]},
                 {"task": "install", "dependencies": []}]
        for sort in ("none", "alphabetical", "reverse_alphabetical"):
            invalid["cases"].append({"input": {"data": tasks, "options": {"sort": sort}},
                                      "expected": []})
        with self.assertRaisesRegex(ValueError, "status/current_state"):
            validate_spec(invalid)

        valid = {**invalid,
                 "requirement": "Select runnable tasks using dependency resolution and current system state; return them in input order.",
                 "cases": []}
        for states in ({"compile": "pending", "install": "completed"},
                       {"compile": "pending", "install": "failed"},
                       {"compile": "completed", "install": "completed"}):
            valid["cases"].append({"input": {"data": tasks, "options": {"current_state": states}},
                                    "expected": []})
        validate_spec(valid)

    def test_malformed_model_plan_is_logged_without_crashing_or_queueing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            malformed = json.dumps({"title": "bad", "requirement": "bad", "cases": [{"input": {}}]})
            with patch("viv_autonomy.ask_model", return_value=malformed):
                plan(store)
            self.assertIn("Rejected malformed proposal", store.get("planning_feedback"))
            self.assertEqual(store.status()["tasks"], [])
            with store.connect() as con:
                event = con.execute("SELECT kind,data FROM events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(event["kind"], "plan_rejected")
            self.assertIn("proposal_sha256", event["data"])

    def test_exact_rejected_plan_is_caught_by_canonical_hash_before_another_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            proposal = {"title": "Count build receipts",
                        "requirement": "Count receipt rows from the provided list and return the total.",
                        "cases": [{"input": [1], "expected": 1},
                                  {"input": [1, 2], "expected": 2},
                                  {"input": [], "expected": 0}]}
            raw = json.dumps(proposal)
            with patch("viv_autonomy.ask_model", return_value=raw):
                plan(store)
                plan(store)
            with store.connect() as con:
                rows = con.execute(
                    "SELECT id,data FROM events WHERE kind='plan_rejected' ORDER BY id").fetchall()
            first = json.loads(rows[-2]["data"])
            second = json.loads(rows[-1]["data"])
            self.assertIn("every input needs exactly data and options", first["reason"].casefold())
            self.assertEqual(second["repeated_from_event_id"], rows[-2]["id"])
            self.assertIn("proposal_canonical_sha256", second)

    def test_contradictory_model_plan_is_rejected_before_spec_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            repeated = {"data": ["ready"], "options": {}}
            proposal = {"title": "Resolve runnable tasks consistently",
                        "requirement": "Return runnable tasks from dependency data without hidden state.",
                        "cases": [{"input": repeated, "expected": ["a"]},
                                  {"input": repeated, "expected": ["b"]},
                                  {"input": {"data": [], "options": {}}, "expected": []}]}
            with patch("viv_autonomy.ask_model", return_value=json.dumps(proposal)) as ask:
                plan(store)
            self.assertEqual(ask.call_count, 1)
            self.assertIn("Contradictory expected outputs", store.get("planning_feedback"))
            self.assertEqual(store.status()["tasks"], [])

    def test_planner_receives_bounded_untrusted_failure_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            failed_id = store.add(seed_task())
            with store.connect() as con:
                con.execute("UPDATE tasks SET status='failed',attempts=5,feedback=? WHERE id=?",
                            ("SyntaxError: generated candidate was invalid", failed_id))
            proposal = {"title": "Count unique receipt sources",
                        "requirement": "Count distinct source identifiers from a list of receipts.",
                        "cases": [{"input": {"data": [{"source": "A"}], "options": {}},
                                   "expected": 1},
                                  {"input": {"data": [{"source": "A"}, {"source": "B"}], "options": {}},
                                   "expected": 2},
                                  {"input": {"data": [], "options": {}}, "expected": 0}]}
            with patch("viv_autonomy.ask_model", side_effect=[
                    json.dumps(proposal), json.dumps({"valid": True, "reason": "clear"})]) as ask:
                plan(store)
            planner_context = json.loads(ask.call_args_list[0].args[0][1]["content"])
            self.assertEqual(planner_context["recent_failed_attempts"][0]["id"], failed_id)
            self.assertIn("SyntaxError", planner_context["recent_failed_attempts"][0]["feedback_untrusted"])
            self.assertEqual(len(store.status()["tasks"]), 2)

    def test_random_task_draw_uses_persistent_activity_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.add(seed_task())
            project = queue_project(store, scheduler_spec())
            selected = choose_task(store, chooser=lambda candidates: candidates[-1])
            self.assertEqual(selected, {"kind": "test", "id": "test"})
            self.assertEqual(store.get("task_list"), DEFAULT_TASK_LIST)
            with store.connect() as con:
                event = con.execute("SELECT kind,data FROM events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(event["kind"], "task_selected")
            self.assertIn('"selection":"uniform_random"', event["data"])

    def test_activity_task_is_completed_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.set("learned_notes", "Source evidence says ask only when blocked.")
            from unittest.mock import patch
            with patch("viv_autonomy.ask_model", return_value="What source should I inspect next?"):
                result = run_autonomous_task(store, "unused", {"kind": "chat", "id": "chat"})
            self.assertIn("queued", result)
            self.assertEqual(store.get("pending_chat"), "What source should I inspect next?")
            with store.connect() as con:
                event = con.execute("SELECT kind,data FROM events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(event["kind"], "task_completed")

    def test_worker_model_is_unloaded_after_each_prompt(self):
        from viv_autonomy import ask_model
        response = BytesIO(b'{"done_reason":"stop","message":{"content":"ok"}}')
        with patch("viv_autonomy.file_lock", return_value=nullcontext()), \
             patch("viv_autonomy.urllib.request.urlopen", return_value=response) as request:
            self.assertEqual(ask_model([{"role": "user", "content": "one task"}]), "ok")
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["keep_alive"], 0)


if __name__ == "__main__":
    unittest.main()
