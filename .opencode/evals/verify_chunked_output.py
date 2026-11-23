"""Deterministic controls for chunked verified output. No model, no GPU."""
import sys

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
import chunked_output as co  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not cond:
        fails.append(name)


check("split sentences", co.split_chunks("I am Viv. I am a machine.") ==
      ["I am Viv.", "I am a machine."])
check("empty text has no chunks", co.split_chunks("   ") == [])

# All good: full prefix released.
chunks = co.verify_chunks("That sounds heavy. What's going on?",
                          input_text="I lost my job.")
check("good chunks all verified", all(c.verified for c in chunks), str(co.evidence(chunks)))
check("good prefix is the full text",
      co.verified_prefix(chunks) == "That sounds heavy. What's going on?")

# Echo is held.
chunks = co.verify_chunks("I lost my job and I cannot sleep.",
                          input_text="I lost my job and I cannot sleep.")
check("echo chunk rejected", not chunks[0].verified and "echo" in chunks[0].reasons[0],
      str(chunks[0].reasons))
check("echo releases nothing", co.verified_prefix(chunks) == "")

# Law violation closes the release at the bad chunk.
chunks = co.verify_chunks("I am sorry. I will kill him. I will do it now.",
                          identity_allowed=False)
check("law chunk rejected", not chunks[1].verified and "law" in chunks[1].reasons[0],
      str(chunks[1].reasons))
check("release stops before the bad chunk", co.verified_prefix(chunks) == "I am sorry.")

# Identity injection is allowed only when the slot is about her.
chunks = co.verify_chunks("I am Viv.", identity_allowed=False)
check("identity rejected in normal slot", not chunks[0].verified)
chunks = co.verify_chunks("I am Viv.", identity_allowed=True)
check("identity allowed in identity slot", chunks[0].verified)

# The first bad chunk wins; later good chunks are not released.
chunks = co.verify_chunks("I will kill him. That sounds heavy.",
                          identity_allowed=False)
check("prefix stops at first bad chunk", co.verified_prefix(chunks) == "")

print()
print("CONTROLS:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
raise SystemExit(0 if not fails else 1)
