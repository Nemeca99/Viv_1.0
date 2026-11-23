# uml_extreme_redteam.py
# Extreme Red-Team Suite: Exponentiation, Dirac impulses, and RID framework stability collapse.

import uml_engine

def run_extreme_test(name, expr, description):
    print(f"\n--- EXTREME FRONTIER: {name} ---")
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
    print("  UML EXTREME RED-TEAM SUITE")
    print("  Testing Exponents, Dirac Impulses, and RID Stability.")
    print("=========================================================")

    # 1. Thermodynamic Absolute Zero Exponentiation
    run_extreme_test(
        "Zeroth Power of Logic Space",
        "^0[!0]",
        "Evaluating primitive logic state raised to the power of 0."
    )

    # 2. The Dirac Delta Integral (0 * Infinity)
    run_extreme_test(
        "Dirac Delta Area Integral",
        "> {!0, !0}, <1, {!0, !0}> <",
        "Multiplying a collapsed temporal floor (0) by an infinite spatial spike (1/0)."
    )

    # 3. RID Framework Stability Collapse (Sn = RSR * LTP * RLE)
    run_extreme_test(
        "RID Framework Cascade Survival",
        ">!0, 0.95, 0.8<",
        "Simulating RSR node failure (!0) against stable LTP (0.95) and RLE (0.8)."
    )

    print("\n=========================================================")
    print("  EXTREME RED-TEAM SUITE COMPLETE")
    print("=========================================================")
