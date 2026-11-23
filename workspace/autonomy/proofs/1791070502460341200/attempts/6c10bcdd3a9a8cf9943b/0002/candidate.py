def solve(value):
    passed = 0
    failed = 0
    unknown = 0
    for receipt in value:
        if 'passed' in receipt:
            if isinstance(receipt['passed'], bool):
                if receipt['passed']:
                    passed += 1
                else:
                    failed += 1
            else:
                unknown += 1
        else:
            unknown += 1
    return {'passed': passed, 'failed': failed, 'unknown': unknown}