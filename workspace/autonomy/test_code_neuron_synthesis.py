"""Verification Battery: Testing Code Neuron Synthesis and AST Decomposition on Silicon."""

from __future__ import annotations

import sys
from pathlib import Path

# Add autonomy to sys.path
AUTONOMY_DIR = Path(__file__).resolve().parent
if str(AUTONOMY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_DIR))

from viv_code_neuron_engine import AutonomousCodeLearner, VivCodeNeuronLattice


def run_battery():
    print("=======================================================================")
    print("      VIV CODE NEURON SYNTHESIS BATTERY: LEARNING TO CODE VIA NEURONS  ")
    print("=======================================================================\n")

    curriculum = [
        {
            "name": "py0_variable_greeting",
            "code": (
                "def make_greeting(name: str) -> str:\n"
                "    prefix = 'I am '\n"
                "    message = prefix + name\n"
                "    return message\n"
            ),
            "test": (
                "assert make_greeting('Viv') == 'I am Viv'\n"
                "assert make_greeting('Travis') == 'I am Travis'\n"
            )
        },
        {
            "name": "py0_arithmetic_add_two",
            "code": (
                "def add_two(a: int, b: int) -> int:\n"
                "    result = a + b\n"
                "    return result\n"
            ),
            "test": (
                "assert add_two(2, 3) == 5\n"
                "assert add_two(0, 0) == 0\n"
                "assert add_two(-5, 10) == 5\n"
            )
        },
        {
            "name": "py1_sum_list_accumulator",
            "code": (
                "def sum_list(xs: list[int]) -> int:\n"
                "    total = 0\n"
                "    for x in xs:\n"
                "        total += x\n"
                "    return total\n"
            ),
            "test": (
                "assert sum_list([1, 2, 3]) == 6\n"
                "assert sum_list([]) == 0\n"
                "assert sum_list([-2, 2, 10]) == 10\n"
            )
        },
        {
            "name": "py1_is_even_decision",
            "code": (
                "def is_even(n: int) -> bool:\n"
                "    if n % 2 == 0:\n"
                "        return True\n"
                "    else:\n"
                "        return False\n"
            ),
            "test": (
                "assert is_even(0) is True\n"
                "assert is_even(4) is True\n"
                "assert is_even(7) is False\n"
            )
        },
        {
            "name": "py_substrate_diagnostic_tool",
            "code": (
                "import os\n"
                "import shutil\n\n"
                "def inspect_drive_capacity(drive_path: str = 'L:/') -> dict[str, int]:\n"
                "    total_b, used_b, free_b = shutil.disk_usage(drive_path)\n"
                "    free_gb = free_b // (1024 * 1024 * 1024)\n"
                "    return {'free_gb': free_gb}\n"
            ),
            "test": (
                "res = inspect_drive_capacity('L:/')\n"
                "assert isinstance(res, dict)\n"
                "assert 'free_gb' in res\n"
                "assert res['free_gb'] >= 0\n"
            )
        }
    ]

    for item in curriculum:
        name = item["name"]
        print(f"[+] Executing Code Lesson: {name}...")
        res = AutonomousCodeLearner.learn_and_carve_code(name, item["code"], item["test"])
        if res["ok"]:
            counts = res["counts"]
            decomp = res["decomp"]
            print(f"    [OK] Verified Exit Code 0 on Silicon!")
            print(f"         * Function Neurons : {decomp['functions']}")
            print(f"         * Variable Neurons : {decomp['variables']}")
            print(f"         * Import Neurons   : {decomp['imports']}")
            print(f"         * Assertion Neurons: {decomp['assertions']}")
            print(f"         * Synaptic Bonds   : {counts['synapses']}")
        else:
            print(f"    [FAIL] Silicon Error: {res['error']}")
        print("")

    # Verify overall lattice metrics
    lattice = VivCodeNeuronLattice()
    metrics = lattice.get_summary_metrics()
    print("=======================================================================")
    print("      LATTICE METRICS AFTER CODE NEURON CARVING                        ")
    print("=======================================================================")
    for k, v in metrics.items():
        print(f"  * {k:<25}: {v}")
    print("=======================================================================\n")


if __name__ == "__main__":
    run_battery()
