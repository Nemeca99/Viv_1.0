# uml_proof.py
# The Algebraic Proof Runner — WITH VERIFICATION.
# Runs the skeleton A op A = B; B op C = A; D op A = A
# Solves for C and D via inverse operations, then SUBSTITUTES them
# back into the original equations and CHECKS the skeleton closes.

import uml_engine

VOID = '!0'

# ==========================================
# SECTION 1: SOLVER TABLE
# ==========================================
# For each operation, we need FIVE expressions:
#   eq1        : B = A op A
#   eq2_solve  : expression that yields C given (A, B)
#   eq2_check  : expression B op C   (should equal A)
#   eq3_solve  : expression that yields D given (A)
#   eq3_check  : expression D op A   (should equal A)

SOLVERS = {
    "ADDITION": {
        "eq1":       "[{},{}]",
        "eq2_solve": "{{{},{}}}",        # C = A - B
        "eq2_check": "[{},{}]",          # B + C
        "eq3_solve": "{{{},{}}}",        # D = A - A
        "eq3_check": "[{},{}]",          # D + A
    },
    "SUBTRACTION": {
        "eq1":       "{{{},{}}}",
        "eq2_solve": "{{{},{}}}",        # C = B - A
        "eq2_check": "{{{},{}}}",        # B - C
        "eq3_solve": "[{},{}]",          # D = A + A
        "eq3_check": "{{{},{}}}",        # D - A
    },
    "MULTIPLICATION": {
        "eq1":       ">{},{}<",
        "eq2_solve": "<{},{}>",          # C = A / B
        "eq2_check": ">{},{}<",          # B * C
        "eq3_solve": "<{},{}>",          # D = A / A
        "eq3_check": ">{},{}<",          # D * A
    },
    "DIVISION": {
        "eq1":       "<{},{}>",
        "eq2_solve": "<{},{}>",          # C = B / A
        "eq2_check": "<{},{}>",          # B / C
        "eq3_solve": ">{},{}<",          # D = A * A
        "eq3_check": "<{},{}>",          # D / A
    },
}


# ==========================================
# SECTION 2: EQUALITY / CLOSURE
# ==========================================

def is_void(v):
    return v == VOID


def closes(verified, target):
    """Did the substituted equation close against the target?

    Cases:
      - Concrete target, concrete verified:  strict numeric match.
      - Concrete target, void verified:      pass iff target ∈ [0, 1]
                                             (logic space contains it).
      - Void target:                         pass iff verified ∈ [0, 1] ∪ {!0}.
    """
    if is_void(target):
        if is_void(verified):
            return True
        if isinstance(verified, (int, float)):
            return 0.0 <= verified <= 1.0
        return False

    if is_void(verified):
        return isinstance(target, (int, float)) and 0.0 <= target <= 1.0

    if isinstance(verified, str) or isinstance(target, str):
        return verified == target

    try:
        return abs(float(verified) - float(target)) < 1e-9 * max(1.0, abs(float(target)))
    except Exception:
        return verified == target


def verdict(ok):
    return "CLOSED" if ok else "DID NOT CLOSE"


# ==========================================
# SECTION 3: SKELETON SOLVER
# ==========================================

def solve_skeleton(A_val, op_name):
    solver = SOLVERS[op_name]
    res = {
        "op": op_name, "A": A_val,
        "B": None, "C": None, "D": None,
        "eq2_verified": None, "eq2_ok": None,
        "eq3_verified": None, "eq3_ok": None,
        "error": None,
    }

    try:
        # --- Eq1: A op A = B  (direct) ---
        res["B"], _, _, _ = uml_engine.evaluate(solver["eq1"].format(A_val, A_val))

        # --- Eq2: B op C = A  (inverse-solve, then verify) ---
        # Arg order for eq2_solve flips between {A,B} and {B,A} families.
        if op_name in ("ADDITION", "MULTIPLICATION"):
            c_expr = solver["eq2_solve"].format(A_val, res["B"])
        else:
            c_expr = solver["eq2_solve"].format(res["B"], A_val)
        res["C"], _, _, _ = uml_engine.evaluate(c_expr)
        res["eq2_verified"], _, _, _ = uml_engine.evaluate(
            solver["eq2_check"].format(res["B"], res["C"]))
        res["eq2_ok"] = closes(res["eq2_verified"], A_val)

        # --- Eq3: D op A = A  (inverse-solve, then verify) ---
        res["D"], _, _, _ = uml_engine.evaluate(solver["eq3_solve"].format(A_val, A_val))
        res["eq3_verified"], _, _, _ = uml_engine.evaluate(
            solver["eq3_check"].format(res["D"], A_val))
        res["eq3_ok"] = closes(res["eq3_verified"], A_val)

    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"

    return res


