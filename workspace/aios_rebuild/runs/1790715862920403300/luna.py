"""
AIOS Viv Persona Synthesis & One Mouth Authority (Luna Core) Rebuild Template.
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
    "persona_name": "Viv AIOS",
    "voice_style": "warm_technical_companion",
    "one_mouth_rule": True,
    "max_output_tokens": 2048,
    "temperature": 0.2,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Synthesize persona framing and enforce the strict One Mouth authority rule.
    """
    updated = copy.deepcopy(dict(variables))
    raw_response = str(context.get("raw_response", ""))
    speaker_role = str(context.get("speaker_role", "Viv-Mind"))

    # Enforce One Mouth Rule: Only Viv-Mind is authorized to speak to the Architect
    authorized = (speaker_role == "Viv-Mind") or not bool(updated["one_mouth_rule"])

    if not authorized:
        final_speech = "[ONE_MOUTH_DENIED] Only Viv-Mind holds speech authority to the Architect."
    else:
        final_speech = f"[{updated['persona_name']}]: {raw_response}"

    return {
        "ok": True,
        "identity": updated["identity"],
        "authorized": authorized,
        "final_speech": final_speech,
        "persona": updated["persona_name"],
        "voice_style": updated["voice_style"],
        "variables": dict(updated),
    }


def sub_main_check_authority(context, variables):
    """
    Submain step 1: Validate speaker role against authority policy.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_format_persona(context, variables):
    """
    Submain step 2: Apply persona voice style and token constraints.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
