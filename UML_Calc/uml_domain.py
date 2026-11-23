import math
import uml_engine
import uml_special

# ==========================================
# TEST RUNNER
# ==========================================
def run_domain_test(domain, standard_expr, uml_expr, note):
    print(f"\n--- {domain} ---")
    print(f"  {note}")
    print(f"  Standard AST: {standard_expr}")
    
    # 1. Standard Math (AST)
    try:
        node = uml_engine.std_parse(standard_expr)
        res = uml_engine.eval_node(node)
        print(f"    Result:     {uml_engine.fmt(res)}")
    except Exception as e:
        print(f"    CRASH:      {type(e).__name__} (Standard math breaks)")

    # 2. UML Math (Logic Space)
    print(f"  UML Engine:   {uml_expr}")
    try:
        translated, _ = uml_special.process(uml_expr)
        res, node, nota, trace = uml_engine.evaluate(translated)
        print(f"    Result:     {uml_engine.fmt(res)}")
    except Exception as e:
        print(f"    CRASH:      {type(e).__name__} (UML engine failed)")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    print("=========================================================")
    print("  THE UNIVERSAL LOGIC SPACE STRESS TEST")
    print("=========================================================")
    
    # 1. CALCULUS: Indeterminate Limits
    run_domain_test(
        "Calculus: Indeterminate Limit",
        "0 / 0",
        "<!0, !0>",
        "Standard math requires L'Hopital's rule. UML defines the limit as Logic Space."
    )

    # 2. PHYSICS: Lorentz Factor at Speed of Light
    run_domain_test(
        "Physics: Speed of Light (Lorentz)",
        "1 / (1 - 1)",
        "<1, {1, 1}>",
        "At v=c, standard math divides by zero. UML isolates the singularity."
    )

    # 3. LINEAR ALGEBRA: Singular Matrix Inversion
    run_domain_test(
        "Linear Algebra: Singular Matrix",
        "1 / 0",
        "<1, !0>",
        "Inverting a matrix with determinant 0 crashes standard math. UML tracks the Null space."
    )

    # 4. PROBABILITY: Impossible Evidence (Bayes)
    run_domain_test(
        "Probability: Impossible Evidence",
        "0.5 / 0",
        "<0.5, !0>",
        "Bayes' theorem with P(B)=0 crashes standard math. UML marks the branch as Logic Space."
    )

    # 5. RID STABILITY: Total System Collapse (Fixed Syntax)
    run_domain_test(
        "RID Stability: System Collapse",
        "(0 * 0) / (0 * 0)",
        "[<!0, !0>, <!0, !0>]", # Changed to addition to avoid bracket confusion
        "If all stability channels hit 0, the RID equation crashes standard math. UML absorbs it."
    )

    # 6. ELECTRICAL ENG: Floating Node
    run_domain_test(
        "Electrical: Floating Node",
        "0 / 0",
        "<!0, !0>",
        "A node with no path to ground has undefined voltage. UML tracks the undefined state."
    )

    print("\n=========================================================")
    print("  DOMAIN TEST COMPLETE")
    print("=========================================================")