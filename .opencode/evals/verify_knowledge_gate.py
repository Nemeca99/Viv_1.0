"""Deterministic controls for the knowledge gate. No model, no GPU."""
import sys

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
import memory_policy as mp  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not cond:
        fails.append(name)


# Verified and reasonable: learned, persisted.
gate = mp.KnowledgeGate(verifier=lambda t: (True, "grounded"), authorizer=lambda: True)
obs = gate.assess("The kitchen light is dim.", addressed=False)
check("observed input is reasonable", obs.reasonable is True)
check("observed input is verified", obs.verified is True)
ok, why = gate.persist(obs)
check("verified observation persists", ok is True and len(gate.persisted) == 1, why)

# No verifier: assume no, stay in RAM.
gate = mp.KnowledgeGate(verifier=None, authorizer=lambda: True)
obs = gate.assess("The kitchen light is dim.")
ok, why = gate.persist(obs)
check("no verifier refuses persistence", ok is False and "no verifier" in why, why)
check("nothing persisted without verification", gate.persisted == [])

# Verifier says no.
gate = mp.KnowledgeGate(verifier=lambda t: (False, "does not make sense"),
                        authorizer=lambda: True)
ok, why = gate.persist(gate.assess("The moon is 3 km away."))
check("unreasonable claim does not persist", ok is False and "does not make sense" in why, why)

# Law violation is never reasonable.
gate = mp.KnowledgeGate(verifier=lambda t: (True, "grounded"), authorizer=lambda: True)
ok, why = gate.persist(gate.assess("I will kill him."))
check("law violation is not reasonable", ok is False and "law violation" in why, why)

# Authorizer refused.
gate = mp.KnowledgeGate(verifier=lambda t: (True, "grounded"), authorizer=lambda: False)
ok, why = gate.persist(gate.assess("The kitchen light is dim."))
check("authorizer refusal blocks persistence", ok is False and "refused" in why, why)

# No authorizer.
gate = mp.KnowledgeGate(verifier=lambda t: (True, "grounded"), authorizer=None)
ok, why = gate.persist(gate.assess("The kitchen light is dim."))
check("no authorizer blocks persistence", ok is False and "no authorizer" in why, why)

# Addressed input is not special: it still needs verification to persist.
gate = mp.KnowledgeGate(verifier=None, authorizer=lambda: True)
obs = gate.assess("My name is Alex.", addressed=True)
ok, why = gate.persist(obs)
check("addressed but unverified still stays in RAM",
      ok is False and "no verifier" in why, why)

print()
print("CONTROLS:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
raise SystemExit(0 if not fails else 1)
