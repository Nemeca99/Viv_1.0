from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext
from io import BytesIO
import json
from unittest.mock import patch

from viv_autonomy import (DEFAULT_TASK_LIST, Store, choose_task, file_lock,
                          plan, run_autonomous_task, seed_task, validate_spec)
from viv_project_builder import queue_project, scheduler_spec


class DurableAutonomyTests(unittest.TestCase):
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
