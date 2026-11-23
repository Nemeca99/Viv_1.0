"""Compact authoritative-candidate storage for Steel Brain neurons.

V1 is intentionally a shadow store: it can ingest existing neuron JSON files
without changing them, preserve their exact bytes, and expose the graph fields
needed for routing through indexed SQLite tables.  Human-readable JSON remains
an export format rather than the hot persistence format.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator


SCHEMA = "NN_STEEL_BRAIN_STORE_V1"
ZERO_HASH = "0" * 64


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _compress(value: bytes) -> bytes:
    return zlib.compress(value, level=9)


def _decompress(value: bytes) -> bytes:
    return zlib.decompress(value)


@dataclass(frozen=True)
class ImportedNeuron:
    token_id: int
    neuron_id: str
    kind: str
    lifecycle: str
    source_sha256: str
    content_sha256: str
    raw_bytes: int
    stored_bytes: int
    link_count: int
    child_count: int
    parent_count: int


class SQLiteNeuronGraphStore:
    """SQLite/WAL graph store with exact source-byte preservation.

    The database transaction is the unit of atomicity.  Payload bytes are
    compressed once, while links and hierarchy references are projected into
    indexed rows for CPU/Rust path finding.  The graph itself replaces a
    conventional parameter tensor: neurons are tokens and edge weights score
    start-token to end-token activation.  A failed batch commits nothing.
    """

    def __init__(
        self, path: str | Path, *, create: bool = False, readonly: bool = False
    ):
        self.path = Path(path).resolve()
        if (not readonly and self.path.name == "neuron_graph.sqlite3"
                and self.path.parent.name.startswith("language-routes-")
                and self.path.parent.parent.name == "neural_runs"):
            raise PermissionError("Published route snapshots are immutable; create a leased candidate")
        if create and readonly:
            raise ValueError("a readonly Steel Brain store cannot be created")
        if create:
            if self.path.exists():
                raise FileExistsError(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.is_file():
            raise FileNotFoundError(self.path)

        self.connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro" if readonly else self.path,
            uri=readonly,
        )
        self.connection.row_factory = sqlite3.Row
        if readonly:
            self.connection.execute("PRAGMA query_only=ON")
        else:
            self.connection.execute("PRAGMA journal_mode=WAL")
            self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=5000")
        if create:
            self._initialize()
        self._verify_schema()
        self._manifest_cache: dict[str, Any] | None = None

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteNeuronGraphStore":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            ) STRICT;

            CREATE TABLE neurons (
                token_id INTEGER PRIMARY KEY CHECK(token_id > 0),
                neuron_id TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                lifecycle TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                updated_utc TEXT NOT NULL,
                creation_event TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                payload_codec TEXT NOT NULL CHECK(payload_codec = 'JSON_UTF8_ZLIB9'),
                payload BLOB NOT NULL,
                raw_bytes INTEGER NOT NULL CHECK(raw_bytes >= 0),
                stored_bytes INTEGER NOT NULL CHECK(stored_bytes >= 0)
            ) STRICT;

            CREATE INDEX neurons_kind_lifecycle_idx
                ON neurons(kind, lifecycle, neuron_id);

            CREATE TABLE links (
                source_id TEXT NOT NULL REFERENCES neurons(neuron_id) ON DELETE RESTRICT,
                reflector TEXT NOT NULL,
                ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
                peer_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                weight INTEGER NOT NULL CHECK(weight BETWEEN 0 AND 1000000),
                uses INTEGER NOT NULL CHECK(uses >= 0),
                pass_hits INTEGER NOT NULL CHECK(pass_hits >= 0),
                fail_hits INTEGER NOT NULL CHECK(fail_hits >= 0),
                hot INTEGER NOT NULL CHECK(hot IN (0, 1)),
                evidence_count INTEGER NOT NULL CHECK(evidence_count >= 0),
                evidence_sha256 TEXT NOT NULL,
                PRIMARY KEY(source_id, reflector, ordinal)
            ) STRICT;

            CREATE INDEX links_route_idx
                ON links(source_id, reflector, hot DESC, weight DESC, peer_id);
            CREATE INDEX links_peer_idx ON links(peer_id, source_id);

            CREATE VIEW token_links AS
                SELECT source.token_id AS start_token_id,
                       target.token_id AS end_token_id,
                       links.reflector AS reflector,
                       links.direction AS direction,
                       links.weight AS weight,
                       links.uses AS uses,
                       links.pass_hits AS pass_hits,
                       links.fail_hits AS fail_hits,
                       links.hot AS hot,
                       links.evidence_count AS evidence_count
                FROM links
                JOIN neurons AS source ON source.neuron_id = links.source_id
                LEFT JOIN neurons AS target ON target.neuron_id = links.peer_id;

            CREATE TABLE hierarchy (
                parent_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                position INTEGER NOT NULL CHECK(position >= 0),
                relation TEXT NOT NULL CHECK(relation IN ('CHILD', 'PARENT_REFERENCE')),
                PRIMARY KEY(parent_id, child_id, position, relation)
            ) STRICT;

            CREATE INDEX hierarchy_child_idx
                ON hierarchy(child_id, relation, parent_id);

            CREATE TABLE graph_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                prior_event_sha256 TEXT NOT NULL,
                payload_codec TEXT NOT NULL CHECK(payload_codec = 'JSON_UTF8_ZLIB9'),
                payload BLOB NOT NULL,
                event_sha256 TEXT NOT NULL UNIQUE
            ) STRICT;
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        self.connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            (
                ("schema", SCHEMA),
                ("created_utc", now),
                ("event_head", ZERO_HASH),
                ("state", "CANDIDATE"),
                ("tokenization", "ONE_NEURON_ONE_TOKEN"),
                ("parameterization", "NEURONS_AND_WEIGHTED_TOKEN_LINKS"),
            ),
        )
        self.connection.commit()

    def _verify_schema(self) -> None:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='schema'"
        ).fetchone()
        if row is None or row[0] != SCHEMA:
            raise ValueError("unsupported Steel Brain store schema")

    def enable_neuron_identity_index(self) -> None:
        """Enable candidate physical/semantic lookup without rewriting neurons."""

        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS neuron_identity (
                neuron_id TEXT PRIMARY KEY
                    REFERENCES neurons(neuron_id) ON DELETE RESTRICT,
                physical_id TEXT NOT NULL UNIQUE,
                semantic_key TEXT NOT NULL,
                CHECK(length(physical_id) = 66 AND substr(physical_id, 1, 2) = 'P-'),
                CHECK(length(semantic_key) = 66 AND substr(semantic_key, 1, 2) = 'S-')
            ) STRICT;
            CREATE INDEX IF NOT EXISTS neuron_identity_semantic_idx
                ON neuron_identity(semantic_key, neuron_id);
            """
        )
        self.connection.commit()

    def _identity_index_enabled(self) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='neuron_identity'"
        ).fetchone() is not None

    def neuron_id_by_physical(self, physical_id: str) -> str:
        if not self._identity_index_enabled():
            raise RuntimeError("neuron physical identity index is not enabled")
        row = self.connection.execute(
            "SELECT neuron_id FROM neuron_identity WHERE physical_id=?",
            (str(physical_id),),
        ).fetchone()
        if row is None:
            raise KeyError(physical_id)
        return str(row[0])

    def neuron_ids_by_semantic(self, semantic_key: str) -> list[str]:
        if not self._identity_index_enabled():
            raise RuntimeError("neuron semantic identity index is not enabled")
        return [
            str(row[0])
            for row in self.connection.execute(
                "SELECT neuron_id FROM neuron_identity WHERE semantic_key=? ORDER BY neuron_id",
                (str(semantic_key),),
            )
        ]

    def migrate_native_neuron_identities(self) -> dict[str, Any]:
        """Assign native physical/semantic identity to every legacy neuron atomically."""

        from .neuron_graph import (
            content_hash,
            new_physical_neuron_id,
            semantic_neuron_key,
        )

        self.enable_neuron_identity_index()
        changed: list[dict[str, Any]] = []
        already_native = 0
        for row in self.connection.execute(
            "SELECT neuron_id FROM neurons ORDER BY token_id"
        ):
            neuron = self.load_neuron(str(row[0]))
            physical_id = neuron.get("physical_id")
            semantic_key = neuron.get("semantic_key")
            if physical_id is not None and semantic_key is not None:
                already_native += 1
                continue
            if physical_id is not None or semantic_key is not None:
                raise ValueError("legacy neuron has a partial identity")
            neuron["physical_id"] = new_physical_neuron_id()
            neuron["semantic_key"] = semantic_neuron_key(
                str(neuron["kind"]), dict(neuron.get("center_attractor", {}))
            )
            neuron["content_sha256"] = content_hash(neuron)
            changed.append(neuron)
        if changed:
            self.transact(
                changed,
                event_kind="NATIVE_NEURON_IDENTITY_MIGRATION_V1",
                details={
                    "migrated": len(changed),
                    "already_native": already_native,
                    "identity_bits": 256,
                    "random_identity_used_as_route_probability": False,
                },
            )
        return {
            "migrated": len(changed),
            "already_native": already_native,
            "total": len(changed) + already_native,
        }

    def enable_edge_identity_index(self) -> None:
        """Enable deterministic physical edge addressing in a candidate store."""

        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS edge_identity (
                edge_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                reflector TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                peer_id TEXT NOT NULL,
                source_physical_id TEXT NOT NULL,
                peer_physical_id TEXT NOT NULL,
                direction TEXT NOT NULL,
                UNIQUE(source_id, reflector, ordinal),
                FOREIGN KEY(source_id, reflector, ordinal)
                    REFERENCES links(source_id, reflector, ordinal)
                    ON DELETE CASCADE
            ) STRICT;
            CREATE INDEX IF NOT EXISTS edge_identity_source_idx
                ON edge_identity(source_physical_id, edge_id);
            CREATE INDEX IF NOT EXISTS edge_identity_peer_idx
                ON edge_identity(peer_physical_id, edge_id);
            """
        )
        self.connection.commit()

    def _edge_identity_index_enabled(self) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='edge_identity'"
        ).fetchone() is not None

    def _refresh_edge_identities_for_source(self, source_id: str) -> None:
        """Refresh the derived physical-edge projection inside an open transaction."""

        if not self._edge_identity_index_enabled():
            return
        rows = list(self.connection.execute(
            """SELECT l.source_id,l.reflector,l.ordinal,l.peer_id,l.direction,
                      s.physical_id AS source_physical_id,p.physical_id AS peer_physical_id
                 FROM links l JOIN neuron_identity s ON s.neuron_id=l.source_id
                 JOIN neuron_identity p ON p.neuron_id=l.peer_id
                 WHERE l.source_id=? ORDER BY l.reflector,l.ordinal""", (str(source_id),),
        ))
        for row in rows:
            edge_id = "R-" + _sha256_bytes(_canonical_json({
                "schema": "NN_PHYSICAL_EDGE_ID_V1",
                "source_physical_id": str(row["source_physical_id"]),
                "peer_physical_id": str(row["peer_physical_id"]),
                "reflector": str(row["reflector"]), "direction": str(row["direction"]),
                "ordinal": int(row["ordinal"]),
            }))
            self.connection.execute(
                "INSERT INTO edge_identity VALUES(?,?,?,?,?,?,?,?)",
                (edge_id, str(row["source_id"]), str(row["reflector"]), int(row["ordinal"]),
                 str(row["peer_id"]), str(row["source_physical_id"]),
                 str(row["peer_physical_id"]), str(row["direction"])),
            )

    def rebuild_native_edge_identities(self) -> dict[str, Any]:
        """Derive one stable edge ID from each pair of physical endpoints."""

        if not self._identity_index_enabled():
            raise RuntimeError("native neuron identities must exist before edge identities")
        neuron_count = int(self.connection.execute(
            "SELECT COUNT(*) FROM neurons"
        ).fetchone()[0])
        identity_count = int(self.connection.execute(
            "SELECT COUNT(*) FROM neuron_identity"
        ).fetchone()[0])
        if neuron_count != identity_count:
            raise RuntimeError("native neuron identity migration is incomplete")
        rows = list(self.connection.execute(
            """SELECT l.source_id,l.reflector,l.ordinal,l.peer_id,l.direction,
                      s.physical_id AS source_physical_id,
                      p.physical_id AS peer_physical_id
               FROM links l
               JOIN neuron_identity s ON s.neuron_id=l.source_id
               JOIN neuron_identity p ON p.neuron_id=l.peer_id
               ORDER BY l.source_id,l.reflector,l.ordinal"""
        ))
        link_count = int(self.connection.execute(
            "SELECT COUNT(*) FROM links"
        ).fetchone()[0])
        if len(rows) != link_count:
            raise RuntimeError("edge identity derivation found an unresolved endpoint")
        self.enable_edge_identity_index()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.connection.execute("DELETE FROM edge_identity")
            for row in rows:
                material = _canonical_json({
                    "schema": "NN_PHYSICAL_EDGE_ID_V1",
                    "source_physical_id": str(row["source_physical_id"]),
                    "peer_physical_id": str(row["peer_physical_id"]),
                    "reflector": str(row["reflector"]),
                    "direction": str(row["direction"]),
                    "ordinal": int(row["ordinal"]),
                })
                edge_id = "R-" + _sha256_bytes(material)
                self.connection.execute(
                    "INSERT INTO edge_identity VALUES(?,?,?,?,?,?,?,?)",
                    (
                        edge_id, str(row["source_id"]), str(row["reflector"]),
                        int(row["ordinal"]), str(row["peer_id"]),
                        str(row["source_physical_id"]), str(row["peer_physical_id"]),
                        str(row["direction"]),
                    ),
                )
            self._append_event(
                "NATIVE_EDGE_IDENTITY_INDEX_V1",
                {"edges": len(rows), "derivation": "PHYSICAL_ENDPOINTS_AND_CHANNEL"},
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return {"edges": len(rows), "resolved": len(rows), "unresolved": 0}

    def edge_by_id(self, edge_id: str) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT * FROM edge_identity WHERE edge_id=?", (str(edge_id),)
        ).fetchone()
        if row is None:
            raise KeyError(edge_id)
        return dict(row)

    def best_physical_path(
        self, start_physical_id: str, end_physical_id: str, *, max_hops: int = 8
    ) -> dict[str, Any]:
        """Find the strongest bounded learned path between two physical neurons."""

        if max_hops < 1:
            raise ValueError("physical pathfinding requires at least one hop")
        start_id = self.neuron_id_by_physical(start_physical_id)
        end_id = self.neuron_id_by_physical(end_physical_id)
        if start_id == end_id:
            return {
                "state": "PASS", "score": 1_000_000, "hops": 0,
                "neuron_ids": [start_id], "physical_ids": [start_physical_id],
                "edge_ids": [],
            }
        frontier: dict[str, tuple[int, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {
            start_id: (1_000_000, (), (start_id,), (str(start_physical_id),))
        }
        best_seen: dict[str, tuple[int, tuple[str, ...]]] = {
            start_id: (1_000_000, ())
        }
        best_target: tuple[
            int, int, tuple[str, ...], tuple[str, ...], tuple[str, ...]
        ] | None = None
        for hop in range(1, max_hops + 1):
            next_frontier: dict[
                str, tuple[int, tuple[str, ...], tuple[str, ...], tuple[str, ...]]
            ] = {}
            for source_id, (score, edge_path, neuron_path, physical_path) in sorted(frontier.items()):
                rows = self.connection.execute(
                    """SELECT e.edge_id,e.peer_id,e.peer_physical_id,l.weight
                       FROM edge_identity e
                       JOIN links l ON l.source_id=e.source_id
                          AND l.reflector=e.reflector AND l.ordinal=e.ordinal
                       WHERE e.source_id=? AND l.hot=1 AND l.weight>0
                       ORDER BY e.edge_id""",
                    (source_id,),
                )
                for row in rows:
                    peer_id = str(row["peer_id"])
                    candidate_score = max(
                        1, (score * int(row["weight"])) // 1_000_000
                    )
                    candidate_edges = (*edge_path, str(row["edge_id"]))
                    prior = best_seen.get(peer_id)
                    if prior is not None and (
                        candidate_score < prior[0]
                        or (candidate_score == prior[0] and candidate_edges >= prior[1])
                    ):
                        continue
                    candidate = (
                        candidate_score,
                        candidate_edges,
                        (*neuron_path, peer_id),
                        (*physical_path, str(row["peer_physical_id"])),
                    )
                    best_seen[peer_id] = (candidate_score, candidate_edges)
                    current = next_frontier.get(peer_id)
                    if current is None or candidate_score > current[0] or (
                        candidate_score == current[0] and candidate_edges < current[1]
                    ):
                        next_frontier[peer_id] = candidate
            target = next_frontier.get(end_id)
            if target is not None:
                candidate_target = (target[0], hop, target[1], target[2], target[3])
                if best_target is None or candidate_target[0] > best_target[0] or (
                    candidate_target[0] == best_target[0]
                    and (candidate_target[1], candidate_target[2])
                    < (best_target[1], best_target[2])
                ):
                    best_target = candidate_target
            if not next_frontier:
                break
            frontier = next_frontier
        if best_target is not None:
            return {
                "state": "PASS", "score": best_target[0], "hops": best_target[1],
                "edge_ids": list(best_target[2]),
                "neuron_ids": list(best_target[3]),
                "physical_ids": list(best_target[4]),
            }
        return {
            "state": "HOLD", "reason": "NO_SUPPORTED_PATH_WITHIN_BOUND",
            "score": 0, "hops": 0, "neuron_ids": [start_id],
            "physical_ids": [str(start_physical_id)], "edge_ids": [],
        }

    def rank_physical_semantic_frontier(
        self,
        start_physical_id: str,
        *,
        allowed_edge_ids: Iterable[str] | None = None,
        multiplicity_cap: int = 200_000,
        quality_guard: int = 100_000,
        saturation: int = 8,
    ) -> dict[str, Any]:
        """Rank outgoing semantic groups with a bounded repetition prior."""

        if not 0 <= multiplicity_cap <= 1_000_000:
            raise ValueError("multiplicity cap outside fixed-point bounds")
        if not 0 <= quality_guard <= 1_000_000 or saturation < 1:
            raise ValueError("invalid semantic frontier guard")
        start_id = self.neuron_id_by_physical(start_physical_id)
        rows = list(self.connection.execute(
            """SELECT e.edge_id,e.peer_id,e.peer_physical_id,l.weight,
                      i.semantic_key
               FROM edge_identity e
               JOIN links l ON l.source_id=e.source_id
                  AND l.reflector=e.reflector AND l.ordinal=e.ordinal
               JOIN neuron_identity i ON i.neuron_id=e.peer_id
               WHERE e.source_id=? AND l.hot=1 AND l.weight>0
               ORDER BY e.edge_id""",
            (start_id,),
        ))
        allowed = None if allowed_edge_ids is None else {str(value) for value in allowed_edge_ids}
        if allowed is not None:
            rows = [row for row in rows if str(row["edge_id"]) in allowed]
        if not rows:
            return {
                "state": "HOLD", "reason": "NO_SUPPORTED_UNLOCKED_FRONTIER",
                "raw_frontier": 0, "semantic_frontier": 0, "groups": [],
            }
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            groups.setdefault(str(row["semantic_key"]), []).append(row)
        best_raw = max(int(row["weight"]) for row in rows)
        ranked: list[dict[str, Any]] = []
        for semantic_key, members in groups.items():
            ordered = sorted(
                members, key=lambda row: (-int(row["weight"]), str(row["edge_id"]))
            )
            champion = ordered[0]
            base = int(champion["weight"])
            multiplicity = len(members)
            prior = (
                multiplicity_cap * max(0, multiplicity - 1)
                // (max(0, multiplicity - 1) + saturation)
            )
            adjusted = base + ((1_000_000 - base) * prior) // 1_000_000
            materially_weaker = base <= best_raw - quality_guard
            if materially_weaker:
                adjusted = min(adjusted, max(0, best_raw - 1))
            ranked.append({
                "semantic_key": semantic_key,
                "multiplicity": multiplicity,
                "base_weight": base,
                "multiplicity_prior": prior,
                "adjusted_weight": adjusted,
                "materially_weaker_than_best": materially_weaker,
                "champion_edge_id": str(champion["edge_id"]),
                "champion_neuron_id": str(champion["peer_id"]),
                "champion_physical_id": str(champion["peer_physical_id"]),
                "member_edge_ids": [str(row["edge_id"]) for row in ordered],
            })
        ranked.sort(
            key=lambda row: (
                -int(row["adjusted_weight"]), -int(row["base_weight"]),
                str(row["semantic_key"]), str(row["champion_edge_id"]),
            )
        )
        return {
            "state": "PASS", "start_neuron_id": start_id,
            "raw_frontier": len(rows), "semantic_frontier": len(ranked),
            "multiplicity_cap": multiplicity_cap, "quality_guard": quality_guard,
            "saturation": saturation, "groups": ranked,
        }

    def apply_physical_route_verdict(
        self, edge_ids: Iterable[str], *, passed: bool, event_id: str,
    ) -> dict[str, Any]:
        """Apply one consequence only to the exact attempted physical edges."""

        from .fixed_point import toward_one, toward_zero
        from .neuron_graph import content_hash

        route = [str(value) for value in edge_ids]
        if not route:
            raise ValueError("physical route verdict requires at least one edge")
        resolved = []
        prior_peer = None
        for edge_id in route:
            row = self.connection.execute(
                """SELECT edge_id,source_id,peer_id,reflector,ordinal
                     FROM edge_identity WHERE edge_id=?""", (edge_id,),
            ).fetchone()
            if row is None:
                raise KeyError(edge_id)
            if prior_peer is not None and str(row["source_id"]) != prior_peer:
                raise ValueError("physical route is not contiguous")
            resolved.append(row)
            prior_peer = str(row["peer_id"])
        changed: dict[str, dict[str, Any]] = {}
        before = []
        after = []
        for row in resolved:
            source_id = str(row["source_id"])
            neuron = changed.get(source_id) or self.load_neuron(source_id)
            reflector = str(row["reflector"]); ordinal = int(row["ordinal"])
            edges = neuron["reflectors"][reflector]
            if ordinal >= len(edges):
                raise RuntimeError("physical edge ordinal escaped neuron payload")
            edge = edges[ordinal]
            if str(edge["peer_id"]) != str(row["peer_id"]):
                raise RuntimeError("physical edge identity/payload mismatch")
            before.append({
                "edge_id": str(row["edge_id"]), "weight": int(edge["weight"]),
                "uses": int(edge["uses"]), "pass_hits": int(edge["pass_hits"]),
                "fail_hits": int(edge["fail_hits"]), "hot": bool(edge["hot"]),
            })
            edge["uses"] += 1; edge["evidence_events"].append(str(event_id))
            if passed:
                edge["pass_hits"] += 1
                edge["weight"] = toward_one(int(edge["weight"]), 900_000)
                edge["hot"] = True
            else:
                edge["fail_hits"] += 1
                edge["weight"] = toward_zero(int(edge["weight"]), 150_000)
                if int(edge["weight"]) < 10_000:
                    edge["hot"] = False
            neuron["updated_utc"] = datetime.now(timezone.utc).isoformat()
            neuron["content_sha256"] = content_hash(neuron)
            changed[source_id] = neuron
            after.append({
                "edge_id": str(row["edge_id"]), "weight": int(edge["weight"]),
                "uses": int(edge["uses"]), "pass_hits": int(edge["pass_hits"]),
                "fail_hits": int(edge["fail_hits"]), "hot": bool(edge["hot"]),
            })
        head = self.transact(
            changed.values(), event_kind="PHYSICAL_ROUTE_ONE_BIT_VERDICT_V1",
            details={
                "event_id": str(event_id), "passed": bool(passed),
                "edge_ids": route, "hidden_alternative_strengthened": False,
            },
        )
        return {"state": "PASS", "passed": bool(passed), "before": before, "after": after, "event_head": head}

    @staticmethod
    def _load_neuron(path: Path) -> tuple[dict[str, Any], bytes]:
        raw = path.read_bytes()
        neuron = json.loads(raw.decode("utf-8"))
        if neuron.get("schema") != "NN_EXPERT_NEURON_V1":
            raise ValueError(f"unsupported neuron schema: {path}")
        return neuron, raw

    @staticmethod
    def _edge_rows(neuron: dict[str, Any]) -> Iterator[tuple[Any, ...]]:
        source_id = str(neuron["neuron_id"])
        for reflector, edges in neuron.get("reflectors", {}).items():
            for ordinal, edge in enumerate(edges):
                evidence = edge.get("evidence_events", [])
                evidence_bytes = _canonical_json(evidence)
                yield (
                    source_id,
                    str(reflector),
                    ordinal,
                    str(edge["peer_id"]),
                    str(edge.get("direction", "OUT")),
                    int(edge.get("weight", 0)),
                    int(edge.get("uses", 0)),
                    int(edge.get("pass_hits", 0)),
                    int(edge.get("fail_hits", 0)),
                    int(bool(edge.get("hot", False))),
                    len(evidence),
                    _sha256_bytes(evidence_bytes),
                )

    @staticmethod
    def _hierarchy_rows(neuron: dict[str, Any]) -> Iterator[tuple[Any, ...]]:
        neuron_id = str(neuron["neuron_id"])
        for position, child_id in enumerate(neuron.get("children", [])):
            yield neuron_id, str(child_id), position, "CHILD"
        # Parent references are the reverse index of authoritative child rows.
        # Materializing both directions made high-fan-in character neurons grow
        # hundreds of thousands of duplicate rows.  The exact imported parent
        # list remains losslessly available in the compressed source payload;
        # live reverse traversal uses hierarchy_child_idx over CHILD rows.

    def _event_head(self) -> str:
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='event_head'"
        ).fetchone()
        return str(row[0])

    def _append_event(self, event_type: str, payload_value: Any) -> str:
        prior = self._event_head()
        created = datetime.now(timezone.utc).isoformat()
        payload_raw = _canonical_json(payload_value)
        event_id = _sha256_bytes(
            prior.encode("ascii") + event_type.encode("utf-8") + payload_raw
        )
        event_material = _canonical_json(
            {
                "event_id": event_id,
                "event_type": event_type,
                "created_utc": created,
                "prior_event_sha256": prior,
                "payload_sha256": _sha256_bytes(payload_raw),
            }
        )
        event_sha256 = _sha256_bytes(event_material)
        self.connection.execute(
            """INSERT INTO graph_events(
                   event_id, event_type, created_utc, prior_event_sha256,
                   payload_codec, payload, event_sha256
               ) VALUES (?, ?, ?, ?, 'JSON_UTF8_ZLIB9', ?, ?)""",
            (event_id, event_type, created, prior, _compress(payload_raw), event_sha256),
        )
        self.connection.execute(
            "UPDATE metadata SET value=? WHERE key='event_head'", (event_sha256,)
        )
        return event_sha256

    def import_paths(
        self, graph_root: str | Path, relative_paths: Iterable[str]
    ) -> list[ImportedNeuron]:
        root = Path(graph_root).resolve()
        prepared: list[tuple[dict[str, Any], bytes, bytes, str]] = []
        for relative in relative_paths:
            path = (root / relative).resolve()
            if root not in path.parents:
                raise ValueError(f"neuron path escapes graph root: {relative}")
            neuron, raw = self._load_neuron(path)
            prepared.append((neuron, raw, _compress(raw), str(relative)))
        if not prepared:
            return []

        imported: list[ImportedNeuron] = []
        ids: list[str] = []
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            next_token_id = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(token_id), 0) + 1 FROM neurons"
                ).fetchone()[0]
            )
            for neuron, raw, packed, relative in prepared:
                neuron_id = str(neuron["neuron_id"])
                token_id = next_token_id
                next_token_id += 1
                source_sha256 = _sha256_bytes(raw)
                links = list(self._edge_rows(neuron))
                hierarchy = list(self._hierarchy_rows(neuron))
                self.connection.execute(
                    """INSERT INTO neurons(
                           token_id, neuron_id, kind, lifecycle, created_utc, updated_utc,
                           creation_event, content_sha256, source_sha256,
                           payload_codec, payload, raw_bytes, stored_bytes
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'JSON_UTF8_ZLIB9', ?, ?, ?)""",
                    (
                        token_id,
                        neuron_id,
                        str(neuron["kind"]),
                        str(neuron["lifecycle"]),
                        str(neuron["created_utc"]),
                        str(neuron["updated_utc"]),
                        str(neuron["creation_event"]),
                        str(neuron["content_sha256"]),
                        source_sha256,
                        packed,
                        len(raw),
                        len(packed),
                    ),
                )
                self.connection.executemany(
                    """INSERT INTO links(
                           source_id, reflector, ordinal, peer_id, direction,
                           weight, uses, pass_hits, fail_hits, hot,
                           evidence_count, evidence_sha256
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    links,
                )
                self.connection.executemany(
                    """INSERT INTO hierarchy(
                           parent_id, child_id, position, relation
                       ) VALUES (?, ?, ?, ?)""",
                    hierarchy,
                )
                imported.append(
                    ImportedNeuron(
                        token_id=token_id,
                        neuron_id=neuron_id,
                        kind=str(neuron["kind"]),
                        lifecycle=str(neuron["lifecycle"]),
                        source_sha256=source_sha256,
                        content_sha256=str(neuron["content_sha256"]),
                        raw_bytes=len(raw),
                        stored_bytes=len(packed),
                        link_count=len(links),
                        child_count=len(neuron.get("children", [])),
                        parent_count=len(neuron.get("parents", [])),
                    )
                )
                ids.append(neuron_id)
            self._append_event(
                "SHADOW_IMPORT",
                {
                    "source_root": str(root),
                    "count": len(ids),
                    "neuron_ids_sha256": _sha256_bytes(_canonical_json(ids)),
                    "token_range": [next_token_id - len(ids), next_token_id - 1],
                    "token_map_sha256": _sha256_bytes(
                        _canonical_json(
                            [
                                list(row)
                                for row in self.connection.execute(
                                    "SELECT token_id, neuron_id FROM neurons ORDER BY token_id"
                                )
                            ]
                        )
                    ),
                    "source_paths_sha256": _sha256_bytes(
                        _canonical_json([item[3] for item in prepared])
                    ),
                },
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
        return imported

    def read_raw(self, neuron_id: str) -> bytes:
        row = self.connection.execute(
            "SELECT payload, source_sha256 FROM neurons WHERE neuron_id=?",
            (neuron_id,),
        ).fetchone()
        if row is None:
            raise KeyError(neuron_id)
        raw = _decompress(bytes(row["payload"]))
        if _sha256_bytes(raw) != row["source_sha256"]:
            raise RuntimeError(f"stored payload hash mismatch: {neuron_id}")
        return raw

    def token_id(self, neuron_id: str) -> int:
        row = self.connection.execute(
            "SELECT token_id FROM neurons WHERE neuron_id=?", (neuron_id,)
        ).fetchone()
        if row is None:
            raise KeyError(neuron_id)
        return int(row[0])

    def neuron_id(self, token_id: int) -> str:
        row = self.connection.execute(
            "SELECT neuron_id FROM neurons WHERE token_id=?", (int(token_id),)
        ).fetchone()
        if row is None:
            raise KeyError(token_id)
        return str(row[0])

    def read_raw_by_token(self, token_id: int) -> bytes:
        return self.read_raw(self.neuron_id(token_id))

    def load_neuron(self, neuron_id: str) -> dict[str, Any]:
        neuron = json.loads(self.read_raw(neuron_id).decode("utf-8"))
        if neuron.get("neuron_id") != neuron_id:
            raise RuntimeError(f"stored neuron identity mismatch: {neuron_id}")
        return neuron

    def _apply_neuron_to_manifest(self, manifest: dict[str, Any], neuron: dict[str, Any]) -> None:
        neuron_id = str(neuron["neuron_id"])
        kind = str(neuron["kind"])
        lifecycle = str(neuron["lifecycle"])
        prev = manifest["neuron_index"].get(neuron_id)
        if prev is not None:
            old_kind = str(prev.get("kind", ""))
            old_life = str(prev.get("lifecycle", ""))
            if old_kind in manifest["kind_counts"]:
                manifest["kind_counts"][old_kind] = max(0, manifest["kind_counts"][old_kind] - 1)
            if old_life in manifest["lifecycle_counts"]:
                manifest["lifecycle_counts"][old_life] = max(0, manifest["lifecycle_counts"][old_life] - 1)
        manifest["neuron_index"][neuron_id] = {
            "kind": kind,
            "lifecycle": lifecycle,
            "content_sha256": str(neuron["content_sha256"]),
        }
        manifest["kind_counts"][kind] = manifest["kind_counts"].get(kind, 0) + 1
        manifest["lifecycle_counts"][lifecycle] = manifest["lifecycle_counts"].get(lifecycle, 0) + 1
        center = neuron.get("center_attractor", {})
        surface = center.get("learned_surface")
        character = center.get("learned_character")
        combination = center.get("learned_combination")
        visible_state = center.get("visible_state_id")
        if kind == "WORD" and isinstance(surface, str) and surface:
            manifest["word_index"][surface] = neuron_id
            manifest["state_index"][f"WORD:{surface}"] = neuron_id
        if kind == "CHARACTER" and isinstance(character, str) and character:
            manifest["character_index"][character] = neuron_id
        if kind == "COMBINATION" and isinstance(combination, str) and combination:
            manifest["combination_index"][combination] = neuron_id
            manifest["state_index"][f"COMBINATION:{combination}"] = neuron_id
        if isinstance(visible_state, str) and visible_state:
            manifest["state_index"][visible_state] = neuron_id

    def manifest(self) -> dict[str, Any]:
        if self._manifest_cache is not None:
            return self._manifest_cache
        manifest: dict[str, Any] = {
            "schema": "NN_NEURON_GRAPH_MANIFEST_V1",
            "neuron_index": {},
            "word_index": {},
            "character_index": {},
            "combination_index": {},
            "state_index": {},
            "kind_counts": {},
            "lifecycle_counts": {},
            "events": int(self.connection.execute(
                "SELECT COUNT(*) FROM graph_events"
            ).fetchone()[0]),
            "ledger_head": self._event_head(),
        }
        rows = self.connection.execute(
            "SELECT neuron_id,kind,lifecycle,content_sha256,payload FROM neurons ORDER BY token_id"
        )
        for row in rows:
            neuron = json.loads(_decompress(bytes(row["payload"])).decode("utf-8"))
            self._apply_neuron_to_manifest(manifest, neuron)
        self._manifest_cache = manifest
        return manifest

    def transact(
        self,
        neurons: Iterable[dict[str, Any]],
        *,
        event_kind: str,
        details: dict[str, Any],
        manifest_mutator: Any | None = None,
    ) -> str:
        """Atomically upsert neurons, links, hierarchy, and one chained event."""
        changed = list(neurons)
        if not changed:
            raise ValueError("transaction requires at least one neuron")
        if manifest_mutator is not None:
            raise ValueError("SQLite live store does not accept external manifest mutation")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            next_token = int(self.connection.execute(
                "SELECT COALESCE(MAX(token_id),0)+1 FROM neurons"
            ).fetchone()[0])
            changed_ids: list[str] = []
            for neuron in changed:
                neuron_id = str(neuron["neuron_id"])
                raw = _canonical_json(neuron)
                packed = _compress(raw)
                existing = self.connection.execute(
                    "SELECT token_id FROM neurons WHERE neuron_id=?", (neuron_id,)
                ).fetchone()
                token_id = int(existing[0]) if existing is not None else next_token
                if existing is None:
                    next_token += 1
                self.connection.execute(
                    """INSERT INTO neurons(
                           token_id,neuron_id,kind,lifecycle,created_utc,updated_utc,
                           creation_event,content_sha256,source_sha256,payload_codec,
                           payload,raw_bytes,stored_bytes
                       ) VALUES(?,?,?,?,?,?,?,?,?,'JSON_UTF8_ZLIB9',?,?,?)
                       ON CONFLICT(neuron_id) DO UPDATE SET
                           kind=excluded.kind,lifecycle=excluded.lifecycle,
                           updated_utc=excluded.updated_utc,
                           creation_event=excluded.creation_event,
                           content_sha256=excluded.content_sha256,
                           source_sha256=excluded.source_sha256,
                           payload=excluded.payload,raw_bytes=excluded.raw_bytes,
                           stored_bytes=excluded.stored_bytes""",
                    (
                        token_id, neuron_id, str(neuron["kind"]),
                        str(neuron["lifecycle"]), str(neuron["created_utc"]),
                        str(neuron["updated_utc"]), str(neuron["creation_event"]),
                        str(neuron["content_sha256"]), _sha256_bytes(raw), packed,
                        len(raw), len(packed),
                    ),
                )
                physical_id = neuron.get("physical_id")
                semantic_key = neuron.get("semantic_key")
                # Identity removal must fail just like replacement: otherwise
                # the durable lookup row outlives the identity in the payload.
                identity = None
                if self._identity_index_enabled():
                    identity = self.connection.execute(
                        "SELECT physical_id,semantic_key FROM neuron_identity WHERE neuron_id=?",
                        (neuron_id,),
                    ).fetchone()
                if identity is not None and (
                    identity["physical_id"] != physical_id
                    or identity["semantic_key"] != semantic_key
                ):
                    raise ValueError("neuron physical and semantic identities are immutable")
                if physical_id is not None or semantic_key is not None:
                    if not self._identity_index_enabled():
                        raise RuntimeError(
                            "physical neuron birth requires the identity index"
                        )
                    if identity is None:
                        self.connection.execute(
                            "INSERT INTO neuron_identity(neuron_id,physical_id,semantic_key) VALUES(?,?,?)",
                            (neuron_id, str(physical_id), str(semantic_key)),
                        )
                    elif (
                        str(identity["physical_id"]) != str(physical_id)
                        or str(identity["semantic_key"]) != str(semantic_key)
                    ):
                        raise ValueError("neuron physical and semantic identities are immutable")
                self.connection.execute("DELETE FROM links WHERE source_id=?", (neuron_id,))
                self.connection.execute("DELETE FROM hierarchy WHERE parent_id=?", (neuron_id,))
                self.connection.executemany(
                    """INSERT INTO links(
                           source_id,reflector,ordinal,peer_id,direction,weight,uses,
                           pass_hits,fail_hits,hot,evidence_count,evidence_sha256
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    list(self._edge_rows(neuron)),
                )
                self._refresh_edge_identities_for_source(neuron_id)
                self.connection.executemany(
                    "INSERT INTO hierarchy(parent_id,child_id,position,relation) VALUES(?,?,?,?)",
                    list(self._hierarchy_rows(neuron)),
                )
                changed_ids.append(neuron_id)
            event_head = self._append_event(
                str(event_kind),
                {"details": details, "changed_neuron_ids": changed_ids},
            )
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            self._manifest_cache = None
            raise
        if self._manifest_cache is not None:
            for neuron in changed:
                self._apply_neuron_to_manifest(self._manifest_cache, neuron)
            self._manifest_cache["events"] = int(self._manifest_cache.get("events", 0)) + 1
            self._manifest_cache["ledger_head"] = event_head
        return event_head

    def recover(self) -> dict[str, Any]:
        row = self.connection.execute("PRAGMA integrity_check").fetchone()
        wal = self.connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        return {
            "state": "PASS" if row and row[0] == "ok" else "FAIL",
            "integrity_check": row[0] if row else "missing",
            "wal_checkpoint": list(wal) if wal is not None else [],
        }

    def audit(self) -> dict[str, Any]:
        neuron = self.connection.execute(
            """SELECT COUNT(*) AS count, COALESCE(SUM(raw_bytes), 0) AS raw_bytes,
                      COALESCE(SUM(stored_bytes), 0) AS stored_bytes
               FROM neurons"""
        ).fetchone()
        link = self.connection.execute(
            "SELECT COUNT(*) AS count, COALESCE(SUM(weight), 0) AS weight_sum FROM links"
        ).fetchone()
        links = int(link["count"])
        resolved_links = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM token_links WHERE end_token_id IS NOT NULL"
            ).fetchone()[0]
        )
        hierarchy = int(
            self.connection.execute("SELECT COUNT(*) FROM hierarchy").fetchone()[0]
        )
        token = self.connection.execute(
            """SELECT COUNT(*) AS count, COALESCE(MIN(token_id), 0) AS minimum,
                      COALESCE(MAX(token_id), 0) AS maximum,
                      COUNT(DISTINCT token_id) AS distinct_count
               FROM neurons"""
        ).fetchone()
        events = list(
            self.connection.execute(
                """SELECT event_id,event_type,created_utc,prior_event_sha256,
                          payload_codec,payload,event_sha256
                   FROM graph_events ORDER BY sequence"""
            )
        )
        head = ZERO_HASH
        chain_valid = True
        for event in events:
            # Linked hash strings alone do not authenticate the stored evidence.
            # Recompute the same byte-level material used by _append_event.
            try:
                payload_raw = _decompress(event["payload"])
                expected_id = _sha256_bytes(
                    head.encode("ascii") + event["event_type"].encode("utf-8") + payload_raw
                )
                expected_hash = _sha256_bytes(_canonical_json({
                    "event_id": expected_id,
                    "event_type": event["event_type"],
                    "created_utc": event["created_utc"],
                    "prior_event_sha256": head,
                    "payload_sha256": _sha256_bytes(payload_raw),
                }))
            except (zlib.error, TypeError, AttributeError, UnicodeError):
                chain_valid = False
                break
            if (
                event["prior_event_sha256"] != head
                or event["payload_codec"] != "JSON_UTF8_ZLIB9"
                or event["event_id"] != expected_id
                or event["event_sha256"] != expected_hash
            ):
                chain_valid = False
                break
            head = str(event["event_sha256"])
        chain_valid = chain_valid and head == self._event_head()
        raw_bytes = int(neuron["raw_bytes"])
        stored_bytes = int(neuron["stored_bytes"])
        return {
            "schema": SCHEMA,
            # Partial imports may exist, but unresolved routes are not a PASS.
            "state": "PASS" if chain_valid and resolved_links == links else "FAIL",
            "neurons": int(neuron["count"]),
            "tokens": int(token["count"]),
            "token_min": int(token["minimum"]),
            "token_max": int(token["maximum"]),
            "token_ids_unique": int(token["count"]) == int(token["distinct_count"]),
            "links": links,
            "weight_sum": int(link["weight_sum"]),
            "token_links_resolved": resolved_links,
            "token_links_unresolved": links - resolved_links,
            "hierarchy_rows": hierarchy,
            "events": len(events),
            "event_chain_valid": chain_valid,
            "raw_payload_bytes": raw_bytes,
            "compressed_payload_bytes": stored_bytes,
            "payload_compression_ratio": (
                raw_bytes / stored_bytes if stored_bytes else 1.0
            ),
            "database_bytes": self.path.stat().st_size,
        }


__all__ = ["ImportedNeuron", "SCHEMA", "SQLiteNeuronGraphStore"]
