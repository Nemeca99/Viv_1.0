# uml_matrix_chaos.py
# Matrix Red-Team Test Suite: Testing multiplicative array wrappers and nested flattening.

import uml_engine

def run_matrix_test(name, expr, expected_desc):
    print(f"\n--- MATRIX CHAOS: {name} ---")
    print(f"  Expression:    {expr}")
    print(f"  Target Focus:  {expected_desc}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:        {uml_engine.fmt(res)}")
        if trace:
            print(f"  Trace Traceback:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<30} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  MATRIX EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML MATRIX CHAOS RED-TEAM SUITE")
    print("  Testing array aggregation under multiplication and nesting.")
    print("=========================================================")

    # 1. Multiplicative Array Explosion
    run_matrix_test(
        "Multiplicative Array Explosion",
        ">[<!0, !0>, 5, {!0, !0}], <!0, !0><",
        "Multiplying an additive matrix sum (6) by a fresh logic primitive division (1)."
    )

    # 2. Pure Token Collapsing Matrix (Nested Arrays)
    run_matrix_test(
        "Pure Token Collapsing Matrix",
        "[[<!0, !0>, <!0, !0>], [{!0, !0}, {!0, !0}]]",
        "A nested square bracket matrix composed of competing ceiling snaps and floor collapses."
    )

    print("\n=========================================================")
    print("  MATRIX CHAOS SUITE COMPLETE")
    print("=========================================================")
