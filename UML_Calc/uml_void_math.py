import uml_engine

def test_equation(name, standard_eq, uml_eq):
    print(f"\n--- {name} ---")
    print(f"  Standard: {standard_eq}")
    try:
        node = uml_engine.std_parse(standard_eq)
        res = uml_engine.eval_node(node)
        print(f"    Result: {uml_engine.fmt(res)}")
    except Exception as e:
        print(f"    CRASH: {type(e).__name__}")

    print(f"  UML:      {uml_eq}")
    try:
        res, node, nota, trace = uml_engine.evaluate(uml_eq)
        print(f"    Result: {uml_engine.fmt(res)}")
    except Exception as e:
        print(f"    CRASH: {type(e).__name__}")

if __name__ == "__main__":
    print("=" * 55)
    print("  THE VOID PYTHAGOREAN TEST")
    print("=" * 55)
    
    # The original: A^2 * B^2 = C^2
    # With A = B = C = !0
    
    # Left Side (Standard AST)
    test_equation(
        "Left Side: !0^2 * !0^2",
        "(0/0)**2 * (0/0)**2",
        ">^2[!0], ^2[!0]<"
    )
    
    # Right Side (Standard AST)
    test_equation(
        "Right Side: !0^2",
        "(0/0)**2",
        "^2[!0]"
    )
    
    # The Full Equation: !0^2 * !0^2 = !0^2
    # To test equality, we subtract the right side from the left side.
    # If the result is 0, the equation is balanced.
    test_equation(
        "Full Equation Check (Left - Right = 0)",
        "((0/0)**2 * (0/0)**2) - ((0/0)**2)",
        "{>^2[!0], ^2[!0]<, ^2[!0]}"
    )
    
    print("\n" + "=" * 55)
    print("  TEST COMPLETE")
    print("=" * 55)