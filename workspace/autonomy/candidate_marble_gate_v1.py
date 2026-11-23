"""Candidate-only copy of Architect's reversible six-mode Boolean gates (v1)."""
from __future__ import annotations

import random


class ReversibleLogicGate:
    MODES = ["INHIBIT_1", "INHIBIT_2", "OR", "AND", "XOR", "XNOR"]

    def __init__(self, gate_id, mode_idx=0):
        self.gate_id = gate_id
        self.mode_idx = mode_idx % len(self.MODES)
        self.last_in1 = 0
        self.last_in2 = 0
        self.last_out = 0

    @property
    def mode(self):
        return self.MODES[self.mode_idx]

    def forward(self, in1: int, in2: int) -> int:
        self.last_in1 = in1 & 1
        self.last_in2 = in2 & 1
        if self.mode == "INHIBIT_1":
            out = int(self.last_in1 == 1 and self.last_in2 == 0)
        elif self.mode == "INHIBIT_2":
            out = int(self.last_in2 == 1 and self.last_in1 == 0)
        elif self.mode == "OR":
            out = self.last_in1 | self.last_in2
        elif self.mode == "AND":
            out = self.last_in1 & self.last_in2
        elif self.mode == "XOR":
            out = self.last_in1 ^ self.last_in2
        else:  # XNOR
            out = int(self.last_in1 == self.last_in2)
        self.last_out = out
        return out

    def backward_pulse(self, target_out: int) -> tuple[int, int]:
        if target_out not in (0, 1):
            raise ValueError("target_out must be a binary value")
        if self.last_out == target_out:
            return (0, 0)
        if self.mode == "INHIBIT_1" and self.last_in2 == 1 and target_out == 1:
            self.mode_idx = self.MODES.index("INHIBIT_2")
        elif self.mode == "INHIBIT_2" and self.last_in1 == 1 and target_out == 1:
            self.mode_idx = self.MODES.index("INHIBIT_1")
        else:
            for step in range(1, len(self.MODES) + 1):
                self.mode_idx = (self.mode_idx + step) % len(self.MODES)
                if self.forward(self.last_in1, self.last_in2) == target_out:
                    break
        pulse_1 = self.last_in1 ^ 1 if self.last_in1 != target_out else self.last_in1
        pulse_2 = self.last_in2 ^ 1 if self.last_in2 != target_out else self.last_in2
        return pulse_1, pulse_2


class MarbleGateNetwork:
    def __init__(self, seed: int | None = None, force_xor: bool = False):
        if force_xor:
            initial = [4, 4, 4]
        else:
            chooser = random.Random(seed)
            initial = [chooser.randint(0, 5) for _ in range(3)]
        self.g_h1 = ReversibleLogicGate("H1", initial[0])
        self.g_h2 = ReversibleLogicGate("H2", initial[1])
        self.g_out = ReversibleLogicGate("OUT", initial[2])
        self.initial_modes = tuple(initial)

    def forward(self, a: int, b: int, c: int) -> int:
        h1_out = self.g_h1.forward(a, b)
        h2_out = self.g_h2.forward(b, c)
        return self.g_out.forward(h1_out, h2_out)

    def reverse_propagate(self, target: int) -> None:
        if self.g_out.last_out == target:
            return
        old_mode = self.g_out.mode_idx
        req_h1, req_h2 = self.g_out.backward_pulse(target)
        if self.g_out.forward(self.g_h1.last_out, self.g_h2.last_out) != target:
            self.g_out.mode_idx = old_mode
            self.g_h1.backward_pulse(req_h1)
            self.g_h2.backward_pulse(req_h2)
            self.g_h1.forward(self.g_h1.last_in1, self.g_h1.last_in2)
            self.g_h2.forward(self.g_h2.last_in1, self.g_h2.last_in2)
            self.g_out.backward_pulse(target)

    def export_canonical_crystal(self) -> tuple[int, int, int]:
        return (self.g_h1.mode_idx, self.g_h2.mode_idx, self.g_out.mode_idx)


CONTRACT = {
    (0, 0, 0): 0, (0, 0, 1): 0, (0, 1, 0): 0, (0, 1, 1): 0,
    (1, 0, 0): 0, (1, 0, 1): 1, (1, 1, 0): 0, (1, 1, 1): 0,
}


def train_contract(net: MarbleGateNetwork, max_epochs: int) -> dict:
    history = []
    for epoch in range(1, max_epochs + 1):
        errors = 0
        for (a, b, c), expected in CONTRACT.items():
            actual = net.forward(a, b, c)
            if actual != expected:
                errors += 1
                net.reverse_propagate(expected)
        table_pass = all(net.forward(*inputs) == expected
                         for inputs, expected in CONTRACT.items())
        history.append({"epoch": epoch, "online_errors": errors,
                        "full_table_pass": table_pass,
                        "modes": net.export_canonical_crystal()})
        if table_pass:
            return {"converged": True, "epochs": epoch, "history": history}
    return {"converged": False, "epochs": max_epochs, "history": history}
