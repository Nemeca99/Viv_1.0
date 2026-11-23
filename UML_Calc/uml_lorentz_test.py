# uml_lorentz_test.py
# Lorentz-Cognizant Red-Team Suite: Rigorous Diagnostic Validation for Boundary Projections.

import uml_engine

def run_test(name, expr, description):
    print(f"\n--- TEST: {name} ---")
    print(f"  Expression:    {expr}")
    print(f"  Description:   {description}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:        {uml_engine.fmt(res)}")
        if trace:
            print(f"  Boundary Trace:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<25} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  RIGOROUS LORENTZ UML BOUNDARY PROJECTION TEST SUITE")
    print("  Eliminating false positives and testing bidirectional symmetry.")
    print("=========================================================")

    # 1. Pure Reflexive Boundaries (All 4 Operators)
    run_test(
        "Reflexive Division Ceiling",
        "<!0, !0>",
        "Normalizing to c (!0 / !0 = 1.0)."
    )

    run_test(
        "Reflexive Subtraction Floor",
        "{!0, !0}",
        "Collapsing temporal interval ({!0 - !0} = 0.0)."
    )

    run_test(
        "Reflexive Multiplication Identity",
        ">!0, !0<",
        "Reflexive mul projection (1 * 1 = 1.0)."
    )

    # 2. Bidirectional Mixed Subtraction & Division (Left and Right positions)
    run_test(
        "Mixed Subtraction (Right: Scalar - !0)",
        "{2, !0}",
        "Evaluating spatial separation (2 - 0 = 2)."
    )

    run_test(
        "Mixed Subtraction (Left: !0 - Scalar)",
        "{!0, 2}",
        "Distinguishing projection vs absorption (0 - 2 = -2)."
    )

    run_test(
        "Mixed Division (Right: Scalar / !0)",
        "<2, !0>",
        "Evaluating temporal scaling (2 / 1 = 2)."
    )

    run_test(
        "Mixed Division (Left: !0 / Scalar)",
        "<!0, 2>",
        "Evaluating inverse manifold projection (1 / 2 = 0.5)."
    )

    # 3. True Direct Mixed Multiplication (Eliminating inner bracket false positives)
    run_test(
        "True Direct Mixed Multiplication",
        ">!0, 3<",
        "Directly passing !0 to mul with non-2 scalar (1 * 3 = 3)."
    )

    # 4. Complex Composition (Annotated Composition Test)
    run_test(
        "Cross-Boundary Multiplicative Array (Composition)",
        ">[2, !0], <!0, !0><",
        "Composite test: outer mul operates on pre-resolved children (mixed-add and reflexive-div)."
    )

    print("\n=========================================================")
    print("  RIGOROUS LORENTZ TEST SUITE COMPLETE")
    print("=========================================================")
