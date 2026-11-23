# uml_positional_scaling.py
# Red-team test suite for positional array lanes and spaced dual-sided scaling.

import uml_engine

def run_positional_test(name, expr, expected_desc):
    print(f"\n--- POSITIONAL & SCALING TEST: {name} ---")
    print(f"  Expression:    {expr}")
    print(f"  Target Focus:  {expected_desc}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:        {uml_engine.fmt(res)}")
        if trace:
            print(f"  Trace Traceback:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<25} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  PARSER EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML POSITIONAL ARRAY & SCALING RED-TEAM SUITE")
    print("  Testing array data lanes and properly formatted nested divisions.")
    print("=========================================================")

    # 1. Positional Array Contamination (Mixing ceiling, raw scalar, and floor)
    run_positional_test(
        "Positional Array Contamination",
        "[<!0, !0>, 5, {!0, !0}]",
        "Evaluating a mixed array containing a ceiling snap, a raw scalar, and a floor collapse."
    )

    # 2. Clean Dual-Sided Scaling (Properly spaced division of two scaled primitives)
    run_positional_test(
        "Clean Dual-Sided Scaling",
        "< >2, !0<, >3, !0<>",
        "Dividing two independently scaled primitives ((2 * 0) / (3 * 0))."
    )

    print("\n=========================================================")
    print("  POSITIONAL & SCALING SUITE COMPLETE")
    print("=========================================================")
