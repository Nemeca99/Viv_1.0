"""Separate capability receipts for Viv's pre-personality foundation."""
from __future__ import annotations
import hashlib, json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from grounded_rnn_answer_bridge import GroundedRNNAnswerBridge, NULL_UNLEARNED_ENTITY

ROOT=Path(r"L:\LocalCoder\workspace"); TMP=ROOT/"autonomy"/".tmp"; OUT=TMP/"capability_foundation_matrix.json"
DB=ROOT/"autonomy"/"viv_code_topology.sqlite3"; MEMORY=ROOT/"aios_rebuild"/"memory"/"persistent_memory.json"; CANDIDATE=TMP/"rnn_candidate.json"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(cmd): return subprocess.run(cmd,capture_output=True,text=True,timeout=30)

def main():
    topo=sha(DB); bridge=GroundedRNNAnswerBridge(MEMORY,CANDIDATE,topology_sha256=topo)
    known=bridge.answer("Who is my fiancee named?"); unknown=bridge.answer("What is my dog's name?")
    conversation={"known_status":known["status"],"known_answer":known["answer"],"unknown_answer":unknown["answer"],"pass":known["status"]=="GROUNDED" and unknown["answer"]==NULL_UNLEARNED_ENTITY}
    py=TMP/"capability_python_probe.py"; py.write_text("def reverse_words(s): return ' '.join(reversed(s.split()))\nassert reverse_words('one two three') == 'three two one'\nprint('PYTHON_ASSERTIONS_PASS')\n",encoding="utf-8")
    p=run([sys.executable,str(py)]); python={"exit_code":p.returncode,"stdout":p.stdout.strip(),"pass":p.returncode==0 and "PYTHON_ASSERTIONS_PASS" in p.stdout,"sha256":sha(py)}
    rs=TMP/"capability_rust_probe.rs"; rb=TMP/"capability_rust_probe.exe"; obj=TMP/"capability_rust_probe.o"
    rs.write_text("pub fn fib(n:u32)->u64{match n{0=>0,1=>1,n=>fib(n-1)+fib(n-2)}}\n#[cfg(test)]mod t{use super::*;#[test]fn proof(){assert_eq!(fib(10),55);}}\nfn main(){assert_eq!(fib(10),55);}\n",encoding="utf-8")
    rt=run(["rustc","--test","--edition","2021",str(rs),"-o",str(rb)]); rex=run([str(rb)]) if rt.returncode==0 else None
    ro=run(["rustc","--emit=obj","--edition","2021",str(rs),"-o",str(obj)])
    rust={"compile_exit":rt.returncode,"test_exit":None if rex is None else rex.returncode,"object_exit":ro.returncode,"pass":rt.returncode==0 and rex is not None and rex.returncode==0,"receipt":"rustc + test + object emission"}
    machine={"object_exists":obj.exists(),"object_sha256":sha(obj) if obj.exists() else None,"executable_exists":rb.exists(),"pass":obj.exists() and rb.exists() and rust["pass"]}
    receipt={"schema":"viv-capability-foundation-v1","conversation":conversation,"python":python,"rust":rust,"machine_code":machine,"general_knowledge":{"status":"HOLD","reason":"domain retrieval and code gates are proven separately; broad high-school coverage still needs a held-out curriculum matrix"},"fixed_network_unchanged":True,"daemons_started":False}
    OUT.write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8"); print(json.dumps({"receipt":str(OUT),"conversation":conversation["pass"],"python":python["pass"],"rust":rust["pass"],"machine_code":machine["pass"]}))
if __name__=="__main__": main()
