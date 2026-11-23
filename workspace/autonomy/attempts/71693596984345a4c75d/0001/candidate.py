def solve(value):
    data = value.get("data", [])
    options = value.get("options", {})
    
    # Filter based on severity if provided
    if options.get("severity_filter"):
        filtered_data = [item for item in data if item.get("severity") == options.get("severity_filter")]
    else:
        filtered_data = data
    
    # Filter based on dependency_filter if provided
    if options.get("dependency_filter"):
        filtered_data = [item for item in filtered_data if item.get("reason") == "Missing dependency"]
    
    # Sort by reason if specified
    if options.get("sort_by") == "reason":
        filtered_data.sort(key=lambda x: x.get("reason", ""))
    elif options.get("sort_by") == "severity":
        # Sort by severity with priority: high, medium, low
        severity_order = {"high": 0, "medium": 1, "low": 2}
        filtered_data.sort(key=lambda x: severity_order.get(x.get("severity", "low")))
    elif options.get("sort_by") == "timestamp":
        filtered_data.sort(key=lambda x: x.get("timestamp", ""))
    
    # Order based on the order parameter
    if options.get("order") == "desc":
        filtered_data.reverse()
    
    return {"results": filtered_data}
