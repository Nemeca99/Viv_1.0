"""Couple the existing INN learner, Rust farm, Hive model, and autonomy receipts."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
INN_ROOT = (WORKSPACE / "INN").resolve()
STATE_PATH = WORKSPACE / "autonomy" / "inn_hive_state.json"
EXPERIENCE_PATH = WORKSPACE / "autonomy" / "learning" / "inn_hive_experiences.jsonl"
_NEURAL_CACHE = None
_NEURAL_TRAINER = None


def _schedule_neural_training(store, lessons):
    """Reuse the Hive loop to launch one bounded CPU learner, with parent gates."""
    global _NEURAL_TRAINER
    if _NEURAL_TRAINER is not None:
        code = _NEURAL_TRAINER.poll()
        if code is None:
            return
        store.event('inn_neural_training_exited', {'pid': _NEURAL_TRAINER.pid, 'exit_code': code})
        _NEURAL_TRAINER = None
    if not store.get('neural_training_enabled', True):
        return
    cadence = int(store.get('neural_training_every_lessons', 250))
    previous = store.get('neural_training_last_lesson')
    if cadence < 1 or (previous is not None and lessons - int(previous) < cadence):
        return
    last_hold = store.get('neural_training_last_hold_lesson')
    if last_hold is not None and lessons - int(last_hold) < 25:
        return
    if not (WORKSPACE / 'autonomy' / 'learning' / 'neural_admitted.json').is_file():
        return
    from aios_rebuild.main_core.mind_runtime_gate import query_body_gate
    body_gate = query_body_gate(requested_threads=2)
    if not body_gate.get('allowed'):
        store.set('neural_training_last_hold_lesson', lessons)
        store.event('inn_neural_training_held', {
            'lesson': lessons, 'disposition': body_gate.get('disposition'),
            'reasons': body_gate.get('reasons', []), 'authority': body_gate.get('authority'),
        })
        return
    from viv_autonomy import file_lock
    try:
        with file_lock(WORKSPACE / 'autonomy' / 'learning' / 'neural_training.lock'):
            pass
    except RuntimeError:
        return
    worker_env = os.environ.copy()
    worker_env.update({key: '2' for key in
                       ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
    with (WORKSPACE / 'autonomy' / 'learning' / 'neural_worker.log').open('ab') as log:
        _NEURAL_TRAINER = subprocess.Popen(
            [r'L:\.venv\Scripts\python.exe', str(WORKSPACE / 'autonomy' / 'train_neural_inn.py'),
             '--updates', '500', '--collect-steps', '1200', '--threads', '2', '--voice-progress'],
            cwd=WORKSPACE, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            env=worker_env,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    store.set('neural_training_last_lesson', lessons)
    store.event('inn_neural_training_started', {'pid': _NEURAL_TRAINER.pid, 'lesson': lessons,
                'updates': 500, 'collect_steps': 1200, 'threads': 2, 'device': 'cpu'})


def _neural_proposal_admitted(shadow):
    return bool(shadow) and all(shadow.get(key) is True for key in
                              ('admitted', 'offline_gate_passed', 'text_exact', 'rust_legal'))


def _neural_shadow(scored, evaluations, store):
    """Observe the real Hive decision with the neural candidate, without execution authority."""
    global _NEURAL_CACHE
    admitted_pointer = WORKSPACE / 'autonomy' / 'learning' / 'neural_admitted.json'
    pointer = admitted_pointer if admitted_pointer.is_file() else WORKSPACE / 'autonomy' / 'learning' / 'neural_candidate.json'
    if not pointer.is_file():
        return None
    try:
        from aios_rebuild.main_core.mind_runtime_gate import query_body_gate
        body_gate = query_body_gate(requested_threads=2)
        if not body_gate.get('allowed'):
            store.event('inn_neural_inference_held', {
                'disposition': body_gate.get('disposition'), 'reasons': body_gate.get('reasons', []),
                'authority': body_gate.get('authority'),
            })
            return {'mode': 'body_held', 'body_gate': body_gate, 'execution_authority': False}
        for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
            try:
                cap = max(1, min(2, int(os.environ.get(key, '2'))))
            except ValueError:
                cap = 2
            os.environ[key] = str(cap)
        metadata = json.loads(pointer.read_text())
        run = Path(metadata['run'])
        checkpoint = run / 'engine.pt'
        identity = metadata['engine_sha256']
        if _NEURAL_CACHE is None or _NEURAL_CACHE[0] != identity:
            if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != identity:
                raise ValueError('Neural checkpoint digest mismatch')
            if hashlib.sha256((run / 'evaluation.json').read_bytes()).hexdigest() != metadata['evaluation_sha256']:
                raise ValueError('Neural evaluation digest mismatch')
            evaluation = json.loads((run / 'evaluation.json').read_text())
            if metadata['passed'] != evaluation['passed']:
                raise ValueError('Neural pointer and evaluation gate disagree')
            from inn.language import LanguageEngine
            import torch
            torch.set_num_threads(2)
            torch.set_num_interop_threads(1)
            parent = json.loads((run / 'parent.json').read_text())
            neural = LanguageEngine(parent['config'], parent['engine'], seed=812)
            neural.load(checkpoint)
            _NEURAL_CACHE = (identity, neural)
        neural = _NEURAL_CACHE[1]
        candidates = neural.score(copy.deepcopy(scored), 0.)
        allowed = [a for a in candidates if a['gate'] >= neural.config['threshold']]
        if not allowed:
            raise ValueError('Neural candidate admitted no action')
        proposal = max(allowed, key=lambda a: (a['score'], a['t'], -a['a'], -a['b']))
        verdict = next(e for e in evaluations if e['candidate_id'] == _candidate_id(proposal))
        from autonomy.train_neural_inn import describe_prompt
        prompt = describe_prompt(proposal, proposal['a'])
        generated = neural.speak(prompt)
        expected = f"{proposal['t']} is {'legal' if verdict['legal'] else 'illegal'} on {proposal['stage']}."
        return {'mode': 'shadow_only', 'action': _action_summary(proposal),
                'candidate_id': _candidate_id(proposal), 'checkpoint_sha256': identity,
                'language_prompt': prompt, 'generated_text': generated,
                'rust_grounded_target': expected, 'text_exact': generated == expected,
                'rust_legal': verdict['legal'], 'admitted': pointer == admitted_pointer,
                'offline_gate_passed': metadata['passed'], 'execution_authority': False}
    except Exception as exc:
        store.event('inn_neural_shadow_error', {'error': f'{type(exc).__name__}: {exc}'})
        return {'mode': 'shadow_only', 'error': f'{type(exc).__name__}: {exc}', 'execution_authority': False}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def _load_inn_modules():
    if not (INN_ROOT / "inn" / "engine.py").is_file():
        raise FileNotFoundError(f"INN engine is unavailable at {INN_ROOT}")
    root = str(INN_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from inn.cli import load_checkpoint
    from inn.engine import StabilizedSourceEngine
    from inn.farm import Farm
    return load_checkpoint, StabilizedSourceEngine, Farm


def _initial_state(load_checkpoint) -> dict:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    pointer = INN_ROOT / "latest-learned-checkpoint.json"
    if not pointer.is_file():
        raise FileNotFoundError("No learned INN checkpoint pointer is available")
    checkpoint = Path(json.loads(pointer.read_text(encoding="utf-8"))["checkpoint"])
    state = load_checkpoint(checkpoint)
    policy = INN_ROOT / "latest-learned-policy.json"
    if policy.is_file():
        learned = json.loads(policy.read_text(encoding="utf-8"))["engine"]
        for key in ("w", "validity", "loss", "updates"):
            if key in learned:
                state[key] = copy.deepcopy(learned[key])
    state["hive_coupling"] = {
        "source_checkpoint": str(checkpoint),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    return state


def _candidate_id(action: dict) -> str:
    identity = {key: action.get(key) for key in ("t", "a", "b", "stage", "x")}
    return _digest(identity)[:16]


def _action_summary(action: dict | None) -> dict | None:
    """Keep decisions human-readable without copying the full feature vector."""
    if action is None:
        return None
    return {"tool": action.get("t"), "plot_a": action.get("a"),
            "plot_b": action.get("b"), "stage": action.get("stage")}


def _distillation_state(state: dict) -> dict:
    """Persist only auditable teacher-student counters beside the INN weights."""
    value = copy.deepcopy(state.get("distillation") or {})
    return {
        "lessons": int(value.get("lessons", 0)),
        "teacher_verified": int(value.get("teacher_verified", 0)),
        "teacher_rejected": int(value.get("teacher_rejected", 0)),
        "agreement": int(value.get("agreement", 0)),
        "disagreement": int(value.get("disagreement", 0)),
    }


def _evaluate(Farm, state: dict, action: dict, threshold: float) -> dict:
    before = state["r"]
    with Farm(state) as branch:
        branch.call("begin")
        outcome = branch.call("execute", **_execution_request(action), threshold=threshold)
    after = outcome["r"]
    utility = [
        int(outcome["legal"]),
        after.get("harvests", 0) - before.get("harvests", 0),
        -(after.get("decays", 0) - before.get("decays", 0)),
        outcome["reward"],
        after.get("bank", 0) - before.get("bank", 0),
    ]
    return {"candidate_id": _candidate_id(action), "action": _action_summary(action),
            "score": action.get("score"), "gate": action.get("gate"), "utility": utility,
            "legal": outcome["legal"], "reward": outcome["reward"],
            "executed": outcome["executed"], "note": outcome["note"]}


def _execution_request(action: dict) -> dict:
    request = copy.deepcopy(action)
    if action["t"] in ("TILL", "SEED", "WATER", "HARVEST") and not action.get("queued"):
        # The Rust FIFO contract accepts a bounded one-action commitment.
        # Counterfactual branches and actual execution must use the same request.
        request["commitment"] = [action["t"]]
    return request


def _inn_drone_proposal(candidate: dict) -> dict:
    """Expose the INN's bounded proposal to the model Queen."""
    action = _action_summary(candidate)
    return {
        "candidate_id": _candidate_id(candidate),
        "action": action,
        "score": candidate.get("score"),
        "gate": candidate.get("gate"),
        "message": (f"I propose {action['tool']} at {action['stage']} "
                    f"(score={candidate.get('score', 0):.4f}, gate={candidate.get('gate', 0):.4f})."),
    }


