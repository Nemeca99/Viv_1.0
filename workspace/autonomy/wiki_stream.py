"""Deterministic full-body Wikipedia prose reader; no dataset copy to L:."""
import hashlib
from pathlib import Path
import re
import mwparserfromhell
from autonomy.wiki_sentence_corpus import reduce_sentence


def article_chunks(raw, limit=240):
    body = raw.split('\n', 1)[1] if raw.startswith('Title:') else raw
    if re.match(r'\s*#redirect\b', body, re.I):
        return []
    # The exported corpus sometimes places section headings inside one giant line.
    # Restore boundaries before parsing so heading markup cannot enter targets.
    body = re.sub(r'={2,}\s*[^=\n]+?\s*={2,}', '\n', body)
    code = mwparserfromhell.parse(body)
    for node in list(code.filter_wikilinks(recursive=False)):
        if str(node.title).lower().startswith(('file:', 'image:', 'category:')):
            code.remove(node)
    for node in list(code.filter_tags(recursive=False)):
        if str(node.tag).lower() in ('ref', 'math', 'gallery', 'table', 'syntaxhighlight', 'source'):
            code.remove(node)
    text = code.strip_code(normalize=True, collapse=True)
    chunks = []
    for paragraph in text.splitlines():
        paragraph = re.sub(r'\s+', ' ', paragraph).strip()
        paragraph = re.sub(r'^[*#:;]+\s*', '', paragraph)
        if len(paragraph.split()) < 7 or any(m in paragraph for m in ('{{', '}}', '[[', ']]', '|')):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])', paragraph):
            # Long prose is split at word boundaries, rather than discarded.
            words, part = sentence.split(), ''
            for word in words:
                if len(word) > limit:
                    if part:
                        chunks.append(part)
                        part = ''
                    # Preserve long strings in bounded character spans.
                    chunks.extend(word[i:i + limit] for i in range(0, len(word), limit))
                elif len(part) + len(word) + 1 > limit:
                    chunks.append(part)
                    part = word
                else:
                    part = (part + ' ' + word).strip()
            if part:
                chunks.append(part)
    return [{'original': s, 'reduced': reduce_sentence(s)[0],
             'removed': reduce_sentence(s)[1]} for s in chunks if s.strip()]


def prepare_segment(root, after='', articles=64, scan_limit=4096):
    root = Path(root)
    rows, sources, skipped = [], [], {}
    cursor, scanned, exhausted = after, 0, True
    for batch in sorted(root.glob('batch_*')):
        if after and batch.name < after.split('/')[0]:
            continue
        for path in sorted(batch.glob('*.txt')):
            relative = path.relative_to(root).as_posix()
            if relative <= after:
                continue
            if len(sources) >= articles or scanned >= scan_limit:
                exhausted = False
                break
            cursor, scanned = relative, scanned + 1
            if path.stat().st_size > 8_000_000:
                skipped['oversize'] = skipped.get('oversize', 0) + 1
                continue
            payload = path.read_bytes()
            try:
                raw = payload.decode('utf-8', errors='strict')
            except UnicodeDecodeError:
                skipped['invalid_utf8'] = skipped.get('invalid_utf8', 0) + 1
                continue
            chunks = article_chunks(raw)
            if not chunks:
                skipped['redirect_or_no_prose'] = skipped.get('redirect_or_no_prose', 0) + 1
                continue
            canonical = hashlib.sha256('\n'.join(r['original'] for r in chunks).encode()).hexdigest()
            bucket = int(canonical[:8], 16) % 10
            split = 'validation' if bucket == 0 else 'test' if bucket == 1 else 'train'
            sources.append({'path': relative, 'sha256': hashlib.sha256(payload).hexdigest(),
                            'article_id': canonical, 'split': split, 'chunks': len(chunks)})
            for index, row in enumerate(chunks):
                rows.append(dict(row, article_id=canonical, split=split, chunk_index=index))
        if not exhausted:
            break
    return {'schema': 'wiki_full_prose_segment_v2', 'after': after, 'next_cursor': cursor,
            'scanned': scanned, 'sources': sources, 'rows': rows, 'skipped': skipped,
            'exhausted': exhausted,
            'scope': 'All extracted prose sections; redirects, markup-only and oversize files are counted exclusions.'}
