# uml_conway_test.py
# Simulating Conway's Game of Life using UML Topological Logic Gates.

import uml_engine

# The pure math equation for Conway's Game of Life.
# No if-statements, just metric signature boundary projections.
CONWAY_UML = "[ {1, <{?N, 3}, {?N, 3}>}, >?C, {1, <{?N, 2}, {?N, 2}>}< ]"

def test_cell_state(current_state, neighbor_sum, expected_next):
    # Inject variables into the engine's state
    uml_engine.SESSION_VARS['?C'] = current_state
    uml_engine.SESSION_VARS['?N'] = neighbor_sum
    
    try:
        result, _, _, _ = uml_engine.evaluate(CONWAY_UML)
        passed = (result == expected_next)
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] Cell: {current_state}, Neighbors: {neighbor_sum} -> Next State: {int(result)} (Expected {expected_next})")
    except Exception as e:
        print(f"[FAIL] Cell: {current_state}, Neighbors: {neighbor_sum} -> ERROR: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("  UML CELLULAR AUTOMATA TEST: CONWAY'S GAME OF LIFE")
    print("  Testing topological Dirac logic gates via the Void.")
    print("=========================================================")
    
    print("\n--- Testing Dead Cell Spawning (Needs exactly 3) ---")
    test_cell_state(0, 2, 0)
    test_cell_state(0, 3, 1)  # Spawn!
    test_cell_state(0, 4, 0)

    print("\n--- Testing Live Cell Survival (Needs 2 or 3) ---")
    test_cell_state(1, 1, 0)  # Starvation
    test_cell_state(1, 2, 1)  # Survival
    test_cell_state(1, 3, 1)  # Survival
    test_cell_state(1, 4, 0)  # Overpopulation
    
    print("\n=========================================================")
