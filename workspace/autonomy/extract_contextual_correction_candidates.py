"""Read-only extraction of pending correction examples from local corpus cartridges."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import random
import sys


HERE = Path(__file__).resolve().parent
SPEC = HERE / "learning" / "contextual_correction_evals" / "contextual_correction_dataset_v1_spec.md"
CORPUS_ROOT = Path(r"F:\AI_Datasets\domain_dbs")
DOMAIN_DATABASES = {
    "geometry": ("wiki_mathematics.sqlite3", "wiki_physics.sqlite3"),
    "geography": ("wiki_geography.sqlite3",),
    "finance": ("wiki_general.sqlite3",),
    "civic": ("wiki_general.sqlite3",),
    "general": ("wiki_general.sqlite3",),
}
SPLIT_TARGET_PER_DOMAIN = 60
RESERVOIR_PER_PAIR = 240
SEED = 20261110

FIELDS = [
    "example_id", "split", "domain_id", "confusion_set_id", "confusion_type",
    "source_id", "source_revision", "source_locator", "source_text",
    "source_start", "source_end", "question", "input_text", "typo_start",
    "typo_end", "gold_token", "typo_token", "distractor_token", "mutation_rule",
    "mutation_seed", "proposal_candidate", "candidate_class", "review_status",
    "review_note", "record_sha256",
]


def _sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_confusions() -> list[dict]:
    rows = []
    domain_id = None
    for line in SPEC.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^### .+ \(`([A-Z]+)`\)", line)
        if heading:
            domain_id = {"GEO": "geometry", "GEOX": "geography", "FIN": "finance",
                         "CIV": "civic", "GEN": "general"}[heading.group(1)]
            continue
        if not domain_id or not line.startswith("|"):
            continue
        parts = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(parts) != 4 or not re.fullmatch(r"[A-Z]+-\d{2}", parts[0]):
            continue
        kind = parts[3].casefold()
        if "homophone" not in kind or "near" in kind or "supplemental" in kind or "accent-sensitive" in kind:
            continue
        words = [w.strip().casefold() for w in parts[1].split("/")]
        if len(words) < 2 or any(not re.fullmatch(r"[a-z]+", word) for word in words):
            continue
        pair_num = int(parts[0].rsplit("-", 1)[1])
        split = "calibration" if pair_num % 2 else "held_out"
        rows.append({"domain": domain_id, "pair_id": parts[0], "words": words,
                     "confusion_type": "homophone", "split": split})
    return rows


def _one_edit_variants(word: str) -> list[tuple[str, str]]:
    variants: set[tuple[str, str]] = set()
    if len(word) > 3:
        for i in range(len(word)):
            variants.add((word[:i] + word[i + 1:], f"delete_char:v1:index={i}"))
    for i in range(len(word) - 1):
        if word[i] != word[i + 1]:
            changed = word[:i] + word[i + 1] + word[i] + word[i + 2:]
            variants.add((changed, f"transpose_adjacent:v1:index={i}"))
    for i, old in enumerate(word):
        for new in "abcdefghijklmnopqrstuvwxyz":
            if new != old:
                variants.add((word[:i] + new + word[i + 1:],
                              f"substitute_char:v1:index={i}:to={new}"))
    return sorted(variants)


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def _mutation(gold: str, distractor: str, pair_words: list[str]) -> tuple[str, str] | None:
    choices = []
    for typo, rule in _one_edit_variants(gold):
        if typo in pair_words or not typo.isalpha() or len(typo) < 2:
            continue
        distance = _edit_distance(typo, distractor)
        if distance <= 2:
            choices.append((distance, rule, typo))
    if not choices:
        return None
    distance, rule, typo = min(choices)
    return typo, f"{rule};distractor_edit_distance={distance}"


def _sentence_spans(text: str):
    start = 0
    for match in re.finditer(r"[.!?]+(?:[\"'’”)]*)\s+|$", text):
        end = match.end()
        raw_end = match.start() if match.group(0).strip() == "" else end
        sentence_start = start
        while sentence_start < raw_end and text[sentence_start].isspace():
            sentence_start += 1
        sentence_end = raw_end
        while sentence_end > sentence_start and text[sentence_end - 1].isspace():
            sentence_end -= 1
        if sentence_end > sentence_start:
            yield sentence_start, sentence_end, text[sentence_start:sentence_end]
        start = end
    if start < len(text):
        tail_start = start
        while tail_start < len(text) and text[tail_start].isspace():
            tail_start += 1
        tail_end = len(text.rstrip())
        if tail_end > tail_start:
            yield tail_start, tail_end, text[tail_start:tail_end]


def _clean_sentence(sentence: str) -> bool:
    if len(sentence) < 35 or len(sentence) > 700 or len(sentence.split()) < 6:
        return False
    if "\ufffd" in sentence or "\x00" in sentence:
        return False
    if re.match(r"^\s*(?:[*#;|]|[-–—]\s)", sentence):
        return False
    if any(mark in sentence for mark in ("<", ">", "{{", "}}", "[[", "]]", "{|", "|}")):
        return False
    if re.search(r"(?:^|\s)[*#|]\s", sentence):
        return False
    if sentence.count("=") > 1 or sentence.count("|") > 1:
        return False
    if not re.search(r"[.!?][\"'’”)]*$", sentence):
        return False
    return True


def _make_row(pair: dict, article: tuple, db_path: Path, revision: str,
              sentence_start: int, sentence: str, token_match: re.Match,
              gold: str, distractor: str) -> dict | None:
    mutated = _mutation(gold, distractor, pair["words"])
    if mutated is None:
        return None
    typo, mutation_rule = mutated
    source_surface = token_match.group(0)
    if source_surface[:1].isupper():
        typo = typo.capitalize()
    start, end = token_match.start(), token_match.end()
    input_text = sentence[:start] + typo + sentence[end:]
    fields = {
        "split": pair["split"],
        "domain_id": pair["domain"],
        "confusion_set_id": pair["pair_id"],
        "confusion_type": pair["confusion_type"],
        "source_id": f"{db_path.name}:{article[0]}",
        "source_revision": revision,
        "source_locator": f"{db_path}#articles.article_id={article[0]} title={article[1]}",
        "source_text": sentence,
        "source_start": start,
        "source_end": end,
        "question": "What proposition does the sentence express?",
        "input_text": input_text,
        "typo_start": start,
        "typo_end": start + len(typo),
        "gold_token": gold,
        "typo_token": typo,
        "distractor_token": distractor,
        "mutation_rule": mutation_rule,
        "mutation_seed": 0,
        "proposal_candidate": "",
        "candidate_class": "",
        "review_status": "pending",
        "review_note": "",
    }
    fields["example_id"] = "CCV1-" + _sha([fields["source_id"], sentence_start,
                                           pair["pair_id"], start, gold])[:20]
    fields["record_sha256"] = _sha(fields)
    return fields


def main() -> int:
    if not SPEC.is_file():
        raise FileNotFoundError(f"dataset spec not found: {SPEC}")
    pairs = _parse_confusions()
    if not pairs:
        raise RuntimeError("no eligible homophone sets parsed from the locked spec")

    by_db: dict[str, list[dict]] = {}
    for pair in pairs:
        for db_name in DOMAIN_DATABASES[pair["domain"]]:
            by_db.setdefault(db_name, []).append(pair)

    targets: dict[tuple[str, str, str], int] = {}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for pair in pairs:
        grouped.setdefault((pair["domain"], pair["split"]), []).append(pair)
    for group, group_pairs in grouped.items():
        base, remainder = divmod(SPLIT_TARGET_PER_DOMAIN, len(group_pairs))
        for i, pair in enumerate(sorted(group_pairs, key=lambda p: p["pair_id"])):
            targets[(pair["domain"], pair["split"], pair["pair_id"])] = base + (i < remainder)

    reservoirs: dict[tuple[str, str, str], list[tuple[str, dict]]] = {key: [] for key in targets}
    seen_counts = {key: 0 for key in targets}
    randomizers = {key: random.Random(SEED + int(_sha(key)[:8], 16)) for key in targets}
    quota_cap = max(RESERVOIR_PER_PAIR, max(targets.values()) * 8)
    sources = {}

    for db_name, db_pairs in by_db.items():
        path = CORPUS_ROOT / db_name
        if not path.is_file():
            print(f"MISSING_SOURCE {path}", flush=True)
            continue
        stat = path.stat()
        revision = f"{db_name};bytes={stat.st_size};mtime_utc={datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}"
        sources[db_name] = {"path": str(path), "bytes": stat.st_size, "revision": revision}
        domain_pairs: dict[str, list[dict]] = {}
        for pair in db_pairs:
            domain_pairs.setdefault(pair["domain"], []).append(pair)
        compiled = {}
        word_to_pairs = {}
        for domain, rows in domain_pairs.items():
            mapping: dict[str, list[dict]] = {}
            for pair in rows:
                for word in pair["words"]:
                    mapping.setdefault(word, []).append(pair)
            word_to_pairs[domain] = mapping
            alternatives = "|".join(re.escape(word) for word in sorted(mapping, key=lambda s: (-len(s), s)))
            compiled[domain] = re.compile(rf"(?<!\w)(?P<word>{alternatives})(?!\w)", re.IGNORECASE)

        uri = f"file:{path.as_posix()}?mode=ro"
        db = sqlite3.connect(uri, uri=True)
        try:
            cursor = db.execute("SELECT article_id, title, domain, categories, summary FROM articles WHERE summary IS NOT NULL")
            while True:
                batch = cursor.fetchmany(200)
                if not batch:
                    break
                for article in batch:
                    summary = article[4]
                    if not isinstance(summary, str) or not summary:
                        continue
                    for sent_start, sent_end, sentence in _sentence_spans(summary):
                        if not _clean_sentence(sentence):
                            continue
                        for domain, pattern in compiled.items():
                            match = pattern.search(sentence)
                            if match is None:
                                continue
                            word = match.group("word").casefold()
                            for pair in word_to_pairs[domain].get(word, ()):
                                if pair["split"] not in {"calibration", "held_out"}:
                                    continue
                                other_words = [candidate for candidate in pair["words"] if candidate != word]
                                if not other_words:
                                    continue
                                distractor = other_words[int(_sha([article[0], sent_start, pair["pair_id"]])[:4], 16) % len(other_words)]
                                row = _make_row(pair, article, path, revision, sent_start,
                                                sentence, match, word, distractor)
                                if row is None:
                                    continue
                                key = (pair["domain"], pair["split"], pair["pair_id"])
                                priority = _sha([SEED, key, row["source_id"], sent_start])
                                seen_counts[key] += 1
                                reservoir = reservoirs[key]
                                if len(reservoir) < quota_cap:
                                    reservoir.append((priority, row))
                                else:
                                    rng = randomizers[key]
                                    index = rng.randrange(seen_counts[key])
                                    if index < quota_cap:
                                        reservoir[index] = (priority, row)
        finally:
            db.close()
        print(f"SCANNED {db_name}", flush=True)

    selected = []
    globally_seen = set()
    group_results = {}
    for group, group_pairs in sorted(grouped.items()):
        domain, split = group
        target = SPLIT_TARGET_PER_DOMAIN
        candidates_by_pair = {}
        for pair in sorted(group_pairs, key=lambda p: p["pair_id"]):
            key = (domain, split, pair["pair_id"])
            candidates_by_pair[pair["pair_id"]] = [row for _, row in
                sorted(reservoirs[key], key=lambda item: item[0])]
        indexes = {pair_id: 0 for pair_id in candidates_by_pair}
        group_rows = []
        while len(group_rows) < target:
            moved = False
            for pair_id, candidates in candidates_by_pair.items():
                if len(group_rows) >= target:
                    break
                while indexes[pair_id] < len(candidates):
                    row = candidates[indexes[pair_id]]
                    indexes[pair_id] += 1
                    source_key = (row["source_id"], row["source_start"], row["source_end"])
                    if source_key in globally_seen:
                        continue
                    globally_seen.add(source_key)
                    group_rows.append(row)
                    moved = True
                    break
            if not moved:
                break
        selected.extend(group_rows)
        group_results[f"{domain}/{split}"] = {
            "target": target, "selected": len(group_rows),
            "shortfall": target - len(group_rows),
            "pairs": {pair_id: len(candidates_by_pair[pair_id]) for pair_id in candidates_by_pair},
        }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = HERE / "learning" / "contextual_correction_evals"
    csv_path = out_dir / f"raw_candidates_v1_{stamp}.csv"
    jsonl_path = out_dir / f"raw_candidates_v1_{stamp}.jsonl"
    receipt_path = out_dir / f"raw_candidates_v1_{stamp}_receipt.json"
    selected.sort(key=lambda row: (row["domain_id"], row["split"], row["confusion_set_id"], row["source_id"], row["source_start"]))

    with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    receipt = {
        "schema": "viv-contextual-correction-raw-candidates-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "seed": SEED,
        "selection": "read-only corpus scan; deterministic reservoir sample; pending human review",
        "source_databases": sources,
        "target_total": 600,
        "selected_total": len(selected),
        "group_counts": group_results,
        "files": {"csv": str(csv_path), "jsonl": str(jsonl_path)},
    }
    receipt["receipt_sha256"] = _sha(receipt)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"csv": str(csv_path), "jsonl": str(jsonl_path),
                      "receipt": str(receipt_path), "selected_total": len(selected),
                      "group_counts": group_results}, ensure_ascii=False, indent=2), flush=True)
    return 0 if len(selected) == 600 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"EXTRACTION_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
