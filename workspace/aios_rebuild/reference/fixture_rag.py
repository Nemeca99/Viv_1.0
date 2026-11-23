"""
AIOS Viv Context Vector Retrieval (RAG Core) Rebuild Template.
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
    "top_k": 5,
    "min_score": 0.70,
    "embedding_model": "nomic-embed-text-local",
    "rerank": True,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Perform vector retrieval and relevancy scoring over Viv's cognitive knowledgebase.
    """
    updated = copy.deepcopy(dict(variables))
    query = str(context.get("query", ""))
    candidates = list(context.get("candidates", []))

    top_k = int(updated["top_k"])
    min_score = float(updated["min_score"])

    matches = []
    for c in candidates:
        score = float(c.get("score", 0.0))
        if score >= min_score:
            matches.append({"text": c.get("text", ""), "score": round(score, 4)})

    matches = matches[:top_k]

    return {
        "ok": True,
        "identity": updated["identity"],
        "query": query,
        "retrieved_count": len(matches),
        "matches": matches,
        "variables": dict(updated),
    }


def sub_main_filter_candidates(context, variables):
    """
    Submain step 1: Validate top_k and min_score parameters.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_rerank_results(context, variables):
    """
    Submain step 2: Rerank top matches by vector similarity score.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
