from typing import Any, Mapping

# TEMPLATE VARIABLES BEGIN
VARIABLES = {
    "message": "template-fixture",
    "suffix": "ok",
}
# TEMPLATE VARIABLES END


def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "message": variables["message"],
        "suffix": variables["suffix"],
        "context_keys": sorted(str(key) for key in context),
        "variables": dict(variables),
    }
