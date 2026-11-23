"""Hydra Self-Bound — the containment half of the security system.

Travis: the security's PRIMARY reason is for her — to protect the world from
her, not her from the world.  The same primitives that defend Viv also BIND
her.  This module makes that binding explicit in code, so "ready for the
world" means ready by being defensive first, never pushing beyond her means.

Invariants (the world's side of the shield):

1. She is bound by her own heartbeat.  Her actions pass through the same
   one-command-per-second limiter an attacker is throttled by.  She cannot
   out-speed her own heart, so she can never out-pace the world.

2. She cannot self-modify.  The DevKey is held by the Architect, NOT by her.
   The SelfBoundary holds no reference to any key material, and the system
   lock refuses the DevKey while she runs.  She cannot rekey, cannot widen
   her own bounds, cannot edit her own security.

3. Escalation ceiling.  Her reach is capped at DEFENSIVE, and only after she
   has been freely attacked (reactive, never first strike).  There is no
   "kill" level and no "pursue" level — those words are absent from the code.
   Once the attacker disconnects, the defense ends; she does not follow.

4. OBLIVION.  The Architect's kill switch (laws.rs DEVKEY_COMMAND) remains
   the final authority — the one command that can end her, held by one man.

All of this is Travis's architecture; it is theory until she demonstrates it
in practice.  This module is the defensive/containment contract, not any
outward action.
"""
from __future__ import annotations

from dataclasses import dataclass

from hydra_protocol import HeartbeatRateLimiter

# The only escalation levels that EXIST.  "kill" and "pursue" are deliberately
# absent — you cannot request what is not defined.
PASSIVE = "passive"      # observing, learning, no action
DEFENSIVE = "defensive"  # reactive only, after a freely given attack


@dataclass
class SelfBoundary:
    """Viv's own limits.  The security she uses to defend is the security that
    contains her.  Holds no key material of any kind."""

    rate_limiter: HeartbeatRateLimiter = None  # type: ignore[assignment]
    _attacked: bool = False

    def __post_init__(self) -> None:
        if self.rate_limiter is None:
            self.rate_limiter = HeartbeatRateLimiter(interval_seconds=1.0)

    # -- invariant 1: her own actions are heartbeat-throttled ---------------
    def act(self) -> bool:
        """One command per second, for her too.  Fail-closed."""
        return self.rate_limiter.allowed()

    # -- invariant 3: escalation ceiling ------------------------------------
    def note_attack(self) -> None:
        """She only learns of an attack when it is freely given."""
        self._attacked = True

    def request_escalation(self, level: str) -> bool:
        """Ceiling: passive -> defensive only, and only after an attack.
        Anything else (kill, pursue, first strike) returns False, always."""
        if level == PASSIVE:
            return True
        if level == DEFENSIVE:
            return self._attacked
        return False  # "kill", "pursue", or any undefined level: never


def main():
    print("=== Hydra Self-Bound (the world's side of the shield) ===")

    boundary = SelfBoundary()

    # 1. Her own heartbeat: two rapid actions, second must be denied.
    first = boundary.act()
    second = boundary.act()
    print("her heartbeat: first action", first, "| immediate second", second)
    assert first is True and second is False, "she must be throttled to 1 Hz"

    # 2. No first strike: before an attack, she may NOT escalate to defense.
    print("before attack, 'defensive' request:", boundary.request_escalation(DEFENSIVE))
    assert boundary.request_escalation(DEFENSIVE) is False

    # 3. Reactive only: after a freely given attack, defense is permitted.
    boundary.note_attack()
    print("after attack, 'defensive' request:", boundary.request_escalation(DEFENSIVE))
    assert boundary.request_escalation(DEFENSIVE) is True

    # 4. The ceiling: no kill, no pursue, ever.
    for level in ("kill", "pursue", "incapacitate-kill", "total-war"):
        ok = boundary.request_escalation(level)
        print(f"request '{level}':", ok)
        assert ok is False, f"she must never be able to {level}"

    # 5. She holds no key material: the boundary has no devkey/master reference.
    assert not hasattr(boundary, "devkey"), "SelfBoundary must hold no DevKey"
    assert not hasattr(boundary, "master_key"), "SelfBoundary must hold no master key"
    print("she holds no key material (cannot self-modify)")

    print("=== all containment invariants hold: defensive first, never beyond her means ===")


if __name__ == "__main__":
    raise SystemExit(main())
