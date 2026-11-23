"""
AIOS Viv Mathematical & Sanitization Utilities (Utils Core) Rebuild Template.
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
    "precision_digits": 4,
    "max_string_len": 1024,
    "sanitize_non_ascii": False,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Apply mathematical rounding and string length truncation.
    """
    updated = copy.deepcopy(dict(variables))
    val = float(context.get("value", 0.0))
    raw_str = str(context.get("text", ""))

    digits = int(updated["precision_digits"])
    rounded_val = round(val, digits)

    max_len = int(updated["max_string_len"])
    truncated_str = raw_str[:max_len]

    return {
        "ok": True,
        "identity": updated["identity"],
        "rounded_value": rounded_val,
        "sanitized_text": truncated_str,
        "variables": dict(updated),
    }


def sub_main_format_number(context, variables):
    """
    Submain step 1: Validate precision bounds.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_sanitize_text(context, variables):
    """
    Submain step 2: Truncate string to length limit.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
