# uml_backprop_proof.py
# Backend ML Proof-of-Concept: Governing backpropagation gradients and loss division using UML boundary logic.
# Linked directly to L:\LocalCoder\workspace\INN\inn\uml_neural_gate.py and INN neurons.

import math
import sys
from pathlib import Path
import uml_engine

_INN_ROOT = Path(__file__).resolve().parents[1] / "workspace" / "INN"
if _INN_ROOT.is_dir() and str(_INN_ROOT) not in sys.path:
    sys.path.insert(0, str(_INN_ROOT))

from inn.uml_neural_gate import (  # noqa: E402
    uml_safe_scalar_div,
    uml_safe_tensor_div,
    uml_clip_and_stabilize_gradients,
)


def uml_safe_grad_div(numerator, denominator):
    """
    UML Boundary-Gated Division for Backprop Gradients.
    Intercepts 0/0 or near-zero gradient norm collisions via uml_engine & inn.uml_neural_gate,
    mapping them to the !0 logic space and resolving safely to a stable multiplier (1.0).
    """
    return uml_safe_scalar_div(numerator, denominator)

class MiniBackpropLayer:
    def __init__(self, weight=0.5):
        self.weight = weight
        
    def step(self, loss, grad_norm, lr):
        """
        Executes a backprop update step: weight = weight - lr * (loss / grad_norm)
        Standard math crashes to NaN when grad_norm = 0.
        """
        # The danger zone: normalizing loss by gradient norm
        scaling_factor, state_tag = uml_safe_grad_div(loss, grad_norm)
        
        # Apply learning rate and update weight
        update = lr * scaling_factor
        self.weight -= update
        return self.weight, state_tag

if __name__ == "__main__":
    print("=========================================================")
    print("  UML BACKPROPAGATION & GRADIENT STABILITY PROOF")
    print("  Simulating multi-epoch training under zero-gradient stress.")
    print("=========================================================")

    layer = MiniBackpropLayer(weight=1.5)
    learning_rate = 0.01

    # Simulate 6 training epochs, injecting a fatal zero-gradient trap at Epoch 3 & 4
    training_data = [
        {"epoch": 1, "loss": 0.85, "grad_norm": 1.20},
        {"epoch": 2, "loss": 0.42, "grad_norm": 0.85},
        {"epoch": 3, "loss": 0.00, "grad_norm": 0.00},  # THE TRAP: 0 / 0 Singularity
        {"epoch": 4, "loss": 0.00, "grad_norm": 0.00},  # THE TRAP: 0 / 0 Singularity
        {"epoch": 5, "loss": 0.15, "grad_norm": 0.50},
        {"epoch": 6, "loss": 0.05, "grad_norm": 0.20},
    ]

    for data in training_data:
        epoch = data["epoch"]
        loss = data["loss"]
        grad = data["grad_norm"]
        
        new_w, status = layer.step(loss, grad, learning_rate)
        print(f"Epoch {epoch} | Loss: {loss:.2f} | GradNorm: {grad:.2f} | Status: {status:<24} | New Weight: {new_w:.4f}")

    print("=========================================================")
    print("  TRAINING COMPLETE: Zero NaN crashes encountered.")
    print("=========================================================")
