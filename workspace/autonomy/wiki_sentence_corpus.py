"""Bounded Wikipedia lead-sentence pilot with aligned, deterministic views."""
import hashlib
import re
from pathlib import Path
import mwparserfromhell

REMOVED_CONJUNCTIONS = frozenset(('and', 'or', 'but', 'nor', 'yet', 'so', 'because', 'although', 'while', 'whereas', 'unless', 'if'))


def reduce_sentence(text):
    words = list(re.finditer(r"\b[^\W\d_]+\b", text, re.UNICODE))
    removed = [{'text': m.group(), 'start': m.start(), 'end': m.end()}
               for m in words if m.group().lower() in REMOVED_CONJUNCTIONS]
    result = text
    for item in reversed(removed):
        result = result[:item['start']] + result[item['end']:]
    return re.sub(r'\s+', ' ', result).strip(), removed


def lead_sentences(raw):
    body = raw.split('\n', 1)[1] if raw.startswith('Title:') else raw
    if re.match(r'\s*#redirect\b', body, re.I):
        return []
    body = re.split(r'={2,}[^=]+={2,}', body, maxsplit=1)[0]
    code = mwparserfromhell.parse(body)
    # File captions, citations, templates and math are not article prose.
    for node in list(code.filter_wikilinks(recursive=False)):
        if str(node.title).lower().startswith(('file:', 'image:', 'category:')):
            code.remove(node)
    for node in list(code.filter_tags(recursive=False)):
        if str(node.tag).lower() in ('ref', 'math', 'gallery', 'table'):
            code.remove(node)
    text = re.sub(r'\s+', ' ', code.strip_code(normalize=True, collapse=True)).strip()
    result = []
    for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])', text):
        # Conservative pilot rejects suspicious leftovers instead of guessing.
        if (45 <= len(sentence) <= 240 and sentence[-1:] in '.!?'
                and not any(mark in sentence for mark in ('{{', '}}', '<', '>', '[[', ']]', '|'))
                and len(sentence.split()) >= 7):
            result.append(sentence)
    return result[:6]


def prepare(root, article_limit=80, scan_limit=1500):
    rows, seen, sources = [], set(), []
    scanned = 0
    for batch in sorted(Path(root).glob('batch_*')):
        for path in sorted(batch.glob('*.txt')):
            scanned += 1
            if scanned > scan_limit or len(sources) >= article_limit:
                break
            if path.stat().st_size > 2_000_000:
                continue
            raw = path.read_text(encoding='utf-8', errors='strict')
            sentences = lead_sentences(raw)
            if not sentences:
                continue
            canonical = hashlib.sha256('\n'.join(sentences).encode()).hexdigest()
            if canonical in seen:
                continue
            seen.add(canonical)
            bucket = int(canonical[:8], 16) % 10
            split = 'validation' if bucket == 0 else 'test' if bucket == 1 else 'train'
            source = {'path': str(path), 'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                      'article_id': canonical, 'title': raw.splitlines()[0], 'split': split}
            sources.append(source)
            for index, sentence in enumerate(sentences):
                reduced, removed = reduce_sentence(sentence)
                rows.append({'article_id': canonical, 'split': split, 'sentence_index': index,
                             'original': sentence, 'reduced': reduced, 'removed': removed})
        if scanned > scan_limit or len(sources) >= article_limit:
            break
    # Exclude cross-split identical original or reduced targets.
    groups = {}
    for row in rows:
        for key in ('original', 'reduced'):
            groups.setdefault((key, row[key]), set()).add(row['split'])
    rows = [r for r in rows if all(len(groups[(key, r[key])]) == 1 for key in ('original', 'reduced'))]
    return {'schema': 'wiki_aligned_sentence_pilot_v1', 'sources': sources, 'rows': rows,
            'scanned': scanned, 'reduction_words': sorted(REMOVED_CONJUNCTIONS),
            'scope': 'Bounded lead sentences; conjunction deletion records are alignment, not proof of preserved meaning.'}
