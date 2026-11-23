# uml_chaos_injections.py
# Chaos injection red-team test suite for floor-ceiling collisions and polarity overrides.

import uml_engine

def run_chaos_test(name, expr, expected_desc):
    print(f"\n--- CHAOS INJECTION: {name} ---")
    print(f"  Expression:    {expr}")
    print(f"  Target Focus:  {expected_desc}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:        {uml_engine.fmt(res)}")
        if trace:
            print(f"  Trace Traceback:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<22} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  CHAOS EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML CHAOS INJECTION RED-TEAM SUITE")
    print("  Forcing floor-ceiling collisions and scalar overrides.")
    print("=========================================================")

    # 1. The Floor-Ceiling Paradox
    run_chaos_test(
        "Floor-Ceiling Paradox",
        "<{!0, !0}, <!0, !0>>",
        "Dividing the additive floor (0.0) by the divisional ceiling (1.0)."
    )

    # 2. Zero-Scalar Interference
    run_chaos_test(
        "Zero-Scalar Interference",
        ">0, <!0, !0><",
        "Multiplying true scalar 0 by the collapsed ceiling (1.0)."
    )

    # 3. Asymmetric Polarity Squeeze
    run_chaos_test(
        "Asymmetric Polarity Squeeze",
        ">~5, <-0, 0><",
        "Scaling an un-snapped polarity state with a negative scalar."
    )

    print("\n=========================================================")
    print("  CHAOS INJECTION SUITE COMPLETE")
    print("=========================================================")
