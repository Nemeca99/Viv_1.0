import sqlite3
from drone_fact_admission_v1 import admit_fact


class PositiveStore:
    def __init__(self, conn, authorize_write, verify_receipt):
        self.conn = conn
        self.authorize_write = authorize_write
        self.verify_receipt = verify_receipt
        try:
            allowed = authorize_write()
        except Exception as error:
            raise PermissionError('schema authorization failed') from error
        if allowed is not True:
            raise PermissionError('schema write denied')
        with conn:
            conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS positive_facts USING fts5(text, provenance UNINDEXED, receipt_hash UNINDEXED)')

    def add_fact(self, text, source_sha256, receipt):
        result = admit_fact(text, source_sha256, receipt, self.authorize_write, self.verify_receipt)
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO positive_facts (text, provenance, receipt_hash) VALUES (?, ?, ?)",
                result
            )
            return cursor.rowcount

    def search(self, query, limit=5):
        if not isinstance(limit, int) or limit < 1:
            limit = 1
        elif limit > 20:
            limit = 20
        with self.conn:
            rows = self.conn.execute(
                "SELECT text, provenance, receipt_hash FROM positive_facts WHERE positive_facts MATCH ? LIMIT ?",
                (query, limit)
            ).fetchall()
            return [row for row in rows]
