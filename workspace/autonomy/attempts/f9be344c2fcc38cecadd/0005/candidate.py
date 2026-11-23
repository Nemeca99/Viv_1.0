def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    sort = options.get("sort", "reason")
    
    filtered = []
    for item in data:
        if query:
            reason = item.get("reason", "")
            if not reason or query.lower() not in reason.lower():
                continue
        filtered.append(item)
    
    if sort == "reason":
        filtered.sort(key=lambda x: x.get("reason", "").lower())
    elif sort == "id":
        filtered.sort(key=lambda x: x.get("id", ""))
    
    return {"results": filtered}