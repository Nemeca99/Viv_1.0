"""
AIOS Viv Hierarchical Task Decomposition Graph (Fractal Core) Rebuild Template.
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
    "max_depth": 5,
    "max_subtasks": 10,
    "require_parent_validation": True,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Decompose high-level goals into DAG task nodes with strict depth constraints.
    """
    updated = copy.deepcopy(dict(variables))
    goal = str(context.get("goal", ""))
    depth = int(context.get("current_depth", 0))

    within_limit = depth < int(updated["max_depth"])
    subtask_count = int(updated["max_subtasks"]) if within_limit else 0

    return {
        "ok": True,
        "identity": updated["identity"],
        "goal": goal,
        "current_depth": depth,
        "within_limit": within_limit,
        "allocated_subtasks": subtask_count,
        "variables": dict(updated),
    }


def sub_main_check_depth(context, variables):
    """
    Submain step 1: Validate hierarchy depth.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_build_dag(context, variables):
    """
    Submain step 2: Construct subtask graph.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
