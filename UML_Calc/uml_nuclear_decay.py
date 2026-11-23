# uml_nuclear_decay.py
# Nuclear Physics & Decay Kinetics Red-Team Suite: Secular equilibrium, reactor period singularities, and decay matrix grids.

import uml_engine

def run_nuclear_test(name, expr, physical_model):
    print(f"\n--- NUCLEAR KINETICS: {name} ---")
    print(f"  UML Expression:  {expr}")
    print(f"  Physical Model:  {physical_model}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  ENGINE RESULT:   {uml_engine.fmt(res)}")
        if trace:
            print(f"  Boundary Trace:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<30} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  NUCLEAR EXCEPTION: {type(e).__name__}: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML NUCLEAR DECAY & REACTOR KINETICS SIMULATOR")
    print("  Resolving zero-reactivity and decay singularities.")
    print("=========================================================")

    # 1. Secular Equilibrium Ratio Collapse (Parent/Daughter activity ratio at zero boundary)
    run_nuclear_test(
        "Secular Equilibrium Ratio",
        "<!0, !0>",
        "Parent-to-daughter isotope decay activity ratio yielding 0/0 boundary limit."
    )

    # 2. Prompt Criticality Reactor Period Singularity (T = Lambda / rho where rho -> 0)
    run_nuclear_test(
        "Prompt Criticality Period",
        "[<!0, !0>, >5, <!0, !0><]",
        "Reactor period calculation compounding zero-reactivity division with structural thermal scaling."
    )

    # 3. Multi-Isotope Decay Chain Matrix Grid
    run_nuclear_test(
        "Decay Chain Grid Matrix",
        "[[<!0, !0>, <!0, !0>], [<{!0, !0}, {!0, !0}>]]",
        "Multi-stage decay matrix mapping stable ground states and unshielded core decay paths."
    )

    print("\n=========================================================")
    print("  NUCLEAR KINETICS SIMULATION COMPLETE")
    print("=========================================================")
