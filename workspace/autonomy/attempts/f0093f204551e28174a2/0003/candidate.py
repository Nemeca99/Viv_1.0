def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    sort = options.get("sort", "timestamp")
    
    filtered = []
    for item in data:
        if query in item.get("reason", ""):
            filtered.append(item)
    
    if sort == "timestamp":
        filtered.sort(key=lambda x: x.get("timestamp", ""))
    elif sort == "id":
        filtered.sort(key=lambda x: x.get("id", ""))
    
    results = []
    for item in filtered:
        results.append({
            "id": item.get("id", ""),
            "reason": item.get("reason", ""),
            "timestamp": item.get("timestamp", ""),
            "status": "failed"
        })
    
    return {"results": results}