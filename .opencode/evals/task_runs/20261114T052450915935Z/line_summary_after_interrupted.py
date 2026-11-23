def summarize_lines(text):
    """Return nonblank line count and distinct stripped nonblank lines in input order."""
    seen = set()
    unique = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return {"count": len(unique), "unique": unique}
