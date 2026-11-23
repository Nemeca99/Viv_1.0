def solve(query):
    failures = [
        {
            "message": "Incorrect count of passed, failed, unknown in build receipts",
            "timestamp": "2023-04-05T14:30:00Z"
        },
        {
            "message": "Mismatch in expected vs actual counts for build receipts",
            "timestamp": "2023-04-05T15:15:00Z"
        },
        {
            "message": "Unexpected value in passed field of receipt object",
            "timestamp": "2023-04-05T16:00:00Z"
        },
        {
            "message": "Incorrect handling of absent passed field in receipt object",
            "timestamp": "2023-04-05T16:45:00Z"
        },
        {
            "message": "Incorrect classification of non-boolean values in passed field",
            "timestamp": "2023-04-05T17:30:00Z"
        }
    ]
    return [failure for failure in failures if query in failure["message"]]