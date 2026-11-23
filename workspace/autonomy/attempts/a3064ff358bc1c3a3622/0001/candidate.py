def solve(value):
    import json
    from collections import defaultdict

    def parse_data(data):
        parsed = []
        for item in data:
            parsed_item = {
                "reason": item.get("reason", ""),
                "severity": item.get("severity", ""),
                "dependencies": item.get("dependencies", []),
                "timestamp": item.get("timestamp", "")
            }
            parsed.append(parsed_item)
        return parsed

    def filter_by_reason(parsed_data, reason_contains):
        filtered = []
        for item in parsed_data:
            if reason_contains in item["reason"]:
                filtered.append(item)
        return filtered

    def sort_by_severity(parsed_data, order):
        severity_order = {"high": 0, "medium": 1, "low": 2}
        sorted_data = sorted(parsed_data, key=lambda x: severity_order[x["severity"]])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_reason(parsed_data, order):
        sorted_data = sorted(parsed_data, key=lambda x: x["reason"])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_timestamp(parsed_data, order):
        sorted_data = sorted(parsed_data, key=lambda x: x["timestamp"])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_dependency(parsed_data, order):
        sorted_data = sorted(parsed_data, key=lambda x: x["dependencies"])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_status(parsed_data, order):
        sorted_data = sorted(parsed_data, key=lambda x: x["status"])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_task(parsed_data, order):
        sorted_data = sorted(parsed_data, key=lambda x: x["task"])
        if order == "descending":
            sorted_data = sorted_data[::-1]
        return sorted_data

    def sort_by_key(parsed_data, key, order):
        if key == "severity":
            return sort_by_severity(parsed_data, order)
        elif key == "reason":
            return sort_by_reason(parsed_data, order)
        elif key == "timestamp":
            return sort_by_timestamp(parsed_data, order)
        elif key == "dependency":
            return sort_by_dependency(parsed_data, order)
        elif key == "status":
            return sort_by_status(parsed_data, order)
        elif key == "task":
            return sort_by_task(parsed_data, order)
        else:
            return parsed_data

    def filter_by_dependency(parsed_data, dependency_filter):
        filtered = []
        for item in parsed_data:
            if dependency_filter and item["dependencies"]:
                filtered.append(item)
            elif not dependency_filter and not item["dependencies"]:
                filtered.append(item)
        return filtered

    def filter_by_status(parsed_data, status_filter):
        filtered = []
        for item in parsed_data:
            if status_filter in item["status"]:
                filtered.append(item)
        return filtered

    def filter_by_query(parsed_data, query):
        filtered = []
        for item in parsed_data:
            if query in item["reason"]:
                filtered.append(item)
        return filtered

    def filter_by_key(parsed_data, key, value):
        filtered = []
        for item in parsed_data:
            if key in item and value in item[key]:
                filtered.append(item)
        return filtered

    def filter_by_all(parsed_data, filters):
        filtered = parsed_data
        for key, value in filters.items():
            filtered = filter_by_key(filtered, key, value)
        return filtered

    def solve(value):
        data = value.get("data", [])
        options = value.get("options", {})
        parsed_data = parse_data(data)
        filtered = parsed_data
        if options.get("filter_by") == "reason":
            filtered = filter_by_reason(parsed_data, options.get("reason_contains", ""))
        elif options.get("filter_by") == "dependency":
            filtered = filter_by_dependency(parsed_data, options.get("dependency_filter", False))
        elif options.get("filter_by") == "status":
            filtered = filter_by_status(parsed_data, options.get("status_filter", ""))
        elif options.get("filter_by") == "query":
            filtered = filter_by_query(parsed_data, options.get("query", ""))
        elif options.get("filter_by") == "all":
            filters = options.get("filters", {})
            filtered = filter_by_all(parsed_data, filters)
        sorted_data = sorted(filtered, key=lambda x: x["reason"])
        if options.get("order") == "descending":
            sorted_data = sorted_data[::-1]
        return {"results": sorted_data}

    return solve(value)