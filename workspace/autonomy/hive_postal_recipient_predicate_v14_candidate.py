def is_valid_drone_recipient(value):
    if not isinstance(value, str) or value.strip() != value:
        return False
    return value.casefold() != "queen"
