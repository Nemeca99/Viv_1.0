# uml_stress_test.py
# Pushing the UML geometric spiral to the absolute hardware limit.

import uml_engine

# --- UML FACTORIAL TOPOLOGY ---
EQ_SUB = "{?N, 1}"
EQ_MULT = ">?N, ?ACC<"

def find_the_break_point():
    print("=========================================================")
    print("  UML STRESS TEST: HUNTING THE 64-BIT HARDWARE BOUNDARY")
    print("=========================================================")
    
    n = 10
    while True:
        uml_engine.SESSION_VARS.update({'?N': n, '?ACC': 1})
        current_n = n
        
        try:
            # Run the volumetric multiplier down to !0
            while current_n > 0:
                acc, _, _, _ = uml_engine.evaluate(EQ_MULT)
                uml_engine.SESSION_VARS['?ACC'] = acc
                
                next_n, _, _, _ = uml_engine.evaluate(EQ_SUB)
                current_n = next_n
                uml_engine.SESSION_VARS['?N'] = current_n
            
            # Print milestones to keep the terminal clean
            if n % 20 == 0 or n < 15:
                print(f"Success: {n}! evaluated perfectly.")
                
            # Enter the danger zone
            if n >= 168:
                print(f"WARNING: {n}! = {acc:.2e}")
                
            n += 1
            
        except Exception as e:
            print("=========================================================")
            print(f"  SILICON SHATTERED AT {n}!")
            print(f"  CRASH REASON: {type(e).__name__}: {e}")
            print("=========================================================")
            break

if __name__ == "__main__":
    find_the_break_point()
