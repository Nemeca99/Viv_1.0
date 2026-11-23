import sqlite3

class VivLexicalCortex:
    def __init__(self, db_path: str = "L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.ram_cache = {}

    def lookup(self, word: str) -> tuple | None:
        """Look up a word in RAM first, then SQLite B-Tree. Fail closed if not found."""
        w = word.lower()
        if w in self.ram_cache:
            return self.ram_cache[w]

        self.cur.execute("SELECT token_id, spelling, observations FROM word_index WHERE word = ?", (w,))
        row = self.cur.fetchone()
        if row:
            self.ram_cache[w] = row
            return row
        return None


cortex = VivLexicalCortex()
res = cortex.lookup('the')
assert res is not None, "Failed to find 'the'!"
token_id, spelling, observations = res
assert token_id == 6613, f"Expected 6613, got {token_id}"
assert spelling == "T-H-E", f"Expected T-H-E, got {spelling}"

# Test RAM cache
assert cortex.lookup('the') == res, "Cache hit mismatch"

# Test Fail-Closed
assert cortex.lookup('xyznonexistentword99') is None, "Did not fail closed!"

print("[RED-TEAM VICTORY] All 5/5 assertions passed with 100% precision!")
