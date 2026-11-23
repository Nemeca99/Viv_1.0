def solve(value):
    from collections import defaultdict

    data = value.get("input", {}).get("data", [])
    options = value.get("input", {}).get("options", {})

    query = options.get("query", "")
    sort = options.get("sort", "task")
    limit = options.get("limit", 10)

    # Filter based on query
    if query:
        data = [item for item in data if query in item.get("task", "")]

    # Sort based on the sort key
    if sort == "task":
        data.sort(key=lambda x: x.get("task", ""))
    elif sort == "status":
        data.sort(key=lambda x: x.get("status", ""))
    elif sort == "dependencies":
        data.sort(key=lambda x: len(x.get("dependencies", [])))

    # Apply limit
    data = data[:limit]

    return {"results": data}