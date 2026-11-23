def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    
    # Apply severity filter
    if options.get("severity_filter"):
        filtered_data = [item for item in data if item.get("severity") == options.get("severity_filter")]
    else:
        filtered_data = data
    
    # Apply dependency filter
    if options.get("dependency_filter"):
        filtered_data = [item for item in filtered_data if item.get("reason") == "Missing dependency"]
    
    # Sort based on sort_by
    if options.get("sort_by") == "reason":
        filtered_data.sort(key=lambda x: x.get("reason", ""))
    elif options.get("sort_by") == "severity":
        severity_order = {"high": 0, "medium": 1, "low": 2}
        filtered_data.sort(key=lambda x: severity_order.get(x.get("severity", "low")))
    elif options.get("sort_by") == "timestamp":
        filtered_data.sort(key=lambda x: x.get("timestamp", ""))
    
    # Apply order
    if options.get("order") == "desc":
        filtered_data.reverse()
    
    return {"results": filtered_data}