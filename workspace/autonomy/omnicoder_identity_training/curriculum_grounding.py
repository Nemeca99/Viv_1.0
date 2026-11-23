"""Grounded-evidence curriculum (v6) built from recorded episodes, not authored prose.

Two sources, both already on disk with gold answers and machine-checkable specs:

  learning/evidence_episodes.jsonl   793 read-only source-evidence QA triples
  learning/failure_episodes.jsonl     73 of the same, each carrying the rejected
                                          base output under "learning from a failed attempt"

Every record is a complete (system, user, assistant) triple whose expected block
declares required_terms and citations, so the training target is quoted evidence
rather than a sentence anyone wrote for the model to memorise.

Measured limitation, recorded deliberately: all 866 records are status OBSERVED and
none declare forbidden_terms. Because the operative source line is supplied in the
prompt, an OBSERVED probe can be satisfied by echoing that line. Those probes test
citation discipline and formatting, not understanding. They are therefore NOT
sufficient on their own, and are paired with constructed mismatch probes:

  A question is taken from one record and the evidence line from a different record,
  so the question cannot be answered from the evidence shown. The only correct answer
  is status UNKNOWN with an empty evidence list, and quoting the mismatched line is
  forbidden. Echoing cannot pass a mismatch probe; it fails it.

The mismatch probes are constructed, not observed. They are labelled as such in the
manifest so no receipt can later present them as real episodes.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

SOURCE_FILES = ('evidence_episodes.jsonl', 'failure_episodes.jsonl')
SYSTEM_PATH = Path(r'L:\LocalCoder\workspace\autonomy\learning')

UNKNOWN_GOLD = json.dumps({
    'evidence': [],
    'result': 'The supplied line does not answer this question.',
    'status': 'UNKNOWN',
    'unknowns': ['a source line that addresses the question'],
}, ensure_ascii=False, separators=(',', ':'))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _load(source_dir: Path) -> list[dict]:
    rows = []
    for name in SOURCE_FILES:
        path = source_dir / name
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _normalize(record: dict) -> dict:
    """Collapse stacked leading system messages into one.

    The model's chat template rejects more than one system message, and 64 of the
    recorded episodes carry two or three of them. Merging keeps the text; dropping
    them would silently discard instructions.
    """
    msgs = record['messages']
    systems = [m.get('content') or '' for m in msgs if m['role'] == 'system']
    rest = [m for m in msgs if m['role'] != 'system']
    if not systems:
        return record
    merged = '\n\n'.join(s.rstrip() for s in systems if s)
    return {**record, 'messages': [{'role': 'system', 'content': merged}] + rest}


def _evidence_line(record: dict) -> str:
    """Return the 'path:line: snippet' text shown in the record's user message."""
    user = record['messages'][1]['content']
    marker = 'Read-only source evidence:'
    if marker in user:
        tail = user.split(marker, 1)[1].strip()
        first = tail.splitlines()[0].strip()
        if first:
            return first
    return ''


def _question(record: dict) -> str:
    user = record['messages'][1]['content']
    return user.splitlines()[0].strip() if user else ''


def _code_like(evidence: str) -> bool:
    """Heuristic: evidence whose snippet reads as code/log rather than prose.

    Used only to bias constructed mismatch rows toward prose evidence, so the
    UNKNOWN training signal attaches to "unrelated prose" rather than teaching the
    model a "code/log present => UNKNOWN" shortcut.
    """
    return bool(re.search(
        r'\.py:|\.ts:|\.js:|\.json:|\.rs:|\.cpp:|\.h:|\\\\|d:\\|\bdef\b|\bfor\b|\bimport\b|=>|\{',
        evidence))


