"""Test suite to inspect Viv's simple machine cognition across slots, cues, and physics."""
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE_ROOT / "INN"
STANDALONE_NN = Path(r"L:\Standalone\NN")
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(INN_ROOT))
sys.path.insert(0, str(STANDALONE_NN))

from autonomy.speak_unified_viv import load_verified_unified_brain
from autonomy.physical_dialogue_adapter import PhysicalDialogueAdapter

brain, receipt = load_verified_unified_brain(writable_clone=False)
phys_adapter = PhysicalDialogueAdapter()

probes = [
    # 1. Toddler Slots
    ("slot", "lever is _"),
    ("slot", "wheel is _"),
    ("slot", "pulley is _"),
    ("slot", "wedge is _"),
    ("slot", "screw is _"),
    ("slot", "ramp is _"),

    # 2. Toddler Cues
    ("cue", "lever"),
    ("cue", "pulley"),
    ("cue", "ramp"),
    ("cue", "wedge"),
    ("cue", "screw"),

    # 3. Wave Physical Interference
    ("phys", "lever fulcrum"),
    ("phys", "pulley rope"),
    ("phys", "ramp slope"),
    ("phys", "wedge force"),
    ("phys", "screw thread"),
    ("phys", "wheel axle"),
]

print("=== VIV SIMPLE MACHINES & FIRST PRINCIPLES PROBE RESULTS ===")
for p_type, text in probes:
    if p_type == "slot":
        res = brain.answer_slot_or_query(text, temperature=0.7)
        cands = [w for w, s in res.get("candidates", [])[:4]]
        print(f"SLOT: '{text}' -> '{res.get('chosen_word')}' (cands: {cands})")
    elif p_type == "cue":
        res = brain.speak_toddler(text)
        print(f"CUE:  '{text}' -> '{res.get('spoken_utterance')}'")
    elif p_type == "phys":
        res = phys_adapter.reason_physical_query(text)
        if res:
            res_words = res.get("top_tokens", [])[:4]
            chain = res.get("matched_chain")
            domain = chain.get("domain") if chain else "resonance"
            print(f"PHYS: '{text}' -> domain={domain} | echoes={res_words}")
        else:
            print(f"PHYS: '{text}' -> [NO RESONANCE]")
