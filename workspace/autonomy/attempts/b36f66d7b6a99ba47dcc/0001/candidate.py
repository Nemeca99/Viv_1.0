def solve(query):
    failures = [
        {"message": "Incorrect count of passed, failed, unknown in build receipts", "timestamp": "2023-04-05T14:30:00Z"},
        {"message": "Mismatch in expected vs actual counts for build receipts", "timestamp": "2023-04-05T15:15:00Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Error in Viv telemetry validation", "timestamp": "2023-10-02T08:15:22Z"},
        {"message": "Error in Viv telemetry validation", "timestamp": "2023-10-02T08:15:22Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"}
    ]
    results = []
    for failure in failures:
        match = True
        if "AND" in query:
            terms = query.split(" AND ")
            for term in terms:
                if term not in failure["message"] and term not in failure["timestamp"]:
                    match = False
                    break
        elif "OR" in query:
            terms = query.split(" OR ")
            match = False
            for term in terms:
                if term in failure["message"] or term in failure["timestamp"]:
                    match = True
                    break
        else:
            if query not in failure["message"] and query not in failure["timestamp"]:
                match = False
        if match:
            results.append(failure)
    return results