def solve(value):
    results = []
    if not value or not value.get("data") or not value.get("options"):
        return {"results": results}
    data = value["data"]
    options = value["options"]
    sort_by = options.get("sort_by", "reason")
    order = options.get("order", "asc")
    filtered_data = data
    if sort_by == "reason":
        filtered_data.sort(key=lambda x: x["reason"])
    elif sort_by == "status":
        filtered_data.sort(key=lambda x: x["status"])
    elif sort_by == "title":
        filtered_data.sort(key=lambda x: x["title"])
    if order == "desc":
        filtered_data.reverse()
    results = filtered_data
    return {"results": results}