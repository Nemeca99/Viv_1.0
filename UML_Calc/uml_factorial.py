# uml_factorial.py
# AIOS Recursive Geometric Spiral (Factorial)
# Collapsing a volumetric multiplier down to the !0 anchor.

import uml_engine
import time

# --- UML FACTORIAL TOPOLOGY ---
# Step inward toward the void: {?N, 1}
EQ_SUB = "{?N, 1}"
# Multiply geometric volume: >?N, ?ACC<
EQ_MULT = ">?N, ?ACC<"

def calculate_factorial(n):
    print("=========================================================")
    print(f"  UML TOPOLOGY: {n}! (FACTORIAL SPIRAL)")
    print("=========================================================")
    
    # Initialize start coordinate and boundary unity
    uml_engine.SESSION_VARS.update({
        '?N': n,
        '?ACC': 1 
    })
    
    current_n = n
    step = 1
    
    while current_n > 0:
        try:
            # 1. Expand the accumulated volume
            acc, _, _, _ = uml_engine.evaluate(EQ_MULT)
            uml_engine.SESSION_VARS['?ACC'] = acc
            
            # 2. Step the boundary coordinate closer to !0
            next_n, _, _, _ = uml_engine.evaluate(EQ_SUB)
            
            print(f"Depth {step:02d} | Node: {current_n:>2} | Spiral Volume: {acc:>8} | Next Boundary: {next_n}")
            
            current_n = next_n
            uml_engine.SESSION_VARS['?N'] = current_n
            step += 1
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Depth {step:02d} | SYSTEM CRASH: {e}")
            break
            
    print("=========================================================")
    print(f"  SPIRAL COLLAPSED TO !0. FINAL FACTORIAL: {uml_engine.SESSION_VARS['?ACC']}")
    print("=========================================================")

if __name__ == "__main__":
    calculate_factorial(5)
    calculate_factorial(10)
