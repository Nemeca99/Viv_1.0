def solve(query):
    failures = [
        {
            "actual": [
                {"message": "Incorrect count of passed, failed, unknown in build receipts", "timestamp": "2023-04-05T14:30:00Z"},
                {"message": "Mismatch in expected vs actual counts for build receipts", "timestamp": "2023-04-05T15:15:00Z"}
            ],
            "expected": [{"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"}],
            "input": "build",
            "passed": False
        },
        {
            "actual": [],
            "expected": [],
            "input": "telemetry",
            "passed": True
        },
        {
            "actual": [],
            "expected": [{"message": "Error in Viv telemetry validation", "timestamp": "2023-10-02T08:15:22Z"}],
            "input": "error",
            "passed": False
        },
        {
            "actual": [],
            "expected": [{"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"}],
            "input": "2023-10-01",
            "passed": False
        },
        {
            "actual": [],
            "expected": [],
            "input": "2023-10-03",
            "passed": True
        },
        {
            "actual": [],
            "expected": [{"message": "Failed to build Viv core module", "timestamp": "2023-10-01T12:34:56Z"}],
            "input": "core",
            "passed": False
        }
    ]
    result = []
    for failure in failures:
        if not failure["passed"]:
            for entry in failure["actual"]:
                if query in entry["message"] or query in entry["timestamp"]:
                    result.append(entry)
            for entry in failure["expected"]:
                if query in entry["message"] or query in entry["timestamp"]:
                    result.append(entry)
    return result