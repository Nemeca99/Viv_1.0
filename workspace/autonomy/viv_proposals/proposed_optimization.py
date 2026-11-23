import sqlite3
from functools import lru_cache

@lru_cache(maxsize=65536)
def lookup(word: str) -> tuple:
    """Lookup a word in the database."""
    w = word.lower()
    return (sqlite3.connect(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3").execute(f"SELECT token_id, spelling, observations FROM word_index WHERE word = ?", (w,)).fetchone())

class UltraFastMemoryCache:
    """Viv's In-Memory RAM Cache:"""
    def __init__(self):
        self.conn = sqlite3.connect(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
        self.cur = self.conn.cursor()
    
    @lru_cache(maxsize=65536)
    def lookup(self, word: str) -> tuple:
        """Lookup a word in the database."""
        return lookup(word)