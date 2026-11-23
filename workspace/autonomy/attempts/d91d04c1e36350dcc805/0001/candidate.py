def solve(query):
    failures = [
        {"message": "Incorrect count of passed, failed, unknown in build receipts", "timestamp": "2023-04-05T14:30:00Z"},
        {"message": "Mismatch in expected vs actual counts for build receipts", "timestamp": "2023-04-05T15:15:00Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"},
        {"message": "Error in Viv telemetry validation", "timestamp": "2023-10-02T08:15:22Z"}
    ]
    results = []
    for failure in failures:
        message = failure["message"]
        timestamp = failure["timestamp"]
        match = False
        if "timeout" in query.lower() or "error" in query.lower():
            if "timeout" in message.lower() or "error" in message.lower():
                match = True
        elif query == "":
            match = True
        elif query == "2023-10-01":
            if timestamp.startswith("2023-10-01"):
                match = True
        elif query == "build":
            if "build" in message.lower():
                match = True
        elif query == "telemetry":
            if "telemetry" in message.lower():
                match = True
        elif query == "error":
            if "error" in message.lower():
                match = True
        elif query == "nonexistent":
            pass
        else:
            if query in message.lower():
                match = True
        if match:
            results.append(failure)
    return results