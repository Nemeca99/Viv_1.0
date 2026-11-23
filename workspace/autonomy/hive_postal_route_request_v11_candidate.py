prepare_routing_request(proposed_recipient_id):
    if proposed_recipient_id is None:
        return (None, ())
    
    try:
        recipient = str(proposed_recipient_id).strip()
    except Exception:
        return (None, ("invalid_proposed_recipient_id",))
    
    if not recipient:
        return (None, ("invalid_proposed_recipient_id",))
    
    if recipient.casefold() == "queen":
        return (None, ("proposed_recipient_is_queen",))
    
    return ({"recipient_id": recipient}, ())

def main():
    import sys
    
    checks = [
        None,
        "drone_2",
        "",
        "QUEEN"
    ]
    
    results = []
    for i, check in enumerate(checks):
        request, errors = prepare_routing_request(check)
        if request is not None:
            status = f"PASS: Check {i+1} ({check!r}) -> recipient_id={request['recipient_id']}"
        else:
            status = f"FAIL: Check {i+1} ({check!r}) -> errors={errors}"
        results.append(status)
    
    print("\n".join(results))
    if all(r.startswith("PASS") for r in results):
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()