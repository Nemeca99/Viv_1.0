"""Recursive role-separated RID: user, assistant, mediator, then master."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from .fixed_point import TriadicSettlement, settle_triadic

@dataclass(frozen=True)
class NestedRidSettlement:
    user: TriadicSettlement
    assistant: TriadicSettlement
    mediator: TriadicSettlement
    master: TriadicSettlement

    @property
    def state(self) -> str:
        # Master-local convergence does not establish whole-tree readiness.
        # Preserve individual arithmetic results and the existing as_dict ABI.
        return "PASS" if all(item.state == "PASS" for item in (self.user, self.assistant, self.mediator, self.master)) else "HOLD"

    def as_dict(self) -> dict:
        return asdict(self)

def settle_nested_rid(user: tuple[int,int,int], assistant: tuple[int,int,int], mediator: tuple[int,int,int], *, max_ticks: int=64, confirmations: int=3) -> NestedRidSettlement:
    lower=[settle_triadic(group,max_ticks=max_ticks,confirmations=confirmations) for group in (user,assistant,mediator)]
    master=settle_triadic(tuple(item.quality for item in lower),max_ticks=max_ticks,confirmations=confirmations)
    return NestedRidSettlement(lower[0],lower[1],lower[2],master)
