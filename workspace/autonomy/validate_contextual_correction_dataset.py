"""Validate a reviewed contextual-correction CSV without touching Viv state."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


FIELDS = [
    "example_id", "split", "domain_id", "confusion_set_id", "confusion_type",
    "source_id", "source_revision", "source_locator", "source_text",
    "source_start", "source_end", "question", "input_text", "typo_start",
    "typo_end", "gold_token", "typo_token", "distractor_token", "mutation_rule",
    "mutation_seed", "proposal_candidate", "candidate_class", "review_status",
    "review_note", "record_sha256",
]
DOMAINS = {"geometry", "geography", "finance", "civic", "general"}
SPLITS = {"calibration", "held_out"}
CONFUSION_TYPES = {"homophone", "near_homophone", "homograph_sense", "other_confusable"}
REVIEW_STATES = {"pending", "verified", "rejected"}
CANDIDATE_CLASSES = {"", "POSITIVE", "HOMOPHONE_NEGATIVE", "OTHER"}


def _sha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate(path: Path, *, allow_pending: bool = False) -> dict:
    errors: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"CSV columns do not match schema: {reader.fieldnames}")
        rows = list(reader)

    seen_ids: set[str] = set()
    seen_sources: set[tuple[str, str, str]] = set()
    confusion_splits: dict[str, str] = {}
    counts: dict[str, int] = {}
    for line, row in enumerate(rows, start=2):
        eid = row.get("example_id", "")
        def fail(code: str, detail: str) -> None:
            errors.append({"line": str(line), "example_id": eid, "code": code, "detail": detail})

        if eid in seen_ids:
            fail("DUPLICATE_EXAMPLE_ID", eid)
        seen_ids.add(eid)
        if row["split"] not in SPLITS:
            fail("SPLIT_INVALID", row["split"])
        if row["domain_id"] not in DOMAINS:
            fail("DOMAIN_INVALID", row["domain_id"])
        if row["confusion_type"] not in CONFUSION_TYPES:
            fail("CONFUSION_TYPE_INVALID", row["confusion_type"])
        if row["review_status"] not in REVIEW_STATES:
            fail("REVIEW_STATUS_INVALID", row["review_status"])
        if not allow_pending and row["review_status"] != "verified":
            fail("ROW_NOT_VERIFIED", row["review_status"])
        if not row["review_note"].strip():
            fail("REVIEW_NOTE_MISSING", "verified rows require an approval note")
        if row["candidate_class"] not in CANDIDATE_CLASSES:
            fail("CANDIDATE_CLASS_INVALID", row["candidate_class"])

        try:
            start, end = int(row["source_start"]), int(row["source_end"])
            typo_start, typo_end = int(row["typo_start"]), int(row["typo_end"])
            seed = int(row["mutation_seed"])
            if not (0 <= start < end <= len(row["source_text"])):
                fail("SOURCE_OFFSETS_INVALID", f"{start}:{end}")
            elif row["source_text"][start:end].casefold() != row["gold_token"].casefold():
                fail("GOLD_SPAN_MISMATCH", row["source_text"][start:end])
            if not (0 <= typo_start < typo_end <= len(row["input_text"])):
                fail("TYPO_OFFSETS_INVALID", f"{typo_start}:{typo_end}")
            elif row["input_text"][typo_start:typo_end] != row["typo_token"]:
                fail("TYPO_SPAN_MISMATCH", row["input_text"][typo_start:typo_end])
            if start != typo_start or row["input_text"] != (
                row["source_text"][:start] + row["typo_token"] + row["source_text"][end:]
            ):
                fail("MUTATION_RECONSTRUCTION_FAILED", "input is not source with the stated token mutation")
            _ = seed
        except (TypeError, ValueError) as exc:
            fail("OFFSET_OR_SEED_NOT_INTEGER", str(exc))

        hash_fields = {key: row[key] for key in FIELDS if key != "record_sha256"}
        for numeric_key in ("source_start", "source_end", "typo_start", "typo_end", "mutation_seed"):
            try:
                hash_fields[numeric_key] = int(hash_fields[numeric_key])
            except (TypeError, ValueError):
                pass
        if _sha(hash_fields) != row["record_sha256"]:
            fail("RECORD_HASH_MISMATCH", "canonical row hash differs")

        confusion = row["confusion_set_id"]
        old_split = confusion_splits.setdefault(confusion, row["split"])
        if old_split != row["split"]:
            fail("CONFUSION_SET_SPLIT_LEAK", f"{confusion}: {old_split}/{row['split']}")
        src_key = (row["source_id"], row["source_start"], row["source_end"])
        if src_key in seen_sources:
            fail("DUPLICATE_SOURCE_SPAN", repr(src_key))
        seen_sources.add(src_key)
        key = f"{row['split']}/{row['domain_id']}"
        counts[key] = counts.get(key, 0) + 1

    expected_keys = {f"{split}/{domain}" for split in SPLITS for domain in DOMAINS}
    quota_errors = {key: counts.get(key, 0) for key in sorted(expected_keys) if counts.get(key, 0) != 60}
    return {
        "schema": "contextual_correction_dataset_validation_v1",
        "path": str(path),
        "rows": len(rows),
        "verified_rows": sum(row["review_status"] == "verified" for row in rows),
        "candidate_class_counts": {
            key: sum(row["candidate_class"] == key for row in rows)
            for key in sorted(CANDIDATE_CLASSES) if any(row["candidate_class"] == key for row in rows)
        },
        "split_domain_counts": dict(sorted(counts.items())),
        "quota_mismatches": quota_errors,
        "errors": errors,
        "passed": len(rows) == 600 and not errors and not quota_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    result = validate(args.csv, allow_pending=args.allow_pending)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
