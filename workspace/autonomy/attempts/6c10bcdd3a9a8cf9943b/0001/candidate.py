def solve(value):
    passed = 0
    failed = 0
    unknown = 0
    for receipt in value:
        field = receipt.get('passed')
        if field is None:
            unknown += 1
        elif isinstance(field, bool):
            if field:
                passed += 1
            else:
                failed += 1
        else:
            unknown += 1
    return {'passed': passed, 'failed': failed, 'unknown': unknown}