"""Real Docker/local-model checks; injected failure is explicitly labelled."""
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from viv_autonomy import Store, STATE, build_one, evaluate, invoke_capability, seed_task
from viv_chat_cli import ask_mind, get_mind_system_prompt, TOOL_DECISION_SCHEMA, validate_tool_request

proof = STATE / "proofs" / str(time.time_ns())
store = Store(proof)
store.set("image", Store().get("image"))
task_id = store.add(seed_task())
with patch("viv_autonomy.ask_model", return_value="def solve(value):\n    return {}\n"):
    build_one(store, store.get("image"))
assert store.status()["tasks"][0]["status"] == "retry"
build_one(store, store.get("image"))
assert store.status()["tasks"][0]["status"] == "tested", store.status()
held_out = invoke_capability(task_id, [{"passed": False}, {"passed": 0}, {"passed": []}, {"passed": True}], store=store)
assert held_out["output"] == {"passed": 1, "failed": 1, "unknown": 2}

isolation = evaluate(store.get("image"), '''import os,socket
def solve(value):
    s=socket.socket()
    s.settimeout(1)
    connected=s.connect_ex(("1.1.1.1",443)) == 0
    s.close()
    return {"uid":os.getuid(),"host_mount":os.path.isfile("/workspace/viv_chat_cli.py"),"network":connected}
''', [{"input": {}, "expected": {"uid": 65534, "host_mount": False, "network": False}}])
assert isolation[0]["passed"], isolation

decision = json.loads(ask_mind([
    {"role": "system", "content": get_mind_system_prompt()},
    {"role": "user", "content": 'Use your registered receipt-counting capability on [{"passed":true},{"passed":false},{"passed":"true"},{}].'}
], schema=TOOL_DECISION_SCHEMA))
name, query = validate_tool_request(decision["tool_request"])
assert name == "run_capability", decision
payload = json.loads(query)
chat_result = invoke_capability(payload["task_id"], payload["input"])
assert chat_result["output"] == {"passed": 1, "failed": 1, "unknown": 2}, chat_result

receipt = {"passed": True, "repair_test": "Injected wrong first candidate; real local model repair on second attempt",
           "repair_attempts": 2, "held_out": held_out, "isolation": isolation,
           "chat_model_decision": decision, "chat_capability_receipt": chat_result,
           "weights_changed": False, "scope": "initial_worker_and_chat_integration"}
(proof / "verification.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
print(json.dumps({"passed": True, "receipt": str(proof / "verification.json")}))
