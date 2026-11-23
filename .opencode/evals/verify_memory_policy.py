"""Deterministic controls for attention and memory policy. No model, no GPU."""
import sys

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
import turn_policy as tp  # noqa: E402
import memory_policy as mp  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# 1. Wake words and direct address.
for text, expected in [
    ("Viv, are you there?", True),
    ("Hey you.", True),
    ("Hey, what's up?", True),
    ("Hello, Viv.", True),
    ("The room is quiet. Sarah is alone.", False),
    ("Sarah told John to leave.", False),
]:
    check(f"wake {text!r} -> {expected}", mp.is_wake(text) == expected)

# 2. Intent-driven retrieval.
for text, expected in [
    ("Do you remember what I said?", True),
    ("What did I tell you earlier?", True),
    ("Remind me what we discussed.", True),
    ("What's the weather?", False),
    ("Pass the salt.", False),
]:
    check(f"intent {text!r} -> {expected}", mp.intent_needs_memory(text) == expected)

# 3. RAM buffer: every input observed; only addressed survives a dump.
buf = mp.InputBuffer(capacity=8)
ambient = buf.observe("The room is quiet. Sarah is alone.", tp.decide("The room is quiet. Sarah is alone."))
addressed = buf.observe("I lost my job.", tp.decide("I lost my job."))
check("buffer observes everything", len(buf.records) == 2)
check("buffer persistence candidates are addressed only",
      [r.text for r in buf.for_persistence()] == ["I lost my job."])
dumped = buf.dump_unaddressed()
check("buffer dumps ambient", dumped == 1 and len(buf.records) == 1
      and buf.records[0].text == "I lost my job.", f"dumped={dumped}")

# 4. Persistent store: fail closed without an authorizer, drop unaddressed.
store = mp.MemoryStore(authorize=None)
ok, why = store.persist(addressed)
check("persist without authorizer refused", ok is False and "authorizer" in why, why)
check("refused write left no record", store.records == [] and store.refused == 1)

store = mp.MemoryStore(authorize=lambda: False)
ok, why = store.persist(addressed)
check("persist with refusing authorizer refused", ok is False and "refused" in why, why)

store = mp.MemoryStore(authorize=lambda: True)
ok, why = store.persist(ambient)
check("unaddressed never persists", ok is False and store.dropped == 1, why)
ok, why = store.persist(addressed)
check("addressed persists with authorizer", ok is True and len(store.records) == 1, why)

# 5. Retrieval only on intent.
store.records.clear()
store.records.append({"text": "I lost my job yesterday.", "at": 0.0, "act": "disclosure"})
check("retrieval requires intent", store.retrieve("What's the weather?") == [])
hits = store.retrieve("Do you remember when I lost my job?")
check("retrieval finds the remembered input", len(hits) == 1 and "lost my job" in hits[0]["text"],
      str(hits))

print()
print("CONTROLS:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
raise SystemExit(0 if not fails else 1)
