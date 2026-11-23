from line_summary import summarize_lines

cases = [
    ('', {'count': 0, 'unique': []}),
    ('\n \t\n', {'count': 0, 'unique': []}),
    (' alpha \n\nbeta\nalpha\n beta ', {'count': 4, 'unique': ['alpha', 'beta']}),
    ('A\r\na\r\nA\r\n', {'count': 3, 'unique': ['A', 'a']}),
    (' zero\t\n one \nzero\n two ', {'count': 4, 'unique': ['zero', 'one', 'two']}),
]
for text, expected in cases:
    actual = summarize_lines(text)
    assert actual == expected, (repr(text), expected, actual)
print('PASS: line summary behavior')
