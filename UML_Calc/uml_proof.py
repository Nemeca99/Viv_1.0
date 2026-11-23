# uml_proof.py
# The Algebraic Proof Runner.
# Runs the skeleton A op A = B; B op C = A; D op A = A
# Uses exact inverse operations to solve for C and D.

import uml_engine

# ==========================================
# SECTION 1: VARIABLES
# ==========================================
# The templates for how we solve each equation based on the operator
SOLVERS = {
    "ADDITION": {
        "eq1": "[{},{}]",       # A + A = B
        "eq2": "{{{},{}}}",     # B + C = A  -> C = A - B
        "eq3": "{{{},{}}}",     # D + A = A  -> D = A - A
    },
    "SUBTRACTION": {
        "eq1": "{{{},{}}}",     # A - A = B
        "eq2": "{{{},{}}}",     # B - C = A  -> C = B - A
        "eq3": "[{},{}]",       # D - A = A  -> D = A + A
    },
    "MULTIPLICATION": {
        "eq1": ">{},{}<",       # A * A = B
        "eq2": "<{},{}>",       # B * C = A  -> C = A / B
        "eq3": "<{},{}>",       # D * A = A  -> D = A / A
    },
    "DIVISION": {
        "eq1": "<{},{}>",       # A / A = B
        "eq2": "<{},{}>",       # B / C = A  -> C = B / A
        "eq3": ">{},{}<",       # D / A = A  -> D = A * A
    }
}

# ==========================================
# SECTION 2: MAIN FUNCTIONS
# ==========================================

def solve_skeleton(A_val, op_name):
    results = {"A": A_val, "B": None, "C": None, "D": None, "error": None}
    solver = SOLVERS[op_name]

    try:
        # --- Equation 1: A op A = B ---
        expr1 = solver["eq1"].format(A_val, A_val)
        b_val, _, _, _ = uml_engine.evaluate(expr1)
        results["B"] = b_val

        # --- Equation 2: B op C = A ---
        # We use the inverse operation to solve for C.
        # If it's ADDITION: B + C = A -> C = A - B
        # If it's SUBTRACTION: B - C = A -> C = B - A
        # If it's MULTIPLICATION: B * C = A -> C = A / B
        # If it's DIVISION: B / C = A -> C = B / A
        
        if op_name == "ADDITION":
            c_expr = solver["eq2"].format(A_val, b_val)
        elif op_name == "SUBTRACTION":
            c_expr = solver["eq2"].format(b_val, A_val)
        elif op_name == "MULTIPLICATION":
            c_expr = solver["eq2"].format(A_val, b_val)
        elif op_name == "DIVISION":
            c_expr = solver["eq2"].format(b_val, A_val)
            
        c_val, _, _, _ = uml_engine.evaluate(c_expr)
        results["C"] = c_val

        # --- Equation 3: D op A = A ---
        # If it's ADDITION: D + A = A -> D = A - A
        # If it's SUBTRACTION: D - A = A -> D = A + A
        # If it's MULTIPLICATION: D * A = A -> D = A / A
        # If it's DIVISION: D / A = A -> D = A * A
        
        if op_name == "ADDITION":
            d_expr = solver["eq3"].format(A_val, A_val)
        elif op_name == "SUBTRACTION":
            d_expr = solver["eq3"].format(A_val, A_val)
        elif op_name == "MULTIPLICATION":
            d_expr = solver["eq3"].format(A_val, A_val)
        elif op_name == "DIVISION":
            d_expr = solver["eq3"].format(A_val, A_val)
            
        d_val, _, _, _ = uml_engine.evaluate(d_expr)
        results["D"] = d_val

    except Exception as e:
        results["error"] = str(e)

    return results


def run_proof(A_val):
    print("\n" + "=" * 55)
    print(f"  ALGEBRAIC PROOF: A = {uml_engine.fmt(A_val)}")
    print("=" * 55)
    
    for op_name in SOLVERS.keys():
        res = solve_skeleton(A_val, op_name)
        
        print(f"\n--- {op_name} ---")
        if res["error"]:
            print(f"  RESULT: BROKEN -> {res['error']}")
            continue
            
        print(f"  A = {uml_engine.fmt(res['A'])}")
        print(f"  B = {uml_engine.fmt(res['B'])}")
        print(f"  C = {uml_engine.fmt(res['C'])}")
        print(f"  D = {uml_engine.fmt(res['D'])}")
    
    print("\n" + "=" * 55)


# ==========================================
# SECTION 3: STANDALONE TEST
# ==========================================
if __name__ == "__main__":
    import uml_special
    
    print("=========================================================")
    print("  ALGEBRAIC SKELETON PROVER")
    print("  Sequence: A op A = B; B op C = A; D op A = A")
    print("=========================================================")
    print("\n  Enter a value for A. (Try 1, 2, or 0)")
    
    try:
        raw = input("\n  A = ").strip()
        if not raw:
            raw = "1"
        
        # Run through gearbox (allows !0, 0~, etc.)
        translated, _ = uml_special.process(raw)
        
        # Evaluate A
        A_val, _, _, _ = uml_engine.evaluate(translated)
        
        run_proof(A_val)
        
    except (EOFError, KeyboardInterrupt):
        print("\n  Exiting.")
    except Exception as e:
        print(f"\n  ERROR: {e}")