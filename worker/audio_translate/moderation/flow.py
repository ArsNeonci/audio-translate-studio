"""Sentence-flow cleanup for subtitle-row translations.

Rows are translated as fragments, so a row continuing the previous one still starts with
a capital ("tôi bị đẩy xuống sông, Tôi không biết bơi, Cuối cùng..."). The first word is
lowercased only when the previous row ended mid-sentence and the word is demonstrably
common in this job's own text: its lowercase form occurs inside rows at least
`COMMON_MIN` times, so names, brands and "Tôi"-like sentence starters are handled
without any word list.
"""
from collections import Counter
import re

COMMON_MIN = 5
WORD = re.compile(r'[^\W\d_]+')
CONTINUES = (',', ';', '、', '，')


class Flow:
    def __init__(self, texts, names=()):
        counts = Counter()
        for text in texts:
            for word in WORD.findall(text)[1:]:
                if word.islower(): counts[word] += 1
        self.common = {word for word, count in counts.items() if count >= COMMON_MIN}
        self.names = {word for name in names for word in WORD.findall(name)}

    def apply(self, previous, text):
        if not previous or not previous.rstrip().endswith(CONTINUES): return text
        first = WORD.match(text)
        if not first: return text
        word = first.group(0)
        if not word[0].isupper() or word in self.names or word.lower() not in self.common: return text
        second = WORD.match(text, first.end() + 1) if text[first.end():first.end() + 1] == ' ' else None
        # "Lý Cường", "Dà Rú": a capitalized pair is a proper noun, not a sentence start.
        if second and second.group(0)[0].isupper(): return text
        return word[0].lower() + text[1:]