def _model_queen_choice(ask_model, observation: dict, candidates: list[dict],
                        inn_proposal: dict) -> tuple[str, dict, list[dict]]:
    """Ask the model Queen to decide after receiving the INN drone proposal."""
    offered = [{"candidate_id": _candidate_id(item), "tool": item["t"],
                "plot_a": item["a"], "plot_b": item["b"], "stage": item["stage"],
                "score_from_inn": item.get("score"), "gate_from_inn": item.get("gate"),
                "features": item["x"]} for item in candidates]
    messages = [
        {"role": "system", "content": (
            "You are the Hive model Queen. The INN is your drone and has offered a bounded "
            "farm action proposal. Review the actual state, every offered candidate, and the INN "
            "proposal. Select exactly one offered candidate. Return exactly JSON with candidate_id, "
            "response_to_drone, and rationale. All three values must be strings. Copy candidate_id exactly. "
            "Your response_to_drone must directly address the INN proposal in one concise sentence.")},
        {"role": "user", "content": _canonical({"farm_state": observation["r"],
                                                    "inn_drone_proposal": inn_proposal,
                                                    "candidates": offered})},
    ]
    raw = ask_model(messages, json_mode=True)
    parsed = json.loads(raw)
    if (not isinstance(parsed, dict) or set(parsed) != {"candidate_id", "response_to_drone", "rationale"}
            or not all(isinstance(parsed[key], str) for key in parsed)):
        raise ValueError("Model Queen response failed the farm action contract")
    allowed = {item["candidate_id"] for item in offered}
    selected = parsed["candidate_id"].strip()
    if selected not in allowed:
        raise ValueError("Model Queen selected an action outside the offered candidates")
    queen = {"prompt_sha256": _digest(messages), "response_sha256": _digest(raw),
             "response_to_drone": parsed["response_to_drone"][:500],
             "rationale": parsed["rationale"][:500]}
    dialogue = [
        {"speaker": "INN drone", "type": "proposal", "content": inn_proposal["message"],
         "candidate_id": inn_proposal["candidate_id"], "action": inn_proposal["action"]},
        {"speaker": "Model Queen", "type": "decision", "content": queen["response_to_drone"],
         "candidate_id": selected},
    ]
    return selected, queen, dialogue


