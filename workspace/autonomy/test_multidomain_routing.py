import urllib.request
import json
import time

queries = [
    "Who is Nikola Tesla",
    "In biology, who was Nikola Tesla?",
    "In physics, who was Nikola Tesla?",
    "In history, who was Nikola Tesla?",
    "In engineering, who was Nikola Tesla?",
    "In physics, what is Tesla?",
    "In physics, what is a binary search tree?",
    "Who was Emperor Zarg of Mars in 1842?"
]

print("================================================================================")
print("  MULTI-DOMAIN ROUTING & GAUGE TRANSITION EMPIRICAL BENCHMARK (PORT 1235)")
print("================================================================================")

for q in queries:
    payload = {
        "messages": [{"role": "user", "content": q}],
        "temperature": 0.0,
        "persona": "jarvis"
    }
    req = urllib.request.Request(
        "http://127.0.0.1:1235/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            data = json.loads(resp.read().decode("utf-8"))
            trace = data.get("enigma_trace", {})
            content = data["choices"][0]["message"]["content"]
            print(f"\n[QUERY]: '{q}'")
            print(f"  -> Latency: {elapsed_ms:.1f} ms (Engine Reported: {trace.get('latency_ms')} ms)")
            print(f"  -> Domain: {trace.get('domain')} (Gauge {trace.get('gauge_shift')}) | Gate: {trace.get('gate_status')}")
            print(f"  -> Rerouted: {trace.get('rotor_rerouted')} | Matched Entity: '{trace.get('matched_entity')}'")
            if trace.get("reroute_trace"):
                print(f"  -> Reroute Diagnostic: {trace['reroute_trace'].get('diagnostic')}")
            hops = trace.get("hop_chain", [])
            if hops:
                print(f"  -> Primary Hop: {hops[0]}")
            print(f"  -> Response Preview: {content[:200]}...")
    except Exception as e:
        print(f"\n[QUERY]: '{q}' -> ERROR: {e}")
