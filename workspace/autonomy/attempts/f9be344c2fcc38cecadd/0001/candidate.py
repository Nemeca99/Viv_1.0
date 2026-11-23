def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    query = options.get("query", "")
    sort = options.get("sort", "reason")
    
    filtered = []
    for item in data:
        if query and query.lower() not in item["reason"].lower():
            continue
        filtered.append(item)
    
    if sort == "reason":
        filtered.sort(key=lambda x: x["reason"])
    elif sort == "id":
        filtered.sort(key=lambda x: x["id"])
    
    return {"results": filtered}