def admit_fact(text, source_sha256, receipt, authorize_write, verify_receipt):
    if not isinstance(text, str) or text.strip() == "":
        raise ValueError("text must be nonblank str")
    if not isinstance(source_sha256, str) or len(source_sha256) != 64 or not all(c in '0123456789abcdef' for c in source_sha256.lower()):
        raise ValueError("source_sha256 must be exactly 64 hex characters")
    if not isinstance(receipt, str):
        raise ValueError("receipt must be str")
    try:
        verified = verify_receipt(receipt)
    except Exception as error:
        raise PermissionError("receipt verifier failed") from error
    if verified is not True:
        raise PermissionError("receipt denied")
    try:
        authorized = authorize_write()
    except Exception as error:
        raise PermissionError("write authorizer failed") from error
    if authorized is not True:
        raise PermissionError("write denied")
    import hashlib
    receipt_hash = hashlib.sha256(receipt.encode('utf-8')).hexdigest().lower()
    return text.strip(), source_sha256.lower(), receipt_hash
