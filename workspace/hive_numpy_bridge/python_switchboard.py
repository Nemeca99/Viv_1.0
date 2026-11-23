"""Transport requests between Rust and the NumPy numerical backend."""

from __future__ import annotations

import sys

import numpy as np

from numpy_backend import create_training_state, train_steps


def emit(line: str) -> None:
    print(line, flush=True)


def main() -> int:
    start = sys.stdin.readline().strip().split("\t")
    if len(start) != 4 or start[0] != "START":
        emit("ERROR\tEXPECTED_START")
        return 2

    try:
        samples = int(start[1])
        first_steps = int(start[2])
        first_lr = float(start[3])
        seed = int(np.random.SeedSequence().entropy)
        state = create_training_state(seed, samples=samples)
        first_loss, first_gradient = train_steps(state, first_steps, first_lr)
    except Exception as exc:  # protocol boundary: report, do not hide
        emit(f"ERROR\tSTART_FAILED\t{type(exc).__name__}")
        return 2

    emit(
        "\t".join(
            (
                "FORWARD",
                str(seed),
                str(state.x.shape[0]),
                str(state.x.shape[1]),
                str(state.x.dtype),
                f"{state.initial_loss:.17g}",
                f"{first_loss:.17g}",
                f"{first_gradient:.17g}",
                np.__version__,
                state.bit_generator,
                state.rng_state_b64,
            )
        )
    )

    feedback = sys.stdin.readline().strip().split("\t")
    if len(feedback) != 3 or feedback[0] != "FEEDBACK":
        emit("ERROR\tEXPECTED_FEEDBACK")
        return 2

    try:
        second_steps = int(feedback[1])
        second_lr = float(feedback[2])
        final_loss, final_gradient = train_steps(state, second_steps, second_lr)
    except Exception as exc:
        emit(f"ERROR\tCONTINUE_FAILED\t{type(exc).__name__}")
        return 2

    emit(
        "\t".join(
            (
                "BACKPROP",
                str(seed),
                f"{first_loss:.17g}",
                f"{final_loss:.17g}",
                f"{final_gradient:.17g}",
                str(state.x.shape[0]),
                str(state.x.shape[1]),
                str(state.y.shape[0]),
                str(state.y.shape[1]),
                str(state.x.dtype),
            )
        )
    )

    decision = sys.stdin.readline().strip()
    if decision not in {"ACCEPT", "HOLD"}:
        emit("ERROR\tEXPECTED_FINAL_DECISION")
        return 2
    emit(f"CLOSED\t{decision}")
    return 0 if decision == "ACCEPT" else 3


if __name__ == "__main__":
    raise SystemExit(main())
