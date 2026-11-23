def solve(value):
    results = []
    for item in value.get("data", []):
        if value.get("options", {}).get("query") in item.get("reason", ""):
            results.append(item)
    if value.get("options", {}).get("sort") == "timestamp":
        results.sort(key=lambda x: x.get("timestamp", ""))
    if value.get("options", {}).get("limit"):
        results = results[:value.get("options", {}).get("limit")]
    return {"results": results}