def solve(value):
    results = []
    query = value.get("options", {}).get("query", "")
    for item in value.get("data", []):
        if query in item.get("reason", ""):
            results.append(item)
    if value.get("options", {}).get("sort") == "timestamp":
        results.sort(key=lambda x: x.get("timestamp", ""))
    limit = value.get("options", {}).get("limit", 0)
    if limit > 0:
        results = results[:limit]
    return {"results": results}