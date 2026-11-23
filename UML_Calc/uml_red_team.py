# uml_red_team.py
# Red-team stress test suite for the UML Engine and Logic Space (!0).
# Pushes the boundaries of recursive containment, singularities, and base-52 scaling.

import uml_engine

def run_red_team_test(name, expr, expected_desc):
    print(f"\n--- RED TEAM: {name} ---")
    print(f"  Target Expression: {expr}")
    print(f"  Expected Behavior: {expected_desc}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:            {uml_engine.fmt(res)}")
        if trace:
            print(f"  Trace Depth Log:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<22} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  BROKEN (CRASH):    {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML ENGINE RED-TEAM STRESS TEST SUITE")
    print("  Target: Expose boundary leaks, parse failures, and logic faults.")
    print("=========================================================")

    # 1. Multi-Layered Nested Void Trap
    run_red_team_test(
        "Nested Void Trap",
        "[<{!0, !0}, {!0, !0}>, ^2[!0]]",
        "Addition of division ceiling (1) and subtraction floor (0), combined with squared logic space."
    )

    # 2. The RID Stability Total Collapse Simulator
    run_red_team_test(
        "RID Total Collapse",
        "> [<!0, !0>, <!0, !0>], {!0, !0} <",
        "Multiplying a dual-void ratio (1) by a floor-subtracted zero state (0)."
    )

    # 3. Base-52 Letter Scaling in Logic Space
    # J = 10 in base-52 indexing
    run_red_team_test(
        "Base-52 Scaling",
        ">[J, !0]<",
        "Scaling the logic space continuum by letter J (10). Should stretch interval to 10."
    )

    # 4. Infinite Logarithm Singularity Collision
    run_red_team_test(
        "Singular Logarithm",
        "&[<!0, !0>, 5]",
        "Log base evaluated from a void ratio (1). Log base 1 is mathematically undefined/invalid."
    )

    # 5. Deep Recursive Bracket Nesting with Mixed Constants
    run_red_team_test(
        "Deep Bracket Recursion",
        "{^[2][<[<!0, !0>, 2], {!0, !0}>], π}",
        "Nested powers, divisions, additions, and subtractions ending in a constant subtraction."
    )

    # 6. Negative Void Contraction
    run_red_team_test(
        "Negative Void Contraction",
        "~<!0, !0>",
        "Negating the ceiling resolution of logic space division (~1)."
    )

    print("\n=========================================================")
    print("  RED-TEAM STRESS TEST COMPLETE")
    print("=========================================================")
