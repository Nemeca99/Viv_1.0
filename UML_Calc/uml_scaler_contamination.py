# uml_scalar_contamination.py
# Red-team test suite for internal scalar contamination and nested bracket geometry.

import uml_engine

def run_scalar_test(name, expr, expected_desc):
    print(f"\n--- SCALAR CONTAMINATION: {name} ---")
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
        print(f"  PARSER EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML SCALAR CONTAMINATION RED-TEAM SUITE")
    print("  Testing nested operator bracket geometry and scalar absorption.")
    print("=========================================================")

    # 1. Corrected Internal Scalar Contamination (Multiplication nested in division denominator)
    run_scalar_test(
        "Nested Denominator Scaling",
        "<!0, >5, !0<>",
        "Dividing logic space by a scaled primitive (0 / (5 * 0))."
    )

    # 2. Dual-Sided Scalar Contamination
    run_scalar_test(
        "Dual-Sided Scaling",
        "<<>2, !0<, >3, !0<>>",
        "Dividing two independently scaled logic space primitives."
    )

    # 3. Deep Arithmetic-Logic Boundary Crossing
    run_scalar_test(
        "Arithmetic-Logic Cross",
        "[{!0, !0}, >4, <!0, !0><]",
        "Adding the absolute floor to a scalar-multiplied ceiling snap."
    )

    print("\n=========================================================")
    print("  SCALAR CONTAMINATION SUITE COMPLETE")
    print("=========================================================")
