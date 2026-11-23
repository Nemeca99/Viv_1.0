"""Official CLI entrypoint proof for opt-in grounded RNN mode."""

import json
import subprocess


CLI = r"L:\LocalCoder\workspace\autonomy\viv.py"
PYTHON = r"L:\.venv\Scripts\python.exe"


def test_official_cli_grounded_rnn_mode_outputs_receipt() -> None:
    result = subprocess.run(
        [PYTHON, CLI, "--grounded-rnn", "Who is my fiancee named?"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    assert "Kat" in lines[0]
    receipt = json.loads(lines[1])
    assert receipt["schema"] == "viv-grounded-rnn-answer-receipt-v1"
