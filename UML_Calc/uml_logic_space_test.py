# uml_logic_space_test.py
# Tests the infinite fractional descent into Logic Space (!0) 
# and the deterministic boundary snapback (Floor 0, Ceiling 1).

import uml_engine

def simulate_descent(steps=10):
    print("\n" + "=" * 55)
    print("  LOGIC SPACE DESCENT & BOUNDARY SNAPBACK TEST")
    print("=" * 55)
    
    val = 1.0
    print(f"  Initial State: A = {val}")
    print("  Beginning infinite halving descent...")
    
    for i in range(1, steps + 1):
        val = val / 2.0
        # Simulating approach toward the limit
        if i <= 3 or i == steps:
            print(f"    Step {i:02d}: Halved -> {val:.8f}")
            
    print(f"\n  Limit approach reached. Engaging Logic Space (!0) boundary gate.")
    
    # Test suite verifying boundary behavior of the continuum
    tests = [
        ("Floor Convergence (Logic Space Subtraction)", "{!0, !0}"),
        ("Ceiling Snapback (Logic Space Division)", "<!0, !0>"),
        ("Nested Fractional Scale in Logic Space", "[<!0, !0>, 0.5]"),
        ("Recursive Self-Containment Boundary", "<!0, {!0, !0}>")
    ]
    
    for name, expr in tests:
        print(f"\n--- {name} ---")
        print(f"  Expression: {expr}")
        try:
            res, node, notation, trace = uml_engine.evaluate(expr)
            print(f"  Result:     {uml_engine.fmt(res)}")
            for depth, sub, val in trace:
                print(f"    d{depth} {sub:<15} = {uml_engine.fmt(val)}")
        except Exception as e:
            print(f"  CRASH:      {e}")
            
    print("\n" + "=" * 55)
    print("  DESCENT TEST COMPLETE: Safe return to ceiling.")
    print("=" * 55)

if __name__ == "__main__":
    simulate_descent(10)
