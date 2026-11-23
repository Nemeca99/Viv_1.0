def lookup(self, word: str):
        w = word.lower()
        if w in self.ram_cache:
            return self.ram_cache[w]
        
        # Fallback to SQLite B-Tree
        self.cur.execute("SELECT token_id, spelling, observations FROM word_index WHERE word = ?", ("?" * len(w)))
        row = self.cur.fetchone()