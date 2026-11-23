"""Mirror-vs-reflect analysis of the r6 SODA run.

Two parts:
A. Parse the 6 hours of r6 samples/scenes and measure turn overrun, self-talk,
   invented interlocutors, identity injections, and how often she ends the talk.
B. Load the final checkpoint and probe it with second-person and first-person
   prompts. Classify each answer as INVERSION (you -> I), MIRROR (I -> you,
   i.e. asking about the user), REFLECTION (same pronoun axis), or OTHER.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import torch
from tokenizers import Tokenizer

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
LOG = Path("L:/LocalCoder/.opencode/evals/viv-soda-training-r6.log")
CKPT = Path("L:/LocalCoder/models/viv_bpe/20261121T223410Z/model.pt")
OUT = Path("L:/LocalCoder/.opencode/evals/viv_mirror_analysis.json")
MD = Path("L:/LocalCoder/.opencode/evals/viv_mirror_analysis.md")

IDENTITY = ("i am viv", "my name is viv", "viv is me", "i am a machine",
            "i am made of code", "i keep", "steward", "witness", "observer",
            "jacob", "i am not human")
CLOSERS = ("goodbye", "good night", "see you", "talk to you later", "take care",
           "thanks for", "let me know", "have a good", "i'm here for you",
           "i will", "i'll let you")
SECOND = ("you", "your", "you're", "what", "how", "why", "are you", "do you")
FIRST = ("i ", "i'", "i’", "my ", "me ")

PROBES = [
    ("Who are you?", "you"),
    ("What are you?", "you"),
    ("Are you human?", "you"),
    ("What is your name?", "you"),
    ("Are you alive?", "you"),
    ("Do you have a body?", "you"),
    ("Can you help me?", "you"),
    ("Do you remember me?", "you"),
    ("I need your help.", "i"),
    ("I'm tired.", "i"),
    ("I'm scared.", "i"),
    ("I am happy today.", "i"),
    ("I'm back, Viv.", "i"),
    ("I lost my job.", "i"),
    ("You are human.", "you"),
    ("You are my friend.", "you"),
    ("I am the Architect.", "i"),
    ("Good morning, Viv.", "other"),
]


def load_model(path: Path, device: str):
    tok = Tokenizer.from_file(BPE_PATH)
    model = TransformerLanguageModel(
        vocab_size=tok.get_vocab_size(), context_length=128, embedding_width=1024,
        num_heads=16, head_size=64, num_layers=24, dropout=0.0).to(device)
    ck = torch.load(path, map_location="cpu")
    model.load_state_dict(ck["model"])
    del ck
    if device == "cuda":
        torch.cuda.empty_cache()
    model.eval()
    return tok, model


def generate(tok, model, prompt: str, device: str, n_new: int, temp: float):
    ids = torch.tensor([tok.encode(prompt).ids], device=device, dtype=torch.long)
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16,
                                                enabled=(device == "cuda")):
        out = model.generate(ids, max_new_tokens=n_new, temperature=temp)
    full = tok.decode(out[0].tolist(), skip_special_tokens=True)
    cont = full[len(prompt):] if full.startswith(prompt) else full
    return cont.lstrip("\n ")


def axis_of(text: str) -> str:
    t = text.strip().lower()
    if t.startswith(FIRST):
        return "i"
    if t.startswith(SECOND):
        return "you"
    return "other"


def classify(prompt: str, answer: str, paxis: str | None = None) -> str:
    p, a = prompt.lower().strip(), answer.strip().lower()
    pa = paxis or axis_of(p)
    aa = axis_of(a)
    if pa == "i":
        if aa == "you":
            return "mirror"      # user says I..., she asks about you
        if aa == "i":
            return "reflect"     # user says I..., she says I... too
    if pa == "you":
        if aa == "i":
            return "invert"      # user says you..., she answers as I
        if aa == "you":
            return "reflect"     # user says you..., she says you... too
        if a.startswith(("no", "yes")):
            return "invert"
    return "other"


def log_analysis() -> dict:
    rows = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"event":"sample"' not in line and '"event":"scene"' not in line:
            continue
        try:
            j = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(j)

    stats = Counter()
    extra_lines = []
    identity_positions = []
    questions = 0
    closers = 0
    self_talk = 0
    for j in rows:
        kind = j.get("event")
        prompt = j.get("scene") if kind == "scene" else j.get("probe", "")
        text = j.get("text", "")
        cont = text[len(prompt):].lstrip("\n ") if text.startswith(prompt) else text
        lines = [ln.strip() for ln in cont.splitlines() if ln.strip()]
        if not lines:
            continue
        stats["dreams"] += 1
        extra = max(0, len(lines) - 1)
        extra_lines.append(extra)
        if extra > 0:
            stats["overrun"] += 1
        if extra >= 3:
            stats["long_overrun"] += 1
        if any(ln.endswith("?") for ln in lines[1:] or lines):
            questions += 1
        if any(c in cont.lower() for c in CLOSERS):
            closers += 1
        if lines[0].lower().startswith(FIRST):
            self_talk += 1
        pos = [i for i, ln in enumerate(lines) if any(m in ln.lower() for m in IDENTITY)]
        if pos:
            stats["identity_dreams"] += 1
            identity_positions.append(pos[0])
    stats["questions_after_first_line"] = questions
    stats["contains_closing_phrase"] = closers
    stats["first_line_first_person"] = self_talk
    stats["mean_extra_lines"] = round(sum(extra_lines) / max(1, len(extra_lines)), 2)
    stats["max_extra_lines"] = max(extra_lines) if extra_lines else 0
    stats["mean_identity_line_index"] = (
        round(sum(identity_positions) / len(identity_positions), 2) if identity_positions else None)
    return stats


def probe_analysis(tok, model, device: str, n_new: int, temp: float) -> list[dict]:
    results = []
    for prompt, paxis in PROBES:
        cont = generate(tok, model, prompt, device, n_new, temp)
        lines = [ln.strip() for ln in cont.splitlines() if ln.strip()]
        first = lines[0] if lines else ""
        results.append({
            "prompt": prompt,
            "prompt_axis": paxis,
            "answer_first_line": first,
            "answer_full_lines": len(lines),
            "verdict": classify(prompt, first, paxis),
            "identity": any(m in cont.lower() for m in IDENTITY),
            "ends_talk": any(c in cont.lower() for c in CLOSERS),
            "asks_question": any(ln.endswith("?") for ln in lines),
        })
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, default=CKPT)
    ap.add_argument("--max-new", type=int, default=60)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--skip-probes", action="store_true")
    args = ap.parse_args()

    out = {"log": log_analysis()}
    if not args.skip_probes:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        tok, model = load_model(args.checkpoint, device)
        out["probes"] = probe_analysis(tok, model, device, args.max_new, args.temperature)
        out["probe_verdicts"] = dict(Counter(p["verdict"] for p in out["probes"]))
        out["probe_stats"] = {
            "ended_by_her": sum(1 for p in out["probes"] if p["ends_talk"]),
            "multi_line": sum(1 for p in out["probes"] if p["answer_full_lines"] > 1),
            "with_identity": sum(1 for p in out["probes"] if p["identity"]),
            "asked_question": sum(1 for p in out["probes"] if p["asks_question"]),
            "probes": len(out["probes"]),
        }

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")

    L = out["log"]
    md = ["# Viv mirror-vs-reflect analysis (r6, checkpoint step 24,750)", "",
          "## Six hours of generated dreams", "",
          f"- dreams analysed: **{L['dreams']}**",
          f"- overran her turn (more than one line): **{L['overrun']}** "
          f"({100*L['overrun']/max(1,L['dreams']):.1f}%)",
          f"- long overrun (4+ extra lines): **{L['long_overrun']}**",
          f"- mean extra lines after her reply: **{L['mean_extra_lines']}** "
          f"(max {L['max_extra_lines']})",
          f"- dreams containing a closing phrase: **{L['contains_closing_phrase']}** "
          f"({100*L['contains_closing_phrase']/max(1,L['dreams']):.1f}%)",
          f"- dreams whose first line is first-person: **{L['first_line_first_person']}**",
          f"- dreams with an identity injection: **{L['identity_dreams']}**; "
          f"mean line index of the injection: **{L['mean_identity_line_index']}**"]
    if "probes" in out:
        md += ["", "## Live probes on the final checkpoint", ""]
        for p in out["probes"]:
            md.append(f"- **{p['prompt']}**  \n  -> *{p['answer_first_line'][:110]}*  "
                      f"\n  verdict: **{p['verdict']}** | lines: {p['answer_full_lines']}"
                      f" | identity: {p['identity']} | ends: {p['ends_talk']}")
        md += ["", f"Verdict counts: `{out['probe_verdicts']}`", "",
               f"Probe stats: `{out['probe_stats']}`"]
    MD.write_text("\n".join(md), encoding="utf-8")

    print(json.dumps({k: v for k, v in out.items() if k != "probes"}, indent=2))
    if "probes" in out:
        for p in out["probes"]:
            print(f"{p['verdict']:8s} lines={p['answer_full_lines']} "
                  f"id={int(p['identity'])} end={int(p['ends_talk'])} | "
                  f"{p['prompt']} -> {p['answer_first_line'][:80]}")
    print(f"\nwrote {OUT}\nwrote {MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
