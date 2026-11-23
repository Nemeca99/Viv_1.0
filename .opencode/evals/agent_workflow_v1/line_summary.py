def summarize_lines(text):
    """Return nonblank line count and distinct stripped nonblank lines in input order."""
    lines = [line.strip() for line in text.splitlines()]
    nonblank = [line for line in lines if line]
    unique = []
    seen = set()
    for line in nonblank:
        if line not in seen:
            unique.append(line)
            seen.add(line)
    return {"count": len(nonblank), "unique": unique}
