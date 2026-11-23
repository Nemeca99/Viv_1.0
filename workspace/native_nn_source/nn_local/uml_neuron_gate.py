"""UML Logic Space (!0) and division-by-zero gate for Steel Brain neurons.

Connects the rebuilt Universal Machine Language (UML) calculator in
``L:\\LocalCoder\\UML_Calc\\uml_engine.py`` directly to the Steel Brain neuron
network (``L:\\Standalone\\NN\\nn_local``) and its PyTorch proposal organ
(``nn_local.transformer`` / ``tools.train_dictionary_gpt`` / ``tools.train_wikipedia_batch_gpt``).

Key invariants:
1. Fixed-point neuron ratios (SCALE = 1,000,000) resolve ``0 / 0`` to the UML
   ``!0`` neutral equilibrium (``SCALE // 2 = 500,000``) or unity boundary
   (``SCALE = 1,000,000``) instead of throwing ``ZeroDivisionError``.
2. Non-zero fixed-point numerators divided by ``0`` resolve to ``HOLD_ZERO_DIVISOR``
   or clamp to the ``SCALE`` ceiling, preserving Steel Brain's zero-stop RID rule.
3. PyTorch proposal-organ masked losses (``(losses * mask).sum() / mask.sum()``)
   and temperature scaling (``logits / temperature``) route through the UML
   ``!0`` autograd boundary so zero-mask batches or near-zero temperatures
   never poison neuron weights with ``NaN`` or ``Inf``.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .fixed_point import SCALE, TriadicSettlement, settle_triadic

# Link to L:\LocalCoder\UML_Calc if present on L:\
_UML_CALC_DIR = Path(r"L:\LocalCoder\UML_Calc")
if _UML_CALC_DIR.is_dir() and str(_UML_CALC_DIR) not in sys.path:
    sys.path.insert(0, str(_UML_CALC_DIR))

try:
    import uml_engine as _uml_engine  # type: ignore[import-not-found]
    HAS_UML_ENGINE = True
except Exception:
    _uml_engine = None
    HAS_UML_ENGINE = False

try:
    import torch
    from torch import Tensor
    HAS_TORCH = True
except Exception:
    torch = None  # type: ignore[assignment]
    Tensor = Any  # type: ignore[assignment,misc]
    HAS_TORCH = False


UML_FIXED_UNITY: int = SCALE
UML_FIXED_NEUTRAL: int = SCALE // 2
UML_EPS: float = 1e-12


@dataclass(frozen=True)
class UMLFixedDivisionResult:
    """Fixed-point UML division outcome on the [0, SCALE] Steel Brain lattice."""

    numerator: int
    denominator: int
    value: int
    uml_symbol: str
    logic_space_triggered: bool
    state: str


def uml_eval_expression(expr: str) -> float | str:
    """Evaluate a raw UML bracket expression via ``uml_engine.evaluate``."""
    if HAS_UML_ENGINE and _uml_engine is not None:
        res, _, _, _ = _uml_engine.evaluate(expr)
        if isinstance(res, complex):
            return float(res.real)
        if res == "!0":
            return "!0"
        return float(res)
    if expr.strip() in ("<0,0>", "<0, 0>", "<!0,!0>", "<!0, !0>"):
        return "!0"
    raise RuntimeError("uml_engine is not available")


def uml_fixed_div(
    numerator: int,
    denominator: int,
    *,
    scale: int = SCALE,
    zero_over_zero: int = UML_FIXED_NEUTRAL,
    clamp_ceiling: bool = True,
) -> UMLFixedDivisionResult:
    """Fixed-point UML division ``<numerator, denominator>`` scaled to ``scale``.

    - ``<0, 0>`` -> ``!0`` (Logic Space): projects to ``zero_over_zero``
      (defaults to ``SCALE // 2 = 500,000`` neutral equilibrium for unactivated
      neuron links, or ``SCALE`` when unity projection is requested).
    - ``<N, 0>`` (``N > 0``) -> ``+!0`` (boundary ceiling): projects to ``scale``
      and flags ``HOLD_ZERO_DIVISOR`` so callers can either clamp or hold.
    - ``<N, D>`` (``D > 0``) -> standard integer fixed-point ``(N * scale) // D``.
    """
    num = int(numerator)
    den = int(denominator)
    if den == 0:
        if num == 0:
            sym = "!0"
            if HAS_UML_ENGINE and _uml_engine is not None:
                raw, _, _, _ = _uml_engine.evaluate("<0, 0>")
                sym = str(raw)
            bounded = max(0, min(scale, int(zero_over_zero)))
            return UMLFixedDivisionResult(
                numerator=num,
                denominator=den,
                value=bounded,
                uml_symbol=sym,
                logic_space_triggered=True,
                state="PASS_UML_LOGIC_SPACE",
            )
        ceiling = scale if num > 0 else 0
        return UMLFixedDivisionResult(
            numerator=num,
            denominator=den,
            value=ceiling if clamp_ceiling else 0,
            uml_symbol="+!0" if num > 0 else "-!0",
            logic_space_triggered=True,
            state="HOLD_ZERO_DIVISOR",
        )

    raw_val = (num * scale) // den
    bounded_val = max(0, min(scale, raw_val)) if clamp_ceiling else raw_val
    return UMLFixedDivisionResult(
        numerator=num,
        denominator=den,
        value=bounded_val,
        uml_symbol=str(bounded_val),
        logic_space_triggered=False,
        state="PASS",
    )


def uml_fixed_mean(
    values: Sequence[int],
    *,
    neutral: int = UML_FIXED_NEUTRAL,
) -> int:
    """Compute fixed-point mean of neuron link weights with UML ``<0, 0> -> !0``."""
    if not values:
        return uml_fixed_div(0, 0, zero_over_zero=neutral).value
    total = sum(int(v) for v in values)
    count = len(values)
    # Unscaled integer average: total / count
    return total // count


def uml_bayesian_rate(
    pass_hits: int,
    fail_hits: int,
    *,
    laplace_prior: int = 1,
    scale: int = SCALE,
) -> int:
    """Compute neuron route probability ``(pass + prior) * SCALE // (pass + fail + 2*prior)``.

    Even if ``laplace_prior == 0`` and ``pass_hits == fail_hits == 0``, UML
    ``<0, 0> -> !0`` resolves cleanly to ``SCALE // 2`` (neutral 0.500000)
    without ``ZeroDivisionError``.
    """
    p = max(0, int(pass_hits))
    f = max(0, int(fail_hits))
    prior = max(0, int(laplace_prior))
    num = p + prior
    den = p + f + 2 * prior
    return uml_fixed_div(num, den, scale=scale, zero_over_zero=scale // 2).value


def uml_settle_neuron_triad(
    channels: tuple[int, int, int],
    *,
    max_ticks: int = 64,
    confirmations: int = 3,
) -> TriadicSettlement:
    """Settle a 3-channel neuron triad using ``fixed_point.settle_triadic``."""
    return settle_triadic(channels, max_ticks=max_ticks, confirmations=confirmations)


if HAS_TORCH:

    class _UMLSafeDivAutograd(torch.autograd.Function):
        """Autograd-safe tensor division implementing UML ``!0`` boundary rules."""

        @staticmethod
        def forward(
            ctx: Any,
            numerator: Tensor,
            denominator: Tensor,
            eps: float,
            max_mag: float,
        ) -> Tensor:
            zero_den = denominator.abs() < eps
            zero_num = numerator.abs() < eps
            both_zero = zero_den & zero_num

            sign = torch.where(
                denominator >= 0,
                torch.ones_like(denominator),
                -torch.ones_like(denominator),
            )
            safe_den = torch.where(zero_den, sign * eps, denominator)
            raw = numerator / safe_den

            # UML <0, 0> -> !0 -> 1.0 unity identity; <x, 0> -> bounded saturation
            out = torch.where(
                both_zero,
                torch.ones_like(raw),
                torch.clamp(raw, min=-max_mag, max=max_mag),
            )
            ctx.save_for_backward(numerator, safe_den, zero_den, both_zero)
            ctx.max_mag = max_mag
            return out

        @staticmethod
        def backward(
            ctx: Any, grad_output: Tensor
        ) -> tuple[Tensor, Tensor, None, None]:
            numerator, safe_den, zero_den, both_zero = ctx.saved_tensors
            max_mag = ctx.max_mag

            clean_grad = torch.nan_to_num(
                grad_output, nan=0.0, posinf=max_mag, neginf=-max_mag
            )
            grad_num = clean_grad / safe_den
            grad_den = -clean_grad * numerator / (safe_den * safe_den)

            # At <0, 0> -> !0 (unity) or singular boundary, zero denominator gradient
            grad_num = torch.where(
                both_zero,
                torch.zeros_like(grad_num),
                torch.clamp(grad_num, min=-max_mag, max=max_mag),
            )
            grad_den = torch.where(
                zero_den,
                torch.zeros_like(grad_den),
                torch.clamp(grad_den, min=-max_mag, max=max_mag),
            )
            return grad_num, grad_den, None, None


def uml_safe_tensor_div(
    numerator: Tensor,
    denominator: Tensor | float,
    *,
    eps: float = UML_EPS,
    max_mag: float = 1e6,
) -> Tensor:
    """Divide PyTorch tensors using the UML ``!0`` boundary gate."""
    if not HAS_TORCH:
        raise RuntimeError("PyTorch is required for uml_safe_tensor_div")
    if not isinstance(denominator, torch.Tensor):
        den_tensor = torch.full_like(numerator, float(denominator))
    else:
        den_tensor = denominator
    return _UMLSafeDivAutograd.apply(numerator, den_tensor, eps, max_mag)


def uml_masked_loss(
    losses: Tensor,
    mask: Tensor,
    *,
    eps: float = UML_EPS,
) -> Tensor:
    """Compute ``(losses * mask).sum() / mask.sum()`` with UML ``!0`` protection.

    If ``mask.sum() == 0`` (an all-masked batch), standard PyTorch produces
    ``0.0 / 0.0 = NaN``, which destroys the entire transformer proposal organ
    on backward(). With the UML gate, ``<0, 0>`` resolves cleanly with zero
    gradient so the optimizer step is a safe no-op.
    """
    if not HAS_TORCH:
        raise RuntimeError("PyTorch is required for uml_masked_loss")
    masked_sum = (losses * mask).sum()
    mask_count = mask.sum()
    if float(mask_count.detach().abs().item()) < eps:
        return masked_sum * 0.0
    return uml_safe_tensor_div(masked_sum, mask_count, eps=eps)


def uml_stabilize_gradients(
    parameters: Iterable[Any],
    *,
    max_norm: float = 1.0,
) -> float:
    """Sanitize ``NaN``/``Inf`` gradients via UML projection and clip norm."""
    if not HAS_TORCH:
        raise RuntimeError("PyTorch is required for uml_stabilize_gradients")
    params = [p for p in parameters if getattr(p, "grad", None) is not None]
    for p in params:
        grad = p.grad
        if grad is not None and not torch.isfinite(grad).all():
            p.grad = torch.nan_to_num(grad, nan=0.0, posinf=max_norm, neginf=-max_norm)
    if not params:
        return 0.0
    norm = float(torch.nn.utils.clip_grad_norm_(params, max_norm))
    if not math.isfinite(norm):
        for p in params:
            if p.grad is not None:
                p.grad.zero_()
        return 0.0
    return norm


__all__ = [
    "HAS_TORCH",
    "HAS_UML_ENGINE",
    "UMLFixedDivisionResult",
    "UML_EPS",
    "UML_FIXED_NEUTRAL",
    "UML_FIXED_UNITY",
    "uml_bayesian_rate",
    "uml_eval_expression",
    "uml_fixed_div",
    "uml_fixed_mean",
    "uml_masked_loss",
    "uml_safe_tensor_div",
    "uml_settle_neuron_triad",
    "uml_stabilize_gradients",
]
