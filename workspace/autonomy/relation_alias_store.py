"""Domain-scoped relation aliases and argument signatures for frame evaluation."""

from __future__ import annotations

import sqlite3
import unicodedata


RELATION_ALIAS_SCHEMA = """
CREATE TABLE relation_alias (
    domain_id TEXT NOT NULL CHECK (length(trim(domain_id)) > 0),
    alias_norm TEXT NOT NULL CHECK (length(trim(alias_norm)) > 0),
    canonical_relation_id TEXT NOT NULL CHECK (length(trim(canonical_relation_id)) > 0),
    PRIMARY KEY (domain_id, alias_norm)
) WITHOUT ROWID;
"""

RELATION_SIGNATURE_SCHEMA = """
CREATE TABLE relation_signature (
    canonical_relation_id TEXT NOT NULL,
    argument_name TEXT NOT NULL CHECK (argument_name IN ('object')),
    expected_type TEXT NOT NULL CHECK (expected_type IN ('entity', 'value', 'property', 'quality')),
    PRIMARY KEY (canonical_relation_id, argument_name)
) WITHOUT ROWID;
"""


def normalize_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


class RelationAliasStore:
    """SQLite-backed alias contract. Defaults to ephemeral storage for evaluation."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.executescript(RELATION_ALIAS_SCHEMA + RELATION_SIGNATURE_SCHEMA)

    def add_alias(self, domain_id: str, alias: str, canonical_relation_id: str) -> None:
        self.connection.execute(
            "INSERT INTO relation_alias(domain_id, alias_norm, canonical_relation_id) VALUES (?, ?, ?)",
            (normalize_alias(domain_id), normalize_alias(alias), canonical_relation_id),
        )

    def add_signature(self, canonical_relation_id: str, argument_name: str,
                      expected_type: str) -> None:
        self.connection.execute(
            "INSERT INTO relation_signature(canonical_relation_id, argument_name, expected_type) VALUES (?, ?, ?)",
            (canonical_relation_id, argument_name, expected_type),
        )

    def relation_aliases(self) -> dict[tuple[str, str], str]:
        return {(domain, alias): canonical for domain, alias, canonical in
                self.connection.execute(
                    "SELECT domain_id, alias_norm, canonical_relation_id FROM relation_alias"
                )}

    def signatures(self) -> dict[str, dict[str, str]]:
        rows = self.connection.execute(
            "SELECT canonical_relation_id, argument_name, expected_type FROM relation_signature"
        )
        result: dict[str, dict[str, str]] = {}
        for relation_id, argument, expected_type in rows:
            result.setdefault(relation_id, {})[argument] = expected_type
        return result

    def close(self) -> None:
        self.connection.close()
