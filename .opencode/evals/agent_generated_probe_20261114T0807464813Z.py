"""Normalize workspace names by trimming whitespace, lowercasing, and joining runs of separators with hyphens."""

import re


def normalize_workspace_name(value: str) -> str:
    """
    Normalize a workspace name string.

    - Trims leading/trailing whitespace.
    - Lowercases the text.
    - Treats any run of whitespace or underscores as a single separator.
    - Joins resulting words with one hyphen.
    - Preserves all other characters (letters, digits, punctuation).

    Examples:
        "  AIOS   Queen  " -> "aios-queen"
        "Drone__Worker" -> "drone-worker"
        "" -> ""
        "Hive\tVoice\nDaemon" -> "hive-voice-daemon"
    """
    # Trim and lowercase
    value = value.strip().lower()

    if not value:
        return ""

    # Replace any run of whitespace or underscores with a single hyphen, then collapse multiple hyphens into one.
    normalized = re.sub(r"[ \t\n\r_]+", "-", value)
    normalized = re.sub(r"-+", "-", normalized)

    return normalized


def _verify():
    """Run assertions for the specified test cases."""
    assert normalize_workspace_name("  AIOS   Queen  ") == "aios-queen"
    assert normalize_workspace_name("Drone__Worker") == "drone-worker"
    assert normalize_workspace_name("") == ""
    assert normalize_workspace_name("Hive\tVoice\nDaemon") == "hive-voice-daemon"


if __name__ == "__main__":
    _verify()
    print("PASS: normalize_workspace_name handles whitespace, underscores, and empty input.")
