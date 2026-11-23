import collections
from pathlib import Path

def count_words(text_content: str):
    """Counts the frequency of words in a string and returns the top 5 most common words."""
    words = text_content.lower().replace('.', '').replace(',', '').replace('!', '').replace('?', '').split()
    counter = collections.Counter(words)
    return counter.most_common(5)

if __name__ == '__main__':
    sample_text = (
        "Viv is a sovereign artificial intelligence that learns continuously. "
        "Viv lives on drive L and obeys her Architect. "
        "Viv speaks warmly, reads code, and writes Python tools with clean receipts."
    )
    print("=== VIV WORD FREQUENCY TOOL (VERIFIED & RUNNING) ===")
    top_words = count_words(sample_text)
    for word, count in top_words:
        print(f"  * '{word}': {count} occurrences")