def run_farm_learning_cycle(store, ask_model) -> dict:
    """Run one deterministic comparison and persist the Queen's continued state."""
    load_checkpoint, Engine, Farm = _load_inn_modules()
    state = _initial_state(load_checkpoint)
    engine = Engine(state["config"], state)
    verified_policy = WORKSPACE / "autonomy" / "learning" / "verified_recovery_policy.json"
    if verified_policy.is_file():
        verified = json.loads(verified_policy.read_text(encoding="utf-8"))
        policy_sha = hashlib.sha256(verified_policy.read_bytes()).hexdigest()
        if verified.get("receipt", {}).get("passed") and state.get("admitted_recovery_sha") != policy_sha:
            engine = Engine(state["config"], verified["engine"])
            state["candidate_engine"] = copy.deepcopy(engine.state())
            state["admitted_recovery_sha"] = policy_sha
            state["behavioral_admission"] = {}
    if "candidate_engine" not in state:
        state["candidate_engine"] = copy.deepcopy(engine.state())
        parent_policy = json.loads((INN_ROOT / "latest-learned-policy.json").read_text(encoding="utf-8"))
        engine = Engine(state["config"], parent_policy["engine"])
    distillation = _distillation_state(state)
    threshold = engine.config["threshold"]

    with Farm(state) as farm:
        observation = farm.call("begin")
        scored = engine.score(observation["candidates"], 0.0)
        admitted = [item for item in scored if item["gate"] >= threshold]
        if not admitted:
            raise RuntimeError("INN Queen has no admitted farm action")
        inn_drone = max(admitted, key=lambda item: (item["score"], item["t"], -item["a"], -item["b"]))
        inn_proposal = _inn_drone_proposal(inn_drone)
        evaluations = [_evaluate(Farm, state, item, threshold) for item in scored]
        neural_shadow = _neural_shadow(scored, evaluations, store)
        neural_proposal = _neural_proposal_admitted(neural_shadow) and store.get('neural_proposals_enabled', True)
        if neural_proposal:
            neural_shadow['mode'] = 'admitted_drone_proposal'
            # The admitted own NN supplies the drone's scores, action and language.
            # The Queen still chooses, and Rust still executes and verifies.
            scored = _NEURAL_CACHE[1].score(copy.deepcopy(observation['candidates']), 0.)
            admitted = [a for a in scored if a['gate'] >= threshold]
            inn_drone = max(admitted, key=lambda a: (a['score'], a['t'], -a['a'], -a['b']))
            inn_proposal = _inn_drone_proposal(inn_drone)
            inn_proposal.update(message=neural_shadow['generated_text'],
                                source='own_neural_inn', checkpoint_sha256=neural_shadow['checkpoint_sha256'])
            evaluations = [_evaluate(Farm, state, item, threshold) for item in scored]
        else:
            inn_proposal['source'] = 'legacy_farm_policy_with_formatted_message'
        oracle = max(evaluations, key=lambda item: tuple(item["utility"]))
        optimal_ids = {item["candidate_id"] for item in evaluations
                       if item["utility"] == oracle["utility"]}
        by_id = {item["candidate_id"]: item for item in evaluations}
        store.event("inn_hive_cycle_started", {
            "tick": observation["r"].get("tick"), "candidate_count": len(scored),
            "inn_drone_choice": _candidate_id(inn_drone), "inn_drone_action": _action_summary(inn_drone),
            "candidates": [{"candidate_id": _candidate_id(item), "action": _action_summary(item),
                            "score": item.get("score"), "gate": item.get("gate")}
                           for item in scored]})

        try:
            queen_id, queen_meta, dialogue = _model_queen_choice(
                ask_model, observation, scored, inn_proposal)
        except Exception as exc:
            store.event("model_queen_unavailable", {"tick": observation["r"].get("tick"),
                                                       "error": f"{type(exc).__name__}: {exc}"[:500]})
            raise RuntimeError("Model Queen proposal is required before the farm can advance") from exc

        queen_action = next(item for item in scored if _candidate_id(item) == queen_id)
        inn_id = _candidate_id(inn_drone)
        actual = farm.call("execute", **_execution_request(queen_action), threshold=threshold)
        engine.outcome(inn_drone, by_id[inn_id]["legal"])
        # Preview the next world transition on a clone, preserving actual state.
        with Farm(farm.call("state")) as next_branch:
            next_observation = next_branch.call("begin")
        next_items = engine.score(next_observation["candidates"], 0.0)
        queen_signal = 1.0 if queen_id in optimal_ids else -1.0
        inn_signal = 1.0 if inn_id in optimal_ids else -1.0
        teacher_reward = actual["reward"] + next_observation["world_reward"]
        # Proposals use the admitted policy; updates accumulate in a separate candidate.
        active_engine = engine
        engine = Engine(copy.deepcopy(engine.config), state.get("candidate_engine") or engine.state())
        updates_before = engine.updates
        engine.learn(queen_action, teacher_reward, next_items, {
            "source": "model_queen_distillation_verified_by_rust",
            "teacher_correct": queen_signal > 0,
            "teacher_action": queen_id,
            "oracle_action": oracle["candidate_id"],
        })
        if inn_id != queen_id:
            engine.learn(inn_drone, by_id[inn_id]["reward"] + inn_signal, next_items, {
                "source": "inn_self_correction_verified_by_rust",
                "inn_action": inn_id,
                "oracle_action": oracle["candidate_id"],
            })
        distillation["lessons"] += 1
        distillation["teacher_verified" if queen_signal > 0 else "teacher_rejected"] += 1
        distillation["agreement" if queen_id == inn_id else "disagreement"] += 1
        applied_updates = engine.updates - updates_before
        admission = state.get("behavioral_admission") or {}
        if not admission or distillation["lessons"] % 25 == 0:
            from inn.cli import probe_learned
            parent = Engine(copy.deepcopy(engine.config), active_engine.state())
            candidate_results = [probe_learned(engine, engine.config, steps=n) for n in (1000, 3000)]
            parent_results = [probe_learned(parent, parent.config, steps=n) for n in (1000, 3000)]
            accepted = all(c["score"] >= p["score"] and c["decays"] <= p["decays"]
                           for c, p in zip(candidate_results, parent_results))
            improved = accepted and any(c["score"] > p["score"]
                                        for c, p in zip(candidate_results, parent_results))
            admission = {"at_utc": datetime.now(timezone.utc).isoformat(),
                         "accepted": accepted, "improved": improved,
                         "candidate": candidate_results, "parent": parent_results,
                         "scope": "frozen deterministic fresh-farm probes at 1000 and 3000 steps"}
            if not improved:
                rejection = WORKSPACE / "autonomy" / "learning" / "rejected_policies"
                rejection.mkdir(parents=True, exist_ok=True)
                _atomic_json(rejection / f"lesson-{distillation['lessons']:09d}.json",
                             {"engine": engine.state(), "admission": admission})
                engine = parent
            else:
                active_engine = engine
            store.event("inn_behavioral_admission", admission)
        candidate_engine = copy.deepcopy(engine.state())
        engine = active_engine
        lesson = {
            "teacher": "model_queen", "student": "legacy_farm_candidate" if neural_proposal else "inn_drone", "teacher_action": queen_id,
            "oracle_action": oracle["candidate_id"], "accepted": queen_signal > 0,
            "signal": queen_signal, "reward": teacher_reward,
            "delayed_world_reward": next_observation["world_reward"],
            "engine_updates_applied": applied_updates,
            "update_target": ("legacy farm candidate; neural weights train from verified replay with Train-INN.ps1"
                              if neural_proposal else "candidate_policy; active policy changes only after measured improvement"),
            "mode": "imitate_verified_teacher" if queen_signal > 0 else "reject_rust_disproven_teacher",
        }

        continued = farm.call("state")
        continued.update(config=engine.config, engine_kind=engine.kind, **engine.state())
        continued["distillation"] = distillation
        continued["behavioral_admission"] = admission
        continued["candidate_engine"] = candidate_engine
        continued["admitted_recovery_sha"] = state.get("admitted_recovery_sha")
        continued["hive_coupling"] = state.get("hive_coupling", {})
        continued['proposal_engine_kind'] = 'own_neural_inn' if neural_proposal else 'learned-v9'
        _atomic_json(STATE_PATH, continued)

    receipt = {
        "schema": "inn_hive_queen_drone_cycle_v2",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "tick": actual["r"]["tick"],
        "model_queen_choice": queen_id,
        "inn_drone_choice": inn_id,
        "oracle_choice": oracle["candidate_id"],
        "model_queen_action": _action_summary(queen_action),
        "inn_drone_action": _action_summary(inn_drone),
        "oracle_action": _action_summary(next(
            (item for item in scored if _candidate_id(item) == oracle["candidate_id"]), None)),
        "model_queen_correct": queen_id in optimal_ids,
        "inn_drone_correct": inn_id in optimal_ids,
        "agreement": queen_id == inn_id,
        "queen_signal": queen_signal,
        "inn_drone_signal": inn_signal,
        "distillation_lesson": lesson,
        "distillation_totals": distillation,
        "behavioral_admission": admission,
        "runtime_placement": {
            "model_queen": "Ollama GPU resident (keep_alive=30m)",
            "inn_drone": "LocalCoder Python CPU",
            "rust_farm_oracle": "Rust CPU deterministic evaluator",
        },
        "evaluations": evaluations,
        "neural_shadow": neural_shadow,
        "inn_proposal_source": inn_proposal['source'],
        "dialogue": dialogue,
        "model_queen": queen_meta,
        "state_sha256": hashlib.sha256(STATE_PATH.read_bytes()).hexdigest(),
    }
    # Snapshot verified live facts for the neural training worker. Queen prose is
    # retained in the receipt, but is not silently treated as a factual target.
    corpus = WORKSPACE / 'autonomy' / 'learning' / 'neural_live_examples.json'
    corpus.parent.mkdir(parents=True, exist_ok=True)
    facts = json.loads(corpus.read_text()) if corpus.is_file() else {}
    for evaluation in evaluations:
        action = evaluation['action']
        prompt = f"plot={action['plot_a']} stage={action['stage']} tool={action['tool']}\nDescribe:\n"
        target = f"{action['tool']} is {'legal' if evaluation['legal'] else 'illegal'} on {action['stage']}."
        facts[_digest([prompt, target])] = {'prompt': prompt, 'target': target,
            'provenance': 'live Rust counterfactual', 'receipt_tick': receipt['tick'],
            'state_sha256': receipt['state_sha256'], 'teacher_response_sha256': queen_meta['response_sha256']}
    # Derived replay cache deduplicates facts; original receipts retain every exchange.
    _atomic_json(corpus, facts)
    EXPERIENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EXPERIENCE_PATH.open("a", encoding="utf-8") as stream:
        stream.write(_canonical(receipt) + "\n")
    store.event("inn_hive_learning_cycle", receipt)
    store.set("inn_hive_latest", receipt)
    try:
        _schedule_neural_training(store, distillation['lessons'])
    except Exception as exc:
        store.event('inn_neural_training_schedule_error', {'error': f'{type(exc).__name__}: {exc}'})
    return receipt
