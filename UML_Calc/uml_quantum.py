# uml_quantum.py
# Quantum Mechanics Red-Team Test Suite for the UML Engine.
# Models wave function superposition, collapse operators, and state normalization.

import uml_engine

def run_quantum_test(name, expr, description):
    print(f"\n--- QUANTUM TEST: {name} ---")
    print(f"  Description: {description}")
    print(f"  UML Expression: {expr}")
    try:
        res, node, notation, trace = uml_engine.evaluate(expr)
        print(f"  RESULT:         {uml_engine.fmt(res)}")
        if trace:
            print(f"  Collapse Trace:")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<22} = {uml_engine.fmt(val)}")
    except Exception as e:
        print(f"  WAVEFUNCTION COLLAPSE ERROR: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML QUANTUM MECHANICS SIMULATOR & RED-TEAM SUITE")
    print("  Mapping Superposition (!0) and Boundary Collapse Operators.")
    print("=========================================================")

    # 1. Basic State Superposition (Unmeasured particle state)
    run_quantum_test(
        "Superposition State",
        "!0",
        "A raw particle existing across the unmeasured 0-to-1 probability interval."
    )

    # 2. Wavefunction Normalization Check (|psi_1|^2 + |psi_2|^2)
    run_quantum_test(
        "Superposition Normalization",
        "[^2[!0], ^2[!0]]",
        "Sum of squared probability amplitudes across two superposed states."
    )

    # 3. Measurement Collapse Operator (Forcing resolution to ceiling)
    run_quantum_test(
        "Forced Measurement Collapse",
        "<!0, !0>",
        "Applying the division collapse operator to force superposition to resolve at the 1.0 eigenstate."
    )

    # 4. Ground State Nullification (Destructive interference)
    run_quantum_test(
        "Destructive Interference",
        "{!0, !0}",
        "Applying subtraction collapse to force superposition down to the 0.0 absolute floor."
    )

    # 5. Complex Quantum State Interaction (Interference Pattern)
    run_quantum_test(
        "Interference Pattern Matrix",
        "> [<!0, !0>, 0.5], {1, <!0, !0>} <",
        "Multiplying a collapsed measurement sum by a phase-shifted subtraction."
    )

    # 6. Orthogonal State Dot Product (Perpendicular States)
    run_quantum_test(
        "Orthogonal State Product",
        "> {!0, !0}, <!0, !0> <",
        "Multiplying ground state (0) by ceiling state (1) through logic space."
    )

    print("\n=========================================================")
    print("  QUANTUM SIMULATION COMPLETE")
    print("=========================================================")
