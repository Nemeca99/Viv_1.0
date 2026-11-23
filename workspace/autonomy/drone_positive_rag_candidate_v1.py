import sqlite3
import hashlib
import re


class PositiveRAG:
    def __init__(self, conn):
        self.conn = conn

    def authorize_schema(self):
        cursor = self.conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS positive_facts (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, provenance TEXT NOT NULL, receipt_hash TEXT NOT NULL)")
        cursor.execute("CREATE VIRTUAL TABLE IF NOT EXISTS positive_facts_fts USING fts5(text, content='positive_facts', rowid)")
        self.conn.commit()

    def add_fact(self, text, source_sha256, receipt):
        if not text or not isinstance(text, str):
            return False
        if len(source_sha256) != 64 or not re.match(r'^[0-9a-f]{64}$', source_sha256):
            return False
        if not receipt:
            return False
        try:
            self.authorize_schema()
            text_hash = hashlib.sha256(text.encode()).hexdigest()[:8]
            receipt_hash = hashlib.sha256(receipt.encode()).hexdigest()
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO positive_facts (text, provenance, receipt_hash) VALUES (?, ?, ?)", (text, source_sha256, receipt_hash))
            self.conn.commit()
        except Exception:
            return False
        return True

    def search(self, query, limit=5):
        cursor = self.conn.cursor()
        cursor.execute("SELECT text FROM positive_facts_fts MATCH ? ORDER BY rank LIMIT ?", (query, min(limit, 20)))
        results = [row[0] for row in cursor.fetchall()]
        return results

    def self_check(self):
        conn = sqlite3.connect(':memory:')
        rag = PositiveRAG(conn)
        rag.authorize_schema()
        rag.add_fact("test fact", "a" * 64, "receipt123")
        retrieved = rag.search("test fact", limit=5)
        if len(retrieved) != 1 or retrieved[0] != "test fact":
            return False
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM positive_facts_fts WHERE 'test fact' MATCH ? LIMIT ?", ("test fact", 1))
        count_before = cursor.fetchone()[0]
        rag.add_fact("denied receipt", "b" * 64, "badreceipt")
        retrieved2 = rag.search("test fact", limit=5)
        if len(retrieved2) != 1:
            return False
        conn.close()
        return True