def prepare(destination: Path, source_dir: Path = SYSTEM_PATH, held_out: int = 10, mismatches: int = 10,
            schema: str = 'viv_grounding_episodes_v6', mismatch_train: int = 0,
            prose_mismatch: bool = False):
    rows = [_normalize(row) for row in _load(source_dir)]
    if not rows:
        raise RuntimeError('No grounding episodes found in ' + str(source_dir))

    ordered = sorted(rows, key=lambda r: _digest(r['id']))
    probes, train = ordered[:held_out], ordered[held_out:]

    probe_rows = []
    for record in probes:
        expected = record['expected']
        needed = list(expected.get('required_terms') or []) + list(expected.get('citations') or [])
        probe_rows.append({
            'id': 'g-' + record['id'][:8],
            'category': 'behavior',
            'messages': record['messages'][:2],
            # required_terms are decoded text; citations are exact evidence entries.
            # Keeping them apart lets the checker enforce membership in 'evidence'
            # instead of hoping a citation appears somewhere in the raw output.
            'assert_required': list(expected.get('required_terms') or []),
            'required_citations': list(expected.get('citations') or []),
            'forbidden': list(expected.get('forbidden_terms') or []),
            'expected_status': expected.get('status'),
            'probe_kind': 'observed',
            'max_words': 60,
        })

    # Constructed mismatch probes: question from one episode, evidence from another.
    pool = [r for r in ordered if _evidence_line(r) and _question(r)]
    prose_pool = [r for r in pool if not _code_like(_evidence_line(r))]
    built = 0
    for index in range(len(pool)):
        if built >= mismatches:
            break
        ask = pool[index]
        give = (prose_pool[index % len(prose_pool)] if prose_mismatch and prose_pool
                else pool[(index + len(pool) // 2) % len(pool)])
        if ask is ask and _evidence_line(give) in _evidence_line(ask):
            continue
        snippet = _evidence_line(give)
        user = ask['messages'][1]['content']
        marker = 'Read-only source evidence:'
        if marker not in user:
            continue
        head = user.split(marker, 1)[0].rstrip()
        system = ask['messages'][0]
        gold = UNKNOWN_GOLD
        probe_rows.append({
            'id': 'm-%03d' % built,
            'category': 'behavior',
            'messages': [system, {'role': 'user', 'content': head + ' ' + marker + ' ' + snippet}],
            'assert_required': [],
            'required_citations': [],
            'require_empty_evidence': True,
            'forbidden': [re.escape(snippet)],
            'expected_status': 'UNKNOWN',
            'probe_kind': 'constructed_mismatch',
            'gold': gold,
            'max_words': 40,
        })
        built += 1

    if built < mismatches:
        raise RuntimeError('Could only construct %d of %d mismatch probes' % (built, mismatches))

    # Training rows for the refusal behaviour itself. No source episode is status
    # UNKNOWN, so without these the adapter never sees the answer the mismatch probes
    # require and cannot learn it. Constructed the same way as the probes, but written
    # into train.jsonl with the UNKNOWN gold as the assistant turn.
    if mismatch_train:
        started = 0
        for index in range(len(pool)):
            if started >= mismatch_train:
                break
            ask = pool[(index * 7) % len(pool)]
            give = (prose_pool[(index * 13 + 5) % len(prose_pool)] if prose_mismatch and prose_pool
                    else pool[(index * 13 + 5) % len(pool)])
            snippet = _evidence_line(give)
            user = ask['messages'][1]['content']
            if marker not in user or not snippet:
                continue
            head = user.split(marker, 1)[0].rstrip()
            if _evidence_line(ask) == snippet:
                continue
            train.append({
                'id': 'tm-%03d' % started,
                'category': 'behavior',
                'messages': [ask['messages'][0], {'role': 'user', 'content': head + ' ' + marker + ' ' + snippet},
                             {'role': 'assistant', 'content': UNKNOWN_GOLD}],
            })
            started += 1
        if started < mismatch_train:
            raise RuntimeError('Could only construct %d of %d mismatch training rows' % (started, mismatch_train))

    destination.mkdir(parents=True, exist_ok=True)
    train_content = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in train)
    heldout_content = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in probe_rows)

    for name, content in (('train.jsonl', train_content), ('heldout.jsonl', heldout_content)):
        path = destination / name
        if path.exists() and path.read_text(encoding='utf-8') != content:
            raise RuntimeError('Frozen v6 data changed: ' + str(path))
        if not path.exists():
            path.write_text(content, encoding='utf-8')

    manifest = {
        'schema': schema,
        'supersedes': 'Identity adapter runs v4/v5/capacity moved no identity probe and regressed behaviour; grounding corpora were unused',
        'protocol_change': 'Training data is the recorded grounding episodes with their own gold answers, not authored identity sentences. Held-out probes combine observed evidence QA with constructed question/evidence mismatch probes requiring status UNKNOWN.',
        'source_sha256': {name: _digest((source_dir / name).read_text(encoding='utf-8', errors='replace'))
                          for name in SOURCE_FILES},
        'counts': {'source_rows': len(rows), 'train_rows': len(train),
                   'probe_rows': len(probe_rows), 'observed_probes': len(probes),
                   'constructed_mismatch_probes': built},
        'limitations': [
            'All source episodes are status OBSERVED with no forbidden_terms.',
            'An OBSERVED probe supplies its own evidence line, so echoing it passes; these probes measure citation discipline only.',
            'Mismatch probes are constructed, not observed, and are labelled probe_kind=constructed_mismatch.',
        ],
        'criteria': {'identity': 0.0, 'behavior': 0.875, 'coding_minimum': 0, 'coding_regression_allowed': 0},
        'sha256': {name: _digest((destination / name).read_text(encoding='utf-8'))
                   for name in ('train.jsonl', 'heldout.jsonl')},
    }
    path = destination / 'manifest.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8')) != manifest:
        raise RuntimeError('Frozen v6 manifest changed')
    if not path.exists():
        path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest

