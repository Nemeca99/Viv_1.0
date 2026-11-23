from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from io import BytesIO
import json
from unittest.mock import Mock, patch

from viv_autonomy import (DEFAULT_TASK_LIST, Store, choose_task, file_lock,
                          normalize_index_response, plan, queen_repair_messages,
                          queue_curiosity_question, record_drive_index_rejection,
                          planner_output_diagnostic, curiosity_ancestor_questions,
                          curiosity_sense_audit, curiosity_followup_blocklist,
                          ModelResponseTruncated,
                          run_autonomous_task,
                          seed_task, update_curiosity_question, validate_spec)
from viv_project_builder import queue_project, scheduler_spec
from autonomy.agent_index import (curiosity_question_repeats_ancestor,
                                  validate_index_proposal)


class DurableAutonomyTests(unittest.TestCase):
    def test_recursive_followup_blocklist_includes_immediate_parent_and_older_ancestors(self):
        root = {"id": "root-question", "question": "What does the search key do?",
                "parent_id": "root-entry"}
        current = {"id": "current-question", "question": "What does the search key do?",
                   "parent_id": "root-question"}

        blocked = curiosity_followup_blocklist([root, current], current)

        self.assertEqual(blocked, [current["question"], root["question"]])
        self.assertTrue(curiosity_question_repeats_ancestor(
            "What does the search key do?", blocked))

    def test_curiosity_sense_audit_carries_sensor_provenance_and_freshness(self):
        source = {"path": r"L:\docs\sensor_map.md", "line": 8, "sha256": "a" * 64}
        sensors = {"observed_utc": "2026-10-05T08:00:00+00:00",
                   "external_sensor_logs": {
                       "hwinfo": {"path": r"L:\LocalCoder\Hardware\hwinfo.CSV",
                                  "sample_timestamp": "2026-10-05 02:59:50",
                                  "sample_age_seconds": 10.0, "stale": False,
                                  "readings": {"CPU Package [C]": "45"}},
                       "corsair": {"path": r"L:\LocalCoder\Hardware\corsair.csv",
                                   "sample_age_seconds": 25.0, "stale": True}}}

        audit = curiosity_sense_audit(source, sensors)

        self.assertIn("sensor_map.md:8", audit["sight"])
        self.assertIn("no haptic/contact sensor", audit["touch"])
        self.assertEqual(audit["body_state_instrumentation"], sensors)
        self.assertEqual(audit["body_state_instrumentation"]["external_sensor_logs"]["hwinfo"]["stale"], False)
        self.assertEqual(audit["body_state_instrumentation"]["external_sensor_logs"]["corsair"]["stale"], True)
        self.assertIn("unavailable", audit["hearing"])
        self.assertIn("unavailable", audit["taste"])
        self.assertIn("unavailable", audit["smell"])

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

    def test_recursive_missing_relation_defaults_only_to_unresolved(self):
        source = {"path": r"L:\demo\readme.md", "line": 2,
                  "sha256": "a" * 64, "snippet": "parse_value reads a report"}
        citation = f"{source['path']}:{source['line']}"
        summary = (
            f"Sense/source: file text at {citation}; Observation: parse_value reads a report; "
            "Investigate: inspect parse_value call sites; "
            "Architect learns: call sites may show the data flow; "
            "Follow-up question: Where is parse_value defined?")
        raw = json.dumps({
            "status": "OBSERVED",
            "result": f"Project path: demo; category: documentation; summary: {summary}",
            "evidence": [citation], "unknowns": []})
        normalized, reason = normalize_index_response(
            raw, source, "L", ["demo"], parent_question=True)
        self.assertIn("defaulted_recursive_parent_status_to_unresolved", reason)
        entry = validate_index_proposal(
            "L", source, normalized, require_curiosity=True, parent_question=True)
        self.assertTrue(entry["summary"].startswith(
            "Prior question status: UNRESOLVED; Sense/source:"))

    def test_recursive_missing_relation_does_not_repair_malformed_status(self):
        source = {"path": r"L:\demo\readme.md", "line": 2,
                  "sha256": "a" * 64, "snippet": "parse_value reads a report"}
        citation = f"{source['path']}:{source['line']}"
        summary = (
            f"Prior question status: MAYBE; Sense/source: file text at {citation}; "
            "Observation: parse_value reads a report; Investigate: inspect call sites; "
            "Architect learns: call sites may show data flow; "
            "Follow-up question: Where is parse_value defined?")
        raw = json.dumps({"status": "OBSERVED",
                          "result": f"Project path: demo; category: documentation; summary: {summary}",
                          "evidence": [citation], "unknowns": []})
        normalized, reason = normalize_index_response(
            raw, source, "L", ["demo"], parent_question=True)
        self.assertNotIn("defaulted_recursive_parent_status_to_unresolved", reason or "")
        proposal = json.loads(normalized)
        self.assertIn("Prior question status: MAYBE;", proposal["result"])

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

    def test_recursive_model_rejection_records_attempt_and_hands_off_after_five(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            parent_source = {"path": r"C:\headers\font.h", "line": 1,
                             "sha256": "a" * 64, "snippet": "macro"}
            parent, _ = queue_curiosity_question(
                store, "What does font.h define?", "C", parent_source,
                parent_id="root", depth=1)
            for line in range(2, 7):
                source = {"path": parent_source["path"], "line": line,
                          "sha256": parent_source["sha256"], "snippet": "macro call"}
                parent = next(row for row in store.get("curiosity_questions")
                              if row["id"] == parent["id"])
                record_drive_index_rejection(
                    store, drive="C", source=source,
                    reason="recursive summary failed validation",
                    rejected_response="bad summary", curiosity_parent=parent)
                current_status = next(row["status"] for row in store.get("curiosity_questions")
                                      if row["id"] == parent["id"])
                self.assertEqual(current_status, "needs_architect" if line == 6 else "pending")
            current = next(row for row in store.get("curiosity_questions")
                           if row["id"] == parent["id"])
            self.assertEqual(current["attempts"], 5)
            self.assertEqual(current["status"], "needs_architect")
            self.assertEqual(len(current["attempted_sources"]), 5)
            feedback = store.get("drive_index_feedback")["C"]
            self.assertTrue(feedback["pending"])
            self.assertEqual(feedback["reason"], "recursive summary failed validation")

    def test_recursive_ancestor_questions_follow_persistent_parent_chain(self):
        queue = [
            {"id": "root", "parent_id": "index-entry", "question": "Where is parse_value defined?"},
            {"id": "child", "parent_id": "root", "question": "What does parse_value return?"},
            {"id": "grandchild", "parent_id": "child", "question": "What does parse_value return?"},
        ]
        ancestors = curiosity_ancestor_questions(queue, queue[-1])
        self.assertEqual(ancestors, ["What does parse_value return?", "Where is parse_value defined?"])

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
            diagnostic = store.get("planning_rejection_diagnostic")
            self.assertEqual(diagnostic["raw_output"]["text"], malformed)
            self.assertEqual(diagnostic["raw_output"]["trust"], "untrusted_diagnostic_only")

    def test_planner_receives_bounded_untrusted_prior_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            malformed = '{"title":"bad","requirement":"missing cases"}'
            with patch("viv_autonomy.ask_model", return_value=malformed):
                plan(store)
            proposal = {"title": "Count unique receipts",
                        "requirement": "Count distinct receipt identifiers from the supplied records.",
                        "cases": [{"input": {"data": [{"id": "a"}], "options": {}},
                                   "expected": 1},
                                  {"input": {"data": [{"id": "a"}, {"id": "b"}], "options": {}},
                                   "expected": 2},
                                  {"input": {"data": [], "options": {}}, "expected": 0}]}
            with patch("viv_autonomy.ask_model", side_effect=[
                    json.dumps(proposal), json.dumps({"valid": True, "reason": "clear"})]) as ask:
                plan(store)
            context = json.loads(ask.call_args_list[0].args[0][1]["content"])
            self.assertEqual(context["last_rejection_diagnostic"]["raw_output"]["text"], malformed)
            self.assertIn("untrusted text", ask.call_args_list[0].args[0][0]["content"])

    def test_planner_summarizes_and_stops_replaying_exhausted_family_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            title = "Validate and Count Build Receipts"
            rejected = {"title": title, "requirement": "Count receipt booleans.", "cases": []}
            for index in range(3):
                store.event("plan_rejected", {
                    "proposal": rejected,
                    "proposal_sha256": str(index),
                    "reason": "Repeated planner family after invalid variants",
                })
            feedback = f"Rejected planner family '{title}' after 3 invalid variants."
            store.set("planning_feedback", feedback)
            store.set("planning_rejection_diagnostic", {
                "reason": feedback, "proposal_sha256": "2",
                "raw_output": {"trust": "untrusted_diagnostic_only",
                               "text": json.dumps(rejected)},
            })
            with patch("viv_autonomy.ask_model", return_value='{"malformed":true}') as ask:
                plan(store)

            prompt = json.loads(ask.call_args.args[0][1]["content"])
            self.assertNotIn(title, json.dumps(prompt["recent_rejected_proposals"]))
            self.assertEqual(prompt["exhausted_rejected_families"][0]["title"], title)
            self.assertEqual(prompt["exhausted_rejected_families"][0]["rejected_variants"], 3)
            self.assertEqual(prompt["last_rejection_diagnostic"]["raw_output"]["omitted"],
                             "exhausted_planner_family_output")
            self.assertNotIn(json.dumps(rejected), json.dumps(prompt))

    def test_planner_diagnostic_redacts_sensitive_and_bounds_long_text(self):
        sensitive = planner_output_diagnostic("api_key=sk-123456789012345678901234")
        self.assertNotIn("sk-123456789012345678901234", json.dumps(sensitive))
        self.assertIn("omitted", sensitive)
        bounded = planner_output_diagnostic("x" * 1400)
        self.assertEqual(len(bounded["text"]), 1200)
        self.assertTrue(bounded["truncated"])

    def test_truncated_planner_output_is_persisted_as_untrusted_rejection_feedback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            partial = '{"title":"Count receipts","requirement":'
            error = ModelResponseTruncated(partial, done_reason="length")
            with patch("viv_autonomy.ask_model", side_effect=error):
                plan(store)
            self.assertEqual(store.status()["tasks"], [])
            self.assertIn("truncated", store.get("planning_feedback"))
            diagnostic = store.get("planning_rejection_diagnostic")
            self.assertEqual(diagnostic["raw_output"]["text"], partial)
            self.assertEqual(diagnostic["raw_output"]["trust"], "untrusted_diagnostic_only")
            with store.connect() as con:
                row = con.execute("SELECT kind,data FROM events ORDER BY id DESC LIMIT 1").fetchone()
            self.assertEqual(row["kind"], "plan_rejected")
            self.assertEqual(json.loads(row["data"])["model_done_reason"], "length")

    def test_sensitive_partial_planner_output_is_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            partial = 'api_key=sk-123456789012345678901234'
            with patch("viv_autonomy.ask_model",
                       side_effect=ModelResponseTruncated(partial, done_reason="length")):
                plan(store)
            diagnostic = store.get("planning_rejection_diagnostic")["raw_output"]
            self.assertNotIn("sk-123456789012345678901234", json.dumps(diagnostic))
            self.assertEqual(diagnostic["omitted"], "credential_sensitive_or_binary_output")

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
            self.assertEqual(selected, {"kind": DEFAULT_TASK_LIST[-1], "id": DEFAULT_TASK_LIST[-1]})
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
        opener = Mock()
        opener.open.return_value = response
        with patch("viv_autonomy.file_lock", return_value=nullcontext()), \
             patch("viv_autonomy.Store") as control_store, \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime"), \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener",
                   return_value=opener):
            control_store.return_value.get.return_value = False
            self.assertEqual(ask_model([{"role": "user", "content": "one task"}]), "ok")
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body["keep_alive"], 0)

    def test_autonomous_queen_body_hold_prevents_ollama_request(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from viv_autonomy import ask_model
        hold = BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                                "reasons": ["privacy_unverified"]})
        with patch("viv_autonomy.file_lock", return_value=nullcontext()), \
             patch("viv_autonomy.Store") as control_store, \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime",
                   side_effect=hold), \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            control_store.return_value.get.return_value = False
            with self.assertRaises(BodyRuntimeHold):
                ask_model([{"role": "user", "content": "one task"}])
        opener.assert_not_called()

    def test_autonomous_queen_privacy_egress_hold_prevents_body_check_and_request(self):
        from aios_rebuild.main_core.mind_runtime_gate import PrivacyEgressHold
        from viv_autonomy import ask_model
        hold = PrivacyEgressHold({"allowed": False, "reason": "egress_endpoint_not_loopback"})
        with patch("viv_autonomy.file_lock", return_value=nullcontext()), \
             patch("viv_autonomy.Store") as control_store, \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_model_egress",
                   side_effect=hold), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime") as body, \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            control_store.return_value.get.return_value = False
            with self.assertRaises(PrivacyEgressHold):
                ask_model([{"role": "user", "content": "one task"}])
        body.assert_not_called()
        opener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