# ==========================================
# SECTION 4: PRINTER
# ==========================================

def print_case(A_val):
    label = "!0 (logic space)" if is_void(A_val) else uml_engine.fmt(A_val)
    print("\n" + "=" * 61)
    print(f"  ALGEBRAIC SKELETON PROOF  —  A = {label}")
    print("=" * 61)

    all_ok = True
    for op_name in SOLVERS.keys():
        res = solve_skeleton(A_val, op_name)
        print(f"\n--- {op_name} ---")

        if res["error"]:
            print(f"  BROKEN → {res['error']}")
            all_ok = False
            continue

        print(f"  A = {uml_engine.fmt(res['A'])}")
        print(f"  B = {uml_engine.fmt(res['B'])}")
        print(f"  C = {uml_engine.fmt(res['C'])}")
        print(f"  D = {uml_engine.fmt(res['D'])}")
        print(f"  B op C = {uml_engine.fmt(res['eq2_verified']):<8} vs A → {verdict(res['eq2_ok'])}")
        print(f"  D op A = {uml_engine.fmt(res['eq3_verified']):<8} vs A → {verdict(res['eq3_ok'])}")

        if not (res["eq2_ok"] and res["eq3_ok"]):
            all_ok = False

    print("\n" + "-" * 61)
    print(f"  RESULT: {'ALL FOUR OPS CLOSED' if all_ok else 'FAILURES DETECTED'}")
    print("-" * 61)
    return all_ok


# ==========================================
# SECTION 5: SWEEP + MAIN
# ==========================================

def run_all_defaults():
    cases = [
        (2.0,   "non-trivial scalar"),
        (0.5,   "interior of logic space"),
        (1.0,   "the ceiling"),
        (0.0,   "the floor"),
        (VOID,  "logic space itself"),
    ]
    summary = []
    for val, note in cases:
        ok = print_case(val)
        label = "!0" if is_void(val) else uml_engine.fmt(val)
        summary.append((label, note, ok))

    print("\n" + "=" * 61)
    print("  SUMMARY")
    print("=" * 61)
    for label, note, ok in summary:
        print(f"  A = {label:<6}  {note:<28}  {'PASS' if ok else 'FAIL'}")
    print("=" * 61)
    return all(ok for _, _, ok in summary)


if __name__ == "__main__":
    import uml_special

    print("=" * 61)
    print("  ALGEBRAIC SKELETON PROVER (verified)")
    print("  Sequence: A op A = B; B op C = A; D op A = A")
    print("  C and D are solved via inverse ops, then substituted")
    print("  back to CHECK the skeleton actually closes.")
    print("=" * 61)

    try:
        raw = input("\n  A = (blank for sweep of 2, 0.5, 1, 0, !0) ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n  Exiting.")
        raise SystemExit(0)

    if not raw:
        ok = run_all_defaults()
        raise SystemExit(0 if ok else 1)

    try:
        translated, _ = uml_special.process(raw)
        A_val, _, _, _ = uml_engine.evaluate(translated)
        ok = print_case(A_val)
        raise SystemExit(0 if ok else 1)
    except (EOFError, KeyboardInterrupt):
        print("\n  Exiting.")
    except Exception as e:
        print(f"\n  ERROR: {e}")