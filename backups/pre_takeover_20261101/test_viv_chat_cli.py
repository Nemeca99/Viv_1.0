"""Local tests for Viv's user/Mind/Swarm authorization boundary."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from io import BytesIO
import io
import json
from unittest.mock import Mock, patch

from viv_chat_cli import (
    CHAT_TOOL_CATALOG,
    TOOL_DECISION_SCHEMA,
    authorize_search,
    cited_observation_lines,
    dispatch_drive_observation,
    explicit_user_search,
    next_curiosity_query,
    search_workspace_filenames,
    tool_catalog_for_prompt,
    validate_tool_request,
)


class ToolAuthorizationTests(unittest.TestCase):
    def test_tool_purpose_catalog_is_complete_and_matches_dispatch_schema(self):
        schema_names = TOOL_DECISION_SCHEMA["properties"]["tool_request"]["properties"]["name"]["enum"]
        prompt_cards = json.loads(tool_catalog_for_prompt())

        self.assertEqual(schema_names, list(CHAT_TOOL_CATALOG))
        self.assertEqual([card["name"] for card in prompt_cards], schema_names)
        for card in prompt_cards:
            with self.subTest(tool=card["name"]):
                self.assertTrue(card["purpose"])
                self.assertTrue(card["input"])
                self.assertTrue(card["effect"])
                self.assertTrue(card["boundary"])

    def test_tool_validator_rejects_non_string_names(self):
        with self.assertRaises(ValueError):
            validate_tool_request({"name": [], "query": ""})

    def test_pc_content_is_only_sent_to_a_ready_drive_agent(self):
        from swarm_adapters.drive_stacks import runtime
        with patch.object(runtime, "registered_drives", return_value=("C", "L")), \
             patch.object(runtime, "resolve_stack", side_effect=[
                 {"ready": False, "reason": "missing C LoRA", "scheme_sha256": "c" * 64},
                 {"ready": True, "scheme_sha256": "l" * 64},
             ]), \
             patch("workspace_observer.search_pc_content", return_value={
                 "matches": [{"path": "L:\\safe.md", "line": 3,
                              "sha256": "a" * 64, "snippet": "agent-visible source"}],
                 "truncated": False,
             }) as search, \
             patch("autonomy.learning_corpus.seen_evidence_keys", return_value=set()), \
             patch("autonomy.learning_corpus.capture_evidence"), \
             patch.object(runtime, "generate_for_drive", return_value={
                 "answer": "L specialist report L:\\safe.md:3",
                 "receipt": {"drive": "L", "adapter_ids": ["L-master"]},
             }) as generate:
            result = dispatch_drive_observation("search_pc_content", "safe.md")
        self.assertEqual([call.kwargs["drive"] for call in search.call_args_list], ["L"])
        self.assertEqual(generate.call_args.args[0], "L")
        self.assertEqual(result["deferred_drives"][0]["drive"], "C")
        self.assertNotIn("agent-visible source", json.dumps(result["deferred_drives"]))
        self.assertEqual(result["agent_reports"][0]["receipt"]["drive"], "L")

    def test_curiosity_query_rotates_and_uses_discovered_project_names(self):
        first = next_curiosity_query([])
        self.assertNotEqual(next_curiosity_query([first]), first)
        history = []
        for _ in range(7):
            history.append(next_curiosity_query(history, [r"L:\Projects\Viv_Core"]))
        self.assertEqual(len(set(history)), len(history))
        self.assertTrue(any("Viv Core" in query for query in history))

    def test_only_exact_explicit_search_command_auto_approves(self):
        self.assertEqual(explicit_user_search("!search hello.py"), "hello.py")
        self.assertEqual(explicit_user_search("please find hello.py"), None)
        self.assertEqual(authorize_search("!search hello.py", "hello.py"), (True, "explicit_user_command"))
        self.assertEqual(
            authorize_search("!search hello.py", "hello", input_fn=lambda _: ""),
            (False, "human_denied"),
        )

    def test_other_mind_proposals_require_human_yes(self):
        self.assertEqual(
            authorize_search("Find the matching source file", "hello.py", input_fn=lambda _: "yes"),
            (True, "human_approval"),
        )
        self.assertEqual(
            authorize_search("Find the matching source file", "hello.py", input_fn=lambda _: "no"),
            (False, "human_denied"),
        )

    def test_tool_contract_rejects_paths_and_patterns(self):
        self.assertEqual(validate_tool_request({"name": "none", "query": ""}), ("none", ""))
        for bad in ("../secret", "C:\\Users", "*.py", "folder/name"):
            with self.subTest(query=bad), self.assertRaises(ValueError):
                validate_tool_request({"name": "search_workspace_filename", "query": bad})

    def test_read_only_observer_tools_and_exact_evidence_citations(self):
        self.assertEqual(validate_tool_request({"name": "inventory_pc_sources", "query": ""}),
                         ("inventory_pc_sources", ""))
        self.assertEqual(validate_tool_request({"name": "search_pc_content", "query": "Viv learning"}),
                         ("search_pc_content", "Viv learning"))
        evidence = [{"path": r"L:\AIOS\README.md", "line": 27}]
        self.assertEqual(cited_observation_lines(r"Observed L:\AIOS\README.md:27", evidence), evidence)
        self.assertEqual(cited_observation_lines("I read the README.", evidence), [])

    def test_chat_model_is_unloaded_after_each_prompt(self):
        from viv_chat_cli import ask_mind
        opener = Mock()
        opener.open.return_value = BytesIO(b'{"message":{"content":"ok"}}')
        with patch("viv_chat_cli.file_lock", return_value=nullcontext()), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime"), \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener",
                   return_value=opener):
            self.assertEqual(ask_mind([{"role": "user", "content": "hello"}]), "ok")
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body["keep_alive"], 0)

    def test_chat_body_hold_prevents_ollama_request(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from viv_chat_cli import ask_mind
        hold = BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                                "reasons": ["privacy_unverified"]})
        with patch("viv_chat_cli.file_lock", return_value=nullcontext()), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime",
                   side_effect=hold), \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            with self.assertRaises(BodyRuntimeHold):
                ask_mind([{"role": "user", "content": "hello"}])
        opener.assert_not_called()

    def test_chat_privacy_egress_hold_prevents_body_check_and_request(self):
        from aios_rebuild.main_core.mind_runtime_gate import PrivacyEgressHold
        from viv_chat_cli import ask_mind
        hold = PrivacyEgressHold({"allowed": False, "reason": "egress_endpoint_not_loopback"})
        with patch("viv_chat_cli.file_lock", return_value=nullcontext()), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_model_egress",
                   side_effect=hold), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime") as body, \
             patch("aios_rebuild.main_core.mind_runtime_gate.urllib.request.build_opener") as opener:
            with self.assertRaises(PrivacyEgressHold):
                ask_mind([{"role": "user", "content": "hello"}])
        body.assert_not_called()
        opener.assert_not_called()

    def test_voice_runtime_hold_prevents_model_unload_and_tts_launch(self):
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold
        from viv_chat_cli import speak_viv
        hold = BodyRuntimeHold({"allowed": False, "disposition": "HOLD_MIND_RUNTIME",
                                "reasons": ["privacy_core_unverified"]})
        output = io.StringIO()
        with patch("viv_chat_cli.file_lock", return_value=nullcontext()), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime",
                   side_effect=hold), \
             patch("viv_chat_cli.subprocess.run") as process, \
             redirect_stdout(output):
            speak_viv("A bounded voice test.")
        process.assert_not_called()
        self.assertIn("[Voice Body HOLD]", output.getvalue())

    def test_voice_child_inherits_two_thread_budget(self):
        from viv_chat_cli import speak_viv
        with patch("viv_chat_cli.file_lock", return_value=nullcontext()), \
             patch("aios_rebuild.main_core.mind_runtime_gate.require_body_runtime"), \
             patch("viv_chat_cli.subprocess.run") as process:
            speak_viv("A bounded voice test.")
        self.assertEqual(process.call_count, 2)
        child_environment = process.call_args_list[1].kwargs["env"]
        for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            self.assertEqual(child_environment[variable], "2")

    def test_search_is_filename_only_and_prunes_sensitive_or_large_dirs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "src").mkdir()
            (root / "memory").mkdir()
            (root / "src" / "hello.py").write_text("safe", encoding="utf-8")
            (root / "memory" / "secret_hello.py").write_text("secret", encoding="utf-8")
            results = search_workspace_filenames("hello.py", root=root)
            self.assertEqual(results, [str(root / "src" / "hello.py")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
