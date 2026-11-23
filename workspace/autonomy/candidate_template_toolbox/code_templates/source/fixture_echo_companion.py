from typing import Any, Mapping

# TEMPLATE VARIABLES BEGIN
VARIABLES = {"text": "template-companion", "tag": "alt"}
# TEMPLATE VARIABLES END

def main(context: Mapping[str, Any], variables: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, "text": variables["text"], "tag": variables["tag"], "context_keys": sorted(str(key) for key in context), "variables": dict(variables)}
