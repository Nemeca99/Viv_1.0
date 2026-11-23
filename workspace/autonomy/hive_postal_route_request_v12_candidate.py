def prepare_routing_request(proposed_recipient_id):
    if proposed_recipient_id is None:
        return (None,("invalid_proposed_recipient_id",))
    s = str(proposed_recipient_id).strip()
    if not s:
        return (None,("invalid_proposed_recipient_id",))
    if s.casefold()=="queen":
        return (None,("proposed_recipient_is_queen",))
    try:
        int(s)
        return (None,("invalid_proposed_recipient_id",))
    except ValueError:
        pass
    return ({"recipient_id":s},())
