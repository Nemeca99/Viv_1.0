# uml_chaos_advanced.py
# Advanced Red-Team Test Suite: Scalar Contamination and Nullary Collisions.

import uml_engine

def run_advanced_chaos_test(name, expr, expected_desc):
    print(f"\n--- ADVANCED CHAOS: {name} ---")
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
    print("  UML ADVANCED CHAOS RED-TEAM SUITE")
    print("  Testing internal scalar containment and nullary collisions.")
    print("=========================================================")

    # 1. Internalized Scalar Contamination
    run_advanced_chaos_test(
        "Internalized Scalar Contamination",
        "<!0, >5, !0<<",
        "Injecting a scalar multiplier directly into the divisor of an un-snapped state."
    )

    # 2. The Nullary Collision
    run_advanced_chaos_test(
        "Nullary Collision",
        "<<-0, 0>, <0, -0>>",
        "Dividing two opposite-signed un-snapped polarity states."
    )

    print("\n=========================================================")
    print("  ADVANCED CHAOS SUITE COMPLETE")
    print("=========================================================")
