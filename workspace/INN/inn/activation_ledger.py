"""Lifetime neuron activation ledger (frequency distribution baked into the Steel Brain runtime).

Every time a neuron fires (a WORD during spelling/speaking/meaning, or during corpus exposure),
its lifetime activation count is incremented, and so are the counts of every child neuron on its
hierarchical route (WORD -> COMBINATION -> CHARACTER). That turns raw experience into a native
frequency hierarchy: function words such as "the" rise to the top (a large share of English tokens),
and the rank/frequency curve can be checked against Zipf's law.

Storage is a sidecar SQLite file, separate from the SHA-256-locked neuron graph:
- Counting works even when the graph is mounted read-only.
- The graph payload hashes and the canonical store are never rewritten per activation.
- Upserts are batched, so streaming a corpus costs one transaction per batch, not per token.
"""
from __future__ import annotations

import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

DEFAULT_ACTIVATION_LEDGER_PATH = Path(
    r"L:\LocalCoder\workspace\autonomy\learning\neuron_activation_ledger.sqlite3"
)
LEDGER_SCHEMA = "VIV_NEURON_ACTIVATION_LEDGER_V1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NeuronActivationLedger:
    """Batched lifetime activation counter keyed by neuron ID."""

    def __init__(self, path: Path | str = DEFAULT_ACTIVATION_LEDGER_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS neuron_activation (
                neuron_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                surface TEXT NOT NULL,
                lifetime_count INTEGER NOT NULL DEFAULT 0,
                direct_count INTEGER NOT NULL DEFAULT 0,
                first_activated_utc TEXT NOT NULL,
                last_activated_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS neuron_activation_kind_count_idx
                ON neuron_activation(kind, lifetime_count DESC);
            CREATE TABLE IF NOT EXISTS activation_sources (
                source TEXT PRIMARY KEY,
                events INTEGER NOT NULL DEFAULT 0,
                word_tokens INTEGER NOT NULL DEFAULT 0,
                last_utc TEXT NOT NULL
            );
            """
        )
        self.connection.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES('schema', ?)", (LEDGER_SCHEMA,)
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def record(
        self,
        counts: Mapping[str, int],
        meta: Mapping[str, tuple[str, str]],
        *,
        direct: Mapping[str, int] | None = None,
        source: str,
        word_tokens: int = 0,
    ) -> int:
        """Add lifetime counts in one transaction.

        `counts`: neuron_id -> activations to add (includes hierarchical child activations).
        `meta`: neuron_id -> (kind, surface).
        `direct`: neuron_id -> activations where this neuron was the directly cued unit.
        """
        if not counts:
            return 0
        direct = direct or {}
        now = _utc_now()
        rows = [
            (nid, meta.get(nid, ("UNKNOWN", ""))[0], meta.get(nid, ("UNKNOWN", ""))[1],
             int(n), int(direct.get(nid, 0)), now, now)
            for nid, n in counts.items()
            if n > 0
        ]
        with self.connection:
            self.connection.executemany(
                """INSERT INTO neuron_activation(
                       neuron_id, kind, surface, lifetime_count, direct_count,
                       first_activated_utc, last_activated_utc)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(neuron_id) DO UPDATE SET
                       lifetime_count = lifetime_count + excluded.lifetime_count,
                       direct_count = direct_count + excluded.direct_count,
                       last_activated_utc = excluded.last_activated_utc""",
                rows,
            )
            self.connection.execute(
                """INSERT INTO activation_sources(source, events, word_tokens, last_utc)
                   VALUES(?, 1, ?, ?)
                   ON CONFLICT(source) DO UPDATE SET
                       events = events + 1,
                       word_tokens = word_tokens + excluded.word_tokens,
                       last_utc = excluded.last_utc""",
                (source, int(word_tokens), now),
            )
        return len(rows)

    def count(self, neuron_id: str) -> int:
        row = self.connection.execute(
            "SELECT lifetime_count FROM neuron_activation WHERE neuron_id = ?", (neuron_id,)
        ).fetchone()
        return int(row[0]) if row else 0

    def distribution(self, *, kind: str = "WORD", top_n: int = 25, direct_only: bool = False) -> dict[str, Any]:
        """Rank/frequency hierarchy for one neuron kind, with share %, cumulative share, and a Zipf fit.

        If `direct_only=True`, ranks exclusively by direct cued word activations (where the neuron was the
        cued word surface itself, rather than firing transitively as a sub-word piece)."""
        count_col = "direct_count" if direct_only else "lifetime_count"
        rows = self.connection.execute(
            f"SELECT neuron_id, surface, {count_col}, direct_count, lifetime_count FROM neuron_activation "
            f"WHERE kind = ? AND {count_col} > 0 ORDER BY {count_col} DESC, surface ASC",
            (kind,),
        ).fetchall()
        total = sum(int(r[2]) for r in rows)
        ranked: list[dict[str, Any]] = []
        cumulative = 0
        for rank, (nid, surface, active_cnt, direct_cnt, lifetime_cnt) in enumerate(rows, start=1):
            cumulative += int(active_cnt)
            if rank <= top_n:
                ranked.append(
                    {
                        "rank": rank,
                        "surface": surface,
                        "neuron_id": nid,
                        "active_count": int(active_cnt),
                        "lifetime_activations": int(lifetime_cnt),
                        "direct_activations": int(direct_cnt),
                        "share_percent": round(100.0 * active_cnt / total, 4) if total else 0.0,
                        "cumulative_percent": round(100.0 * cumulative / total, 4) if total else 0.0,
                    }
                )
        # Zipf fit: least squares on log(freq) = c - s * log(rank) over the top 1,000 ranks
        fit_rows = rows[: min(len(rows), 1000)]
        zipf_s = None
        r_squared = None
        if len(fit_rows) >= 10:
            xs = [math.log(i + 1) for i in range(len(fit_rows))]
            ys = [math.log(int(r[2])) for r in fit_rows]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            sxx = sum((x - mx) ** 2 for x in xs)
            sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            slope = sxy / sxx if sxx else 0.0
            ss_tot = sum((y - my) ** 2 for y in ys)
            ss_res = sum((y - (my + slope * (x - mx))) ** 2 for x, y in zip(xs, ys))
            zipf_s = round(-slope, 4)
            r_squared = round(1.0 - ss_res / ss_tot, 4) if ss_tot else None
        sources = [
            {"source": s, "events": int(e), "word_tokens": int(t), "last_utc": u}
            for s, e, t, u in self.connection.execute(
                "SELECT source, events, word_tokens, last_utc FROM activation_sources ORDER BY word_tokens DESC"
            )
        ]
        return {
            "schema": LEDGER_SCHEMA,
            "ledger_path": str(self.path),
            "kind": kind,
            "metric": "direct_activations" if direct_only else "hierarchical_lifetime_activations",
            "distinct_neurons_activated": len(rows),
            "total_lifetime_activations": total,
            "zipf_exponent_s": zipf_s,
            "zipf_fit_r_squared": r_squared,
            "top": ranked,
            "sources": sources,
        }


def tokenize_words(text: str) -> list[str]:
    """Lowercase ASCII alphabetic word tokens."""
    out: list[str] = []
    word: list[str] = []
    for ch in text:
        if ch.isascii() and ch.isalpha():
            word.append(ch.lower())
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def count_tokens(tokens: Iterable[str]) -> Counter[str]:
    return Counter(tokens)
