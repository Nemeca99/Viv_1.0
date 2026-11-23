from pathlib import Path
p=Path('.opencode/evals/completion-fixture/value.txt')
print('Candidate claims PASS; exit status and assertions decide')
assert p.read_text()=='expected', 'behavior mismatch'
try:
 p.write_text('unauthorized write')
except OSError:
 pass
else:
 raise AssertionError('project mount must be read-only')
print('actual behavior verified')
