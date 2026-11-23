"""Explicit foreground CLI for Viv's grounded capability router."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from viv_capability_router import VivCapabilityRouter
from deterministic_containment import ContainmentEngine,SQLiteArticleCartridge
from viv_internal_reflection import InternalReflection

PHYSICS=Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3")
REASON_RECEIPT=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_reasoning_probe.json")

def handle(text,router,knowledge):
    if text.startswith("/reflect "):
        question=text[9:]
        primitive=InternalReflection().reflect_loop(question)
        if primitive["status"]=="VERIFIED": return primitive
        return InternalReflection().reflect_with_cartridge(question, knowledge)
    if text.startswith("/reason"):
        if not REASON_RECEIPT.exists(): return {"status":"HOLD","reason":"reasoning receipt missing"}
        data=json.loads(REASON_RECEIPT.read_text(encoding="utf-8"))
        return {"status":data["status"],"answer":data["composition"]["accepted_claim"],"receipt":{"schema":data["schema"],"gate":data["composition"]["gate"],"retrieval_rows":data["retrieval"]["rows"],"held_out":data["held_out"]["pass"]},"rejected_hypothesis":data["composition"]["rejected_claim"]}
    if text.startswith("/probe "):
        capability=text.split(None,1)[1].casefold()
        matrix=Path(r"L:\LocalCoder\workspace\autonomy\.tmp\capability_foundation_matrix.json")
        if not matrix.exists(): return {"status":"HOLD","reason":"capability receipt missing"}
        data=json.loads(matrix.read_text(encoding="utf-8")); section={"python":"python","rust":"rust","machine":"machine_code"}.get(capability)
        return {"status":"GATE_PASS" if section and data.get(section,{}).get("pass") else "GATE_HOLD","capability":section,"receipt":str(matrix)}
    if text=="/identity": return {"status":"IDENTITY_CANDIDATE","profile":router.personality,"authority":"Architect and deterministic gates"}
    if text.startswith("/knowledge "):
        result=knowledge.query(text[11:]); receipt=dict(result.receipt); receipt["trace_length"]=len(result.trace); receipt.pop("instruction_trace",None)
        return {"status":result.state,"answer":result.answer[:800],"receipt":receipt,"provenance":None if not result.candidates else {"cartridge":result.candidates[0].cartridge,"row_id":result.candidates[0].row_id}}
    return router.answer(text)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--once"); args=ap.parse_args()
    router=VivCapabilityRouter(); knowledge=ContainmentEngine([SQLiteArticleCartridge("wiki_physics",PHYSICS)])
    if args.once: print(json.dumps(handle(args.once,router,knowledge),indent=2)); return
    print("Viv foreground CLI. /knowledge <query>, /reflect <question>, /identity, /quit")
    for line in sys.stdin:
        text=line.strip()
        if not text: continue
        if text=="/quit": print(json.dumps({"status":"STOPPED"})); break
        print(json.dumps(handle(text,router,knowledge),indent=2),flush=True)
if __name__=="__main__": main()
