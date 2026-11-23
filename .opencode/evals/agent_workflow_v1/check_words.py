from count_words import count_words

cases = [
    ('', 0),
    ('one', 1),
    ('two words', 2),
    ('  many\twords\nacross lines  ', 4),
]
for text, expected in cases:
    actual = count_words(text)
    assert actual == expected, (repr(text), expected, actual)
print('PASS: whitespace word count')
