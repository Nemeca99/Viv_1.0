# uml_traps.py
# Red-team test suite for architectural traps and edge cases in the !0 logic space.

import uml_engine

def run_trap_test(name, expr, expected_desc):
    print(f"\n--- ARCHITECTURAL TRAP: {name} ---")
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
        print(f"  TRAP TRIGGERED EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML ARCHITECTURAL TRAP RED-TEAM SUITE")
    print("  Testing interval scaling, polarity, and structural momentum.")
    print("=========================================================")

    # 1. The Multiplicative Squeeze (Positive & Negative Scalars)
    run_trap_test(
        "Multiplicative Squeeze (Positive)",
        ">5, <!0, !0><",
        "Scaling the logic space interval by 5."
    )
    
    run_trap_test(
        "Multiplicative Squeeze (Negative)",
        ">~5, <!0, !0><",
        "Scaling the logic space interval by a negative scalar (-5)."
    )

    # 2. The Compounding Feedback Loop (Nested Depth Test)
    run_trap_test(
        "Compounding Feedback Loop",
        "<<!0, !0>, <!0, !0>>",
        "Dividing logic space division by logic space division ((0/0) / (0/0))."
    )

    # 3. The Sign Inversion Polarity Test
    run_trap_test(
        "Polarity Trap (Negative Zero Division)",
        "<-0, 0>",
        "Testing divisor polarity with a negative zero float."
    )

    # 4. Structural Differential Shift (AST Preservation Test)
    # Comparing structural representation of (x^2)/x vs x/(x^2) using standard parse trees
    print("\n--- ARCHITECTURAL TRAP: Differential Shift Structure ---")
    print("  Target Focus: Verifying AST structural momentum for x^2/x vs x/x^2")
    try:
        node1 = uml_engine.std_parse("(2**2)/2")
        node2 = uml_engine.std_parse("2/(2**2)")
        print(f"  AST 1 ((x^2)/x at x=2): {uml_engine.to_std(node1)} -> Evaluates to: {uml_engine.eval_node(node1)}")
        print(f"  AST 2 (x/(x^2) at x=2): {uml_engine.to_std(node2)} -> Evaluates to: {uml_engine.eval_node(node2)}")
    except Exception as e:
        print(f"  STRUCTURAL TEST ERROR: {e}")

    print("\n=========================================================")
    print("  ARCHITECTURAL TRAP SUITE COMPLETE")
    print("=========================================================")
