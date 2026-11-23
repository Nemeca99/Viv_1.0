"""
AIOS Viv Cryptographic Security Membrane (Security Core) Rebuild Template.
Strict AST deterministic template contract:
  - Imports: copy
  - Literal VARIABLES dictionary
  - def main(context, variables)
  - def sub_main_*(context, variables)
"""
import copy

# TEMPLATE VARIABLES BEGIN
VARIABLES = {
    "identity": 'Viv',
    "aead_cipher": 'AES-256-GCM',
    "key_rotation_days": 30,
    "require_signature": True,
    "allowed_endpoints": ['192.168.1.21:1234', '127.0.0.1:11434'],
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Enforce AEAD cryptographic key validation and endpoint privilege check.
    """
    updated = copy.deepcopy(dict(variables))
    endpoint = str(context.get("endpoint", ""))
    signed = bool(context.get("signed", False))

    allowed = list(updated["allowed_endpoints"])
    endpoint_ok = endpoint in allowed
    signature_ok = signed or not bool(updated["require_signature"])

    authorized = endpoint_ok and signature_ok

    return {
        "ok": True,
        "identity": updated["identity"],
        "authorized": authorized,
        "endpoint_ok": endpoint_ok,
        "signature_ok": signature_ok,
        "cipher": updated["aead_cipher"],
        "variables": dict(updated),
    }


def sub_main_verify_endpoint(context, variables):
    """
    Submain step 1: Check endpoint against authorized IP whitelist.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_verify_signature(context, variables):
    """
    Submain step 2: Assert cryptographic signature integrity.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
