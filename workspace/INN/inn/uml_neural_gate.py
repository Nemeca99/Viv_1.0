"""UML Boundary-Gated Neural Stabilization for INN Neurons.

Links the Lorentz-Cognizant UML Engine (`L:\\LocalCoder\\UML_Calc\\uml_engine.py`)
into PyTorch neural computation, attention divisors, and backpropagation gradients:
- `!0` Singularity Gate (`0 / 0 -> <!0, !0> = 1.0` ceiling snap)
- Zero Division Floor (`0 / !0 -> 0.0`, `!0 / 0 -> 0.0`)
- Dirac Impulse Absorption (`0 * inf -> !0 -> 1.0` or `0.0` floor)
- Gradient Norm & Parameter Sanitization for `TransformerEngine` and `LanguageEngine`
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Iterable

import torch
from torch import nn

# Ensure L:\LocalCoder\UML_Calc is importable so uml_engine is the single authority
_UML_CALC_DIR = Path(__file__).resolve().parents[3] / "UML_Calc"
if not _UML_CALC_DIR.is_dir():
    _UML_CALC_DIR = Path(r"L:\LocalCoder\UML_Calc")
if _UML_CALC_DIR.is_dir() and str(_UML_CALC_DIR) not in sys.path:
    sys.path.insert(0, str(_UML_CALC_DIR))

import uml_engine  # noqa: E402

# Canonical boundary constants evaluated directly through the UML Engine
UML_CEILING_UNITY: float = float(uml_engine.evaluate("<!0, !0>")[0])  # 1.0
UML_FLOOR_ZERO: float = float(uml_engine.evaluate("{!0, !0}")[0])     # 0.0


def uml_safe_scalar_div(numerator: float, denominator: float, eps: float = 1e-12) -> tuple[float, str]:
    """Evaluate scalar division using UML `!0` Logic Space boundary rules.

    Returns `(value, state_tag)`:
    - `|num| < eps` and `|den| < eps` -> `(1.0, "!0 (Singularity Bounded)")` via `<!0, !0>`
    - `|den| < eps` -> `(0.0, "Zero Division Floor")` via `<!0, 0>`
    - `NaN` or `Inf` -> `(1.0, "!0 (NaN/Inf Sanitized)")` via `<!0, !0>`
    - Standard finite ratio -> `(num / den, "Standard Flow")`
    """
    num_zero = (not math.isfinite(numerator)) or abs(numerator) < eps
    den_zero = (not math.isfinite(denominator)) or abs(denominator) < eps

    if not math.isfinite(numerator) or not math.isfinite(denominator):
        return UML_CEILING_UNITY, "!0 (NaN/Inf Sanitized)"
    if num_zero and den_zero:
        val, _, _, _ = uml_engine.evaluate("<!0, !0>")
        return float(val), "!0 (Singularity Bounded)"
    if den_zero:
        val, _, _, _ = uml_engine.evaluate("<!0, 0>")
        return float(val), "Zero Division Floor"

    val, _, _, _ = uml_engine.evaluate(f"<{numerator}, {denominator}>")
    if val == "!0" or not isinstance(val, (int, float)) or not math.isfinite(val):
        return UML_CEILING_UNITY, "!0 (NaN/Inf Sanitized)"
    return float(val), "Standard Flow"


class _UMLSafeDivAutograd(torch.autograd.Function):
    """Differentiable PyTorch autograd gate implementing UML `!0` division."""

    @staticmethod
    def forward(ctx, numerator: torch.Tensor, denominator: torch.Tensor, eps: float = 1e-12) -> torch.Tensor:
        ctx.eps = eps
        ctx.save_for_backward(numerator, denominator)

        num_zero = numerator.abs() < eps
        den_zero = denominator.abs() < eps
        both_zero = num_zero & den_zero

        # Safe denominator avoids IEEE-754 division by zero before boundary projection
        safe_den = torch.where(den_zero, torch.ones_like(denominator), denominator)
        raw_ratio = numerator / safe_den

        # Apply UML boundary rules:
        # 1. 0 / 0 -> <!0, !0> = 1.0 (UML_CEILING_UNITY)
        # 2. x / 0 -> <!0, 0>  = 0.0 (UML_FLOOR_ZERO)
        # 3. NaN/Inf -> 1.0
        out = torch.where(den_zero, torch.full_like(raw_ratio, UML_FLOOR_ZERO), raw_ratio)
        out = torch.where(both_zero, torch.full_like(out, UML_CEILING_UNITY), out)
        out = torch.where(torch.isfinite(out), out, torch.full_like(out, UML_CEILING_UNITY))
        return out

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor):
        numerator, denominator = ctx.saved_tensors
        eps = ctx.eps

        # Sanitize incoming upstream gradient if it contains NaN/Inf (!0 Dirac impulse protection)
        clean_grad = torch.where(
            torch.isfinite(grad_output),
            grad_output,
            torch.full_like(grad_output, UML_FLOOR_ZERO),
        )

        num_zero = numerator.abs() < eps
        den_zero = denominator.abs() < eps
        both_zero = num_zero & den_zero

        safe_den = torch.where(den_zero, torch.ones_like(denominator), denominator)

        # At 0/0 (!0 singularity), UML projects to unity multiplier (1.0) for numerator
        # and floors the unstable -num/den^2 term to 0.0.
        grad_num = torch.where(
            both_zero,
            clean_grad * UML_CEILING_UNITY,
            torch.where(den_zero, torch.zeros_like(clean_grad), clean_grad / safe_den),
        )
        grad_den = torch.where(
            den_zero,
            torch.zeros_like(clean_grad),
            -clean_grad * numerator / (safe_den * safe_den),
        )

        grad_num = torch.where(torch.isfinite(grad_num), grad_num, torch.zeros_like(grad_num))
        grad_den = torch.where(torch.isfinite(grad_den), grad_den, torch.zeros_like(grad_den))
        return grad_num, grad_den, None


def uml_safe_tensor_div(numerator: torch.Tensor, denominator: torch.Tensor | float, eps: float = 1e-12) -> torch.Tensor:
    """Tensor division governed by the UML `!0` autograd boundary gate."""
    if not torch.is_tensor(denominator):
        denominator = torch.tensor(float(denominator), dtype=numerator.dtype, device=numerator.device)
    elif denominator.dtype != numerator.dtype or denominator.device != numerator.device:
        denominator = denominator.to(dtype=numerator.dtype, device=numerator.device)
    return _UMLSafeDivAutograd.apply(numerator, denominator, eps)


def uml_attention_divisor(head_dim: int | float, surface: float) -> float:
    """Compute attention divisor `head_dim ** (surface / 2)` through the UML Engine."""
    if head_dim <= 0:
        val, _, _, _ = uml_engine.evaluate("<!0, !0>")
        return float(val)
    exp = float(surface) / 2.0
    val, _, _, _ = uml_engine.evaluate(f"^{exp}[{float(head_dim)}]")
    if val == "!0" or not isinstance(val, (int, float)) or val <= 0 or not math.isfinite(val):
        return UML_CEILING_UNITY
    return float(val)


def uml_sanitize_loss(loss: torch.Tensor) -> tuple[torch.Tensor, bool]:
    """Ensure loss is finite; if a `!0` singularity (`NaN`/`Inf`) occurs, snap to a safe zero-gradient anchor."""
    if torch.isfinite(loss).all():
        return loss, False
    # Replace non-finite loss with a zero-valued graph-connected anchor so backward() doesn't poison weights
    sanitized = torch.where(torch.isfinite(loss), loss, torch.zeros_like(loss))
    return sanitized, True


def uml_clip_and_stabilize_gradients(
    parameters: Iterable[nn.Parameter],
    max_norm: float = 1.0,
    loss_value: float | None = None,
    eps: float = 1e-12,
) -> dict[str, float | int | str]:
    """UML Boundary-Gated Gradient Stabilizer for INN neurons.

    1. Scans all parameter gradients for `NaN`/`Inf` (`!0` Dirac spikes) and projects them to `0.0` floor.
    2. Computes total L2 gradient norm `||g||_2`.
    3. Evaluates the boundary scaling factor via `uml_safe_scalar_div`:
       - If `loss == 0` and `||g|| == 0` (`0/0` singularity): snaps to `<!0, !0> = 1.0` (`!0 (Singularity Bounded)`).
       - If `||g|| > max_norm`: scales gradients by `<max_norm, ||g||>` through the UML Engine.
       - If `||g|| <= max_norm`: preserves standard flow (`1.0` multiplier).
    """
    params = [p for p in parameters if p.grad is not None]
    if not params:
        return {
            "grad_norm": 0.0,
            "scale": UML_CEILING_UNITY,
            "state_tag": "!0 (Singularity Bounded)",
            "sanitized_elements": 0,
        }

    sanitized_elements = 0
    sq_sum = 0.0
    for p in params:
        g = p.grad.data
        non_finite = ~torch.isfinite(g)
        if non_finite.any():
            sanitized_elements += int(non_finite.sum().item())
            g.masked_fill_(non_finite, UML_FLOOR_ZERO)
        sq_sum += float(g.float().pow(2).sum().item())

    grad_norm = math.sqrt(sq_sum)
    ref_num = abs(float(loss_value)) if loss_value is not None else grad_norm

    if grad_norm < eps and ref_num < eps:
        scale, state_tag = uml_safe_scalar_div(0.0, 0.0, eps=eps)
    elif grad_norm > max_norm:
        scale, state_tag = uml_safe_scalar_div(max_norm, grad_norm, eps=eps)
        for p in params:
            p.grad.data.mul_(scale)
    else:
        scale = UML_CEILING_UNITY
        state_tag = "!0 (NaN/Inf Sanitized)" if sanitized_elements > 0 else "Standard Flow"

    return {
        "grad_norm": grad_norm,
        "scale": float(scale),
        "state_tag": state_tag,
        "sanitized_elements": sanitized_elements,
    }
