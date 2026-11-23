def validate_postal_message(message):
    """Validate a postal message according to the schema."""
    
    # Required keys
    REQUIRED_KEYS = ['schema', 'message_id', 'sender_id', 'recipient_id', 
                    'task_id', 'kind', 'body']
    
    # Allowed keys (including optional parent_message_sha256)
    ALLOWED_KEYS = REQUIRED_KEYS + ['parent_message_sha256']
    
    # Valid kind values
    VALID_KINDS = {'REPORT', 'SELF_PROMPT', 'ROUTED_REPORT', 'ACK', 'STOP'}
    
    # Schema constant
    VALID_SCHEMA = 'hive_postal_message_v1'
    
    # Error codes
    ERROR_MISSING_KEY = 'MISSING_KEY'
    ERROR_UNKNOWN_KEY = 'UNKNOWN_KEY'
    ERROR_INVALID_SCHEMA = 'INVALID_SCHEMA'
    ERROR_EMPTY_STRING = 'EMPTY_STRING'
    ERROR_INVALID_KIND = 'INVALID_KIND'
    ERROR_NON_DICT_BODY = 'NON_DICT_BODY'
    ERROR_MALFORMED_HASH = 'MALFORMED_HASH'
    
    # Check if input is a dict
    if not isinstance(message, dict):
        return (False, ERROR_NON_DICT_BODY)
    
    # Check for unknown keys
    for key in message.keys():
        if key not in ALLOWED_KEYS:
            return (False, ERROR_UNKNOWN_KEY)
    
    # Check required keys are present
    for req_key in REQUIRED_KEYS:
        if req_key not in message:
            return (False, ERROR_MISSING_KEY)
    
    # Validate schema
    if message['schema'] != VALID_SCHEMA:
        return (False, ERROR_INVALID_SCHEMA)
    
    # Validate string fields (nonempty trimmed strings)
    for field in ['message_id', 'sender_id', 'recipient_id', 'task_id']:
        value = message[field]
        if not isinstance(value, str):
            return (False, ERROR_NON_DICT_BODY)  # String validation falls under body check
        if value.strip() == '':
            return (False, ERROR_EMPTY_STRING)
    
    # Validate kind field
    kind_value = message['kind']
    if not isinstance(kind_value, str):
        return (False, ERROR_NON_DICT_BODY)
    if kind_value.strip() == '':
        return (False, ERROR_EMPTY_STRING)
    if kind_value.strip().upper() not in VALID_KINDS:
        return (False, ERROR_INVALID_KIND)
    
    # Validate body is a dict
    if not isinstance(message['body'], dict):
        return (False, ERROR_NON_DICT_BODY)
    
    # Validate parent_message_sha256 if present
    if 'parent_message_sha256' in message:
        parent_hash = message['parent_message_sha256']
        if not isinstance(parent_hash, str):
            return (False, ERROR_MALFORMED_HASH)
        if len(parent_hash) != 64:
            return (False, ERROR_MALFORMED_HASH)
        # Check for valid lowercase hexadecimal characters only
        try:
            int(parent_hash, 16)
        except ValueError:
            return (False, ERROR_MALFORMED_HASH)
    
    return (True, 'accepted')


def main():
    """Self-check entry point with nine test cases."""
    
    import sys
    
    # Test case 1: valid REPORT accepted
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': {'status': 'complete'}
        })
        assert result == (True, 'accepted'), f"Test 1 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 1 - valid REPORT accepted")
        sys.exit(1)
    
    # Test case 2: non-dict rejected
    try:
        result = validate_postal_message("not a dict")
        assert result == (False, ERROR_NON_DICT_BODY), f"Test 2 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 2 - non-dict rejected")
        sys.exit(1)
    
    # Test case 3: missing task_id rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            # task_id missing
            'kind': 'REPORT',
            'body': {'status': 'complete'}
        })
        assert result == (False, ERROR_MISSING_KEY), f"Test 3 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 3 - missing task_id rejected")
        sys.exit(1)
    
    # Test case 4: blank sender_id rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': '',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': {'status': 'complete'}
        })
        assert result == (False, ERROR_EMPTY_STRING), f"Test 4 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 4 - blank sender_id rejected")
        sys.exit(1)
    
    # Test case 5: unsupported kind rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'UNKNOWN_KIND',
            'body': {'status': 'complete'}
        })
        assert result == (False, ERROR_INVALID_KIND), f"Test 5 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 5 - unsupported kind rejected")
        sys.exit(1)
    
    # Test case 6: non-dict body rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': "not a dict"
        })
        assert result == (False, ERROR_NON_DICT_BODY), f"Test 6 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 6 - non-dict body rejected")
        sys.exit(1)
    
    # Test case 7: unknown key rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': {'status': 'complete'},
            'unknown_field': 'value'
        })
        assert result == (False, ERROR_UNKNOWN_KEY), f"Test 7 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 7 - unknown key rejected")
        sys.exit(1)
    
    # Test case 8: malformed parent hash rejected
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': {'status': 'complete'},
            'parent_message_sha256': 'invalid-hash'
        })
        assert result == (False, ERROR_MALFORMED_HASH), f"Test 8 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 8 - malformed parent hash rejected")
        sys.exit(1)
    
    # Test case 9: valid lowercase 64-character parent hash accepted
    try:
        result = validate_postal_message({
            'schema': 'hive_postal_message_v1',
            'message_id': 'msg_001',
            'sender_id': 'user_alice',
            'recipient_id': 'user_bob',
            'task_id': 'task_42',
            'kind': 'REPORT',
            'body': {'status': 'complete'},
            'parent_message_sha256': 'a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef12'
        })
        assert result == (True, 'accepted'), f"Test 9 failed: {result}"
    except AssertionError as e:
        print(f"FAIL: Test 9 - valid lowercase 64-character parent hash accepted")
        sys.exit(1)
    
    # All tests passed
    print("PASS: postal envelope checks")
    return 0


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Postal message validation')
    parser.add_argument('--self-check', action='store_true', help='Run self-check tests')
    
    args = parser.parse_args()
    
    if args.self_check:
        sys.exit(main())
    else:
        print("Usage: python hive_postal_message_contract_candidate.py --self-check")
        sys.exit(1)
