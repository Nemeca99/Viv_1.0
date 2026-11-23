"""Add-only Python smoke probe for the LocalCoder Drone."""


def normalize_workspace_name(value: str) -> str:
    """Lowercase and join whitespace or underscore separated words with hyphens."""
    return "-".join(value.strip().lower().replace("_", " ").split())


def _verify() -> None:
    assert normalize_workspace_name("  AIOS   Queen  ") == "aios-queen"
    assert normalize_workspace_name("Drone__Worker") == "drone-worker"
    assert normalize_workspace_name("") == ""
    assert normalize_workspace_name("Hive\tVoice\nDaemon") == "hive-voice-daemon"


if __name__ == "__main__":
    _verify()
    print("PASS: normalize_workspace_name handles whitespace, underscores, and empty input")