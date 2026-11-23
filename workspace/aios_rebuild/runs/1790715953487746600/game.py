"""
AIOS Viv World Environment Tick Loop (Game Core) Rebuild Template.
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
    "starting_food": 20,
    "max_farms": 10,
    "farm_cost": 8,
    "rest_recovery": 5,
    "tick_limit": 8760,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Step the discrete survival world tick and update biological resource states.
    """
    updated = copy.deepcopy(dict(variables))
    state = dict(context.get("state", {"food": updated["starting_food"], "farms": 0, "health": 100}))
    action = str(context.get("action", "wait"))

    food = int(state.get("food", updated["starting_food"]))
    farms = int(state.get("farms", 0))
    health = int(state.get("health", 100))

    if action == "buy_farm" and food >= int(updated["farm_cost"]):
        food -= int(updated["farm_cost"])
        farms += 1
    elif action == "rest":
        health = min(100, health + int(updated["rest_recovery"]))

    # End-of-tick farm yield & upkeep
    food += farms * 2
    food -= 1  # Base metabolism

    alive = health > 0 and food >= 0

    return {
        "ok": True,
        "identity": updated["identity"],
        "action": action,
        "next_state": {"food": max(0, food), "farms": farms, "health": health},
        "alive": alive,
        "variables": dict(updated),
    }


def sub_main_validate_action(context, variables):
    """
    Submain step 1: Validate action vocabulary against game rules.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_apply_metabolism(context, variables):
    """
    Submain step 2: Compute farm production and metabolic consumption.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
