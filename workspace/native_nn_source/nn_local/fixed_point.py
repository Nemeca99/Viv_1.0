"""Integer reference math for the custom CUDA bucket mechanism."""

from __future__ import annotations

from dataclasses import dataclass
from math import isqrt


SCALE = 1_000_000
GLOBAL_SHARE = 150_000
HEAD_SHARE = 800_000
REFLECTION_SHARE = 50_000
EXPLORATION_FLOOR = 100
PASS_RATE = 900_000
FAIL_HEAD_RATE = 120_000
FAIL_LINK_RATE = 150_000
COMPETITION_POWER = 12
MASK64 = (1 << 64) - 1


class RouteHoldError(RuntimeError):
    """No child remains supported by both parent heads and routed links."""


def _u64(value: int) -> int:
    return value & MASK64


def splitmix64(value: int) -> int:
    value = _u64(value + 0x9E3779B97F4A7C15)
    value = _u64((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9)
    value = _u64((value ^ (value >> 27)) * 0x94D049BB133111EB)
    return _u64(value ^ (value >> 31))


def toward_one(value: int, rate: int) -> int:
    return min(SCALE, value + rate * (SCALE - value) // SCALE)


def toward_zero(value: int, rate: int) -> int:
    return max(0, value - rate * value // SCALE)


def powered_strength(combined: int) -> int:
    value = SCALE
    base = max(1, combined)
    for _ in range(COMPETITION_POWER):
        value = value * base // SCALE
    return max(EXPLORATION_FLOOR, value)


@dataclass(frozen=True)
class FixedAttempt:
    path: tuple[int, ...]
    strengths: tuple[int, ...]


@dataclass(frozen=True)
class TriadicSettlement:
    """Settled three-channel state and its independent motion residual."""

    channels: tuple[int, int, int]
    quality: int
    rid: int
    ticks: int
    zero_confirmations: int
    state: str


@dataclass(frozen=True)
class ResourceRidState:
    """One bounded resource heartbeat controlling the next work cadence."""

    rid: int
    delay_microseconds: int
    bottleneck: str
    headrooms: dict[str, int]
    stop: bool


def govern_resource_rid(
    headrooms: dict[str, int], *, slowdown_microseconds: int = 1_000_000
) -> ResourceRidState:
    """Use the least safe headroom; zero stops before any dependent division."""
    if not headrooms:
        raise ValueError("resource RID requires at least one bounded metric")
    if slowdown_microseconds < 0:
        raise ValueError("resource RID slowdown must be nonnegative")
    bounded = {
        str(name): max(0, min(SCALE, int(value)))
        for name, value in headrooms.items()
    }
    bottleneck = min(bounded, key=lambda name: (bounded[name], name))
    rid = bounded[bottleneck]
    if rid == 0:
        return ResourceRidState(0, 0, bottleneck, bounded, True)
    delay = ((SCALE - rid) * slowdown_microseconds) // SCALE
    return ResourceRidState(rid, delay, bottleneck, bounded, False)


def triadic_step(channels: tuple[int, int, int]) -> tuple[tuple[int, int, int], int, int]:
    """Apply the synchronous 3x3 RID matrix using fixed-point integers."""
    a, b, c = (max(0, min(SCALE, int(value))) for value in channels)
    updated = ((a + b) // 2, (b + c) // 2, (c + a) // 2)
    total = sum(updated)
    # If d_i = x_i - mean, then 3*d_i = 3*x_i-total. RMS(d)^2=sum((3*d)^2)/27.
    deviation_square_sum = sum((3 * value - total) ** 2 for value in updated)
    sync_error = isqrt(deviation_square_sum // 27)
    motion_error = max(abs(updated[0] - a), abs(updated[1] - b), abs(updated[2] - c))
    return updated, sync_error, motion_error


def settle_triadic(
    channels: tuple[int, int, int], *, max_ticks: int = 64, confirmations: int = 3
) -> TriadicSettlement:
    """Settle until RID is exactly zero for consecutive frozen heartbeats."""
    if max_ticks < 1 or confirmations < 1:
        raise ValueError("triadic bounds must be positive")
    current = tuple(max(0, min(SCALE, int(value))) for value in channels)
    zero_count = 0
    rid = SCALE
    for tick in range(1, max_ticks + 1):
        current, sync_error, motion_error = triadic_step(current)
        rid = min(SCALE, sync_error + motion_error)
        zero_count = zero_count + 1 if rid == 0 else 0
        if zero_count >= confirmations:
            return TriadicSettlement(
                current, sum(current) // 3, 0, tick, zero_count, "PASS"
            )
    return TriadicSettlement(
        current, sum(current) // 3, rid, max_ticks, zero_count, "HOLD"
    )


def attempt(
    *,
    positions: int,
    candidates: int,
    inventory: list[int],
    heads: list[int],
    links: list[int],
    seed_state: int,
    attempt_seed: int,
    context_bias: list[int] | None = None,
) -> FixedAttempt:
    if type(positions) is not int or type(candidates) is not int or not 0 < positions <= 64 or not 0 < candidates <= 4096:
        raise ValueError("fixed bucket dimensions outside native bounds")
    # Negative inventory can satisfy the sum while selecting nonexistent tokens.
    if len(inventory) != candidates or any(type(value) is not int or value < 0 for value in inventory) or sum(inventory) != positions:
        raise ValueError("inventory does not match bucket dimensions")
    if len(heads) != positions * candidates:
        raise ValueError("head shape mismatch")
    if len(links) != (candidates + 1) * candidates:
        raise ValueError("transition shape mismatch")
    if any(type(value) is not int or not 0 <= value <= SCALE for row in (heads, links) for value in row):
        raise ValueError("route weights outside fixed-point bounds")
    context = context_bias if context_bias is not None else [SCALE // 2] * candidates
    if len(context) != candidates or any(type(value) is not int or not 0 <= value <= SCALE for value in context):
        raise ValueError("context bias shape or bounds mismatch")

    remaining = inventory.copy()
    source_row = 0
    rotor_state = seed_state % SCALE
    remaining_total = positions
    random_state = splitmix64(attempt_seed ^ seed_state)
    path: list[int] = []
    selected_strengths: list[int] = []

    for position in range(positions):
        reflection = SCALE - rotor_state
        strengths = [0] * candidates
        total = 0
        for candidate in range(candidates):
            if remaining[candidate] == 0:
                continue
            global_weight = links[source_row * candidates + candidate]
            head_weight = heads[position * candidates + candidate]
            if global_weight == 0 or head_weight == 0:
                continue
            key = (candidate + 1) * SCALE // candidates
            reflection_fit = SCALE - min(SCALE, abs(key - reflection))
            combined = (
                GLOBAL_SHARE * global_weight
                + HEAD_SHARE * head_weight
                + REFLECTION_SHARE * reflection_fit
            ) // SCALE
            combined = max(1, min(SCALE, combined + (context[candidate] - SCALE // 2) // 10))
            strengths[candidate] = powered_strength(combined)
            total += strengths[candidate]

        random_state = splitmix64(random_state + position + 1)
        if total == 0:
            raise RouteHoldError("HOLD_NO_SUPPORTED_ROUTE")
        draw = random_state % total
        cumulative = 0
        selected = 0
        for candidate, strength in enumerate(strengths):
            if strength == 0:
                continue
            cumulative += strength
            selected = candidate
            if draw < cumulative:
                break
        path.append(selected)
        selected_strengths.append(strengths[selected])
        remaining[selected] -= 1
        remaining_total -= 1
        source_row = selected + 1
        key = (selected + 1) * SCALE // candidates
        position_factor = SCALE + (position + 1) * SCALE // positions
        stepped = (
            (rotor_state + key) * position_factor // SCALE
            + remaining_total * SCALE // positions
        )
        rotor_state = stepped % SCALE

    return FixedAttempt(tuple(path), tuple(selected_strengths))


def apply_verdict(
    *,
    path: tuple[int, ...],
    candidates: int,
    heads: list[int],
    links: list[int],
    uses: list[int],
    pass_hits: list[int],
    fail_hits: list[int],
    passed: bool,
    link_pass_hits: list[int] | None = None,
    link_fail_hits: list[int] | None = None,
) -> None:
    # Validate the entire consequence before the first weight/counter mutation.
    # In particular, negative indices and truthy strings must never teach a path.
    if type(passed) is not bool:
        raise ValueError("verdict must be a boolean CPU consequence")
    if type(candidates) is not int or not 0 < candidates <= 4096 or not 0 < len(path) <= 64:
        raise ValueError("verdict dimensions outside native bounds")
    if any(type(selected) is not int or not 0 <= selected < candidates for selected in path):
        raise ValueError("verdict route references an invalid candidate")
    head_size, link_size = len(path) * candidates, (candidates + 1) * candidates
    for row, size, weights, optional in (
        (heads, head_size, True, False), (links, link_size, True, False),
        (uses, head_size, False, False), (pass_hits, head_size, False, False), (fail_hits, head_size, False, False),
        (link_pass_hits, link_size, False, True), (link_fail_hits, link_size, False, True),
    ):
        if row is None and optional:
            continue
        if not isinstance(row, list) or len(row) != size or any(
            type(value) is not int or value < 0 or (weights and value > SCALE) for value in row
        ):
            raise ValueError("verdict state shape or bounds mismatch")
    for position, selected in enumerate(path):
        head_index = position * candidates + selected
        source_row = 0 if position == 0 else path[position - 1] + 1
        link_index = source_row * candidates + selected
        uses[head_index] += 1
        if passed:
            pass_hits[head_index] += 1
            if link_pass_hits is not None:
                link_pass_hits[link_index] += 1
            heads[head_index] = toward_one(heads[head_index], PASS_RATE)
            links[link_index] = toward_one(links[link_index], PASS_RATE)
        else:
            fail_hits[head_index] += 1
            if link_fail_hits is not None:
                link_fail_hits[link_index] += 1
            heads[head_index] = toward_zero(heads[head_index], FAIL_HEAD_RATE)
            links[link_index] = toward_zero(links[link_index], FAIL_LINK_RATE)


__all__ = [
    "FixedAttempt",
    "TriadicSettlement",
    "SCALE",
    "RouteHoldError",
    "apply_verdict",
    "attempt",
    "powered_strength",
    "splitmix64",
    "settle_triadic",
    "triadic_step",
    "toward_one",
    "toward_zero",
]
