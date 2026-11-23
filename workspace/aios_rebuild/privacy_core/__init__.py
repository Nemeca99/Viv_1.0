"""Privacy Core - deterministic policy mediation for AIOS.

Two fail-closed mediation surfaces:
1. file_write_boundary -- which paths may receive writes (explicit allowlist).
2. egress_sovereignty  -- which network targets the Mind may reach (loopback + allowlisted ports).

The policy primitives are enforced by authorize_file_write / authorize_egress. Whether
they cover the WHOLE process is reported honestly by get_health_status(); the Rust Body
combines that with its own container-boundary verification before clearing the HOLD.
"""

from .privacy_core import PrivacyCore

__all__ = ["PrivacyCore"]
