def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    
    # Apply severity filter
    severity_filter = options.get("severity_filter")
    if severity_filter:
        filtered_data = [item for item in data if item.get("severity") == severity_filter]
    else:
        filtered_data = data
    
    # Apply dependency filter
    dependency_filter = options.get("dependency_filter")
    if dependency_filter:
        filtered_data = [item for item in filtered_data if item.get("reason") == "Missing dependency"]
    
    # Sort based on sort_by
    sort_by = options.get("sort_by", "reason")
    if sort_by == "reason":
        filtered_data.sort(key=lambda x: x.get("reason", ""))
    elif sort_by == "severity":
        severity_order = {"high": 0, "medium": 1, "low": 2}
        filtered_data.sort(key=lambda x: severity_order.get(x.get("severity", "low")))
    elif sort_by == "timestamp":
        filtered_data.sort(key=lambda x: x.get("timestamp", ""))
    
    # Apply order
    order = options.get("order", "asc")
    if order == "desc":
        filtered_data.reverse()
    
    return {"results": filtered_data}