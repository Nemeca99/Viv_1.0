"""Route the documented python -m nn_local launcher to the existing CLI."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
