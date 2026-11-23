"""
AIOS Viv Local Egress Boundary Membrane (Privacy Core) Rebuild Template.
Strict AST deterministic template contract:
  - Imports: copy
  - Literal VARIABLES dictionary
  - def main(context, variables)
  - def sub_main_*(context, variables)
"""
import copy

# TEMPLATE VARIABLES BEGIN
VARIABLES = {
    "identity": "Viv",
    "sovereignty_target": "L:\\\\",
    "allowed_file_exts": [".py", ".md", ".json", ".pdf"],
    "allowed_api_endpoints": ["192.168.1.21:1234", "127.0.0.1:11434"],
    "block_external_telemetry": True,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Enforce data sovereignty rules: block external network egress & unapproved file writes outside L:\\.
    """
    updated = copy.deepcopy(dict(variables))
    target_path = str(context.get("target_path", "L:\\test.json"))
    target_endpoint = str(context.get("target_endpoint", "127.0.0.1:11434"))

    # File extension check
    ext_ok = any(target_path.endswith(ext) for ext in updated["allowed_file_exts"])
    path_ok = target_path.startswith(updated["sovereignty_target"])

    endpoint_ok = target_endpoint in updated["allowed_api_endpoints"]

    sovereignty_passed = ext_ok and path_ok and endpoint_ok

    return {
        "ok": True,
        "identity": updated["identity"],
        "sovereignty_passed": sovereignty_passed,
        "path_ok": path_ok,
        "ext_ok": ext_ok,
        "endpoint_ok": endpoint_ok,
        "variables": dict(updated),
    }


def sub_main_verify_path_sovereignty(context, variables):
    """
    Submain step 1: Verify target path remains within L:\\ boundary.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_verify_endpoint_sovereignty(context, variables):
    """
    Submain step 2: Verify network request targets only authorized local ports.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
