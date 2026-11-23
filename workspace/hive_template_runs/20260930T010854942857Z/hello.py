"Hive greeting module"

from typing import Final

GREETING: Final[str] = "Hello from the Hive!"


def greet() -> str:
    return GREETING
