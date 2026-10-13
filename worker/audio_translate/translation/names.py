"""Per-job person-name glossary with Sino-Vietnamese (Hán-Việt) readings.

Hy-MT2 transliterates Chinese names inconsistently (宋轩 -> Song Xuan / Sông Xuân /
Sung Huan) and cannot produce Hán-Việt on request, but it follows a terminology
list reliably. Names are detected from the transcript once per job and stored in
`working/name-glossary.json`, which users may edit before Continue/Reprocess.

Readings come from curated tables of common surnames and given-name characters.
Unihan `kVietnamese` mixes Nôm readings (徐 -> chờ, 强 -> càng), so it is not used
directly. A name with any character outside the tables is skipped instead of guessed.

Asset 2 (Hán-Việt names): the tables live in the encrypted vault (`names`), loaded through the
security service, with a plaintext dev fallback (`worker/config/names.json`).
"""
from collections import Counter
from functools import lru_cache

from audio_translate.core.storage import ROOT


@lru_cache(maxsize=1)
def _tables():
    from audio_translate.core import vault
    data = vault.load_json('names', ROOT / 'worker' / 'config' / 'names.json')
    if data.get('version') != 1 or not all(isinstance(data.get(k), dict) for k in ('compound_surnames', 'surnames', 'given')) or not isinstance(data.get('ambiguous'), list):
        raise ValueError('Invalid names table')
    return {'compound': data['compound_surnames'], 'surnames': data['surnames'],
            'given': data['given'], 'ambiguous': set(data['ambiguous'])}


def reading(name):
    """Hán-Việt for a full name, or None when any character is uncertain."""
    tables = _tables()
    compound_surnames, surnames, given_table = tables['compound'], tables['surnames'], tables['given']
    for compound, value in compound_surnames.items():
        if name.startswith(compound) and len(name) > len(compound):
            given = [given_table.get(ch) for ch in name[len(compound):]]
            return None if None in given else ' '.join([value, *given])
    if name[0] not in surnames or len(name) < 2:
        return None
    given = [given_table.get(ch) for ch in name[1:]]
    return None if None in given else ' '.join([surnames[name[0]], *given])


def given_reading(given):
    given_table = _tables()['given']
    parts = [given_table.get(ch) for ch in given]
    return None if None in parts else ' '.join(parts)


def detect(rows, minimum=3, limit=40):
    """Glossary entries [{source, target, count, auto}] for frequent person names."""
    import jieba
    import jieba.posseg
    jieba.setLogLevel(60)
    tables = _tables()
    surnames, compound_surnames, ambiguous = tables['surnames'], tables['compound'], tables['ambiguous']
    text = '\n'.join(rows)
    tags = jieba.posseg.dt.word_tag_tab

    def is_word(gram):
        # A dictionary word that is not tagged as a person name (张开, 高兴, 金钱 ...).
        return gram in tags and not tags[gram].startswith('nr')

    tagged = Counter(word for row in rows for word, flag in jieba.posseg.cut(row)
                     if flag == 'nr' and 2 <= len(word) <= 4)
    grams = Counter()
    for size in (2, 3, 4):
        for start in range(len(text) - size + 1):
            gram = text[start:start + size]
            if '\n' not in gram and (gram[0] in surnames or gram[:2] in compound_surnames):
                grams[gram] += 1
    candidates = {}
    for gram, count in grams.items():
        if count < minimum or is_word(gram) or reading(gram) is None:
            continue
        if gram[:2] not in compound_surnames and (len(gram) == 4 or gram[0] in ambiguous):
            continue  # rarely a name / needs the jieba name tag below
        candidates[gram] = count
    for word, count in tagged.items():
        if reading(word) and grams[word] >= 2:
            candidates[word] = max(candidates.get(word, 0), grams[word])
    # Prefer the longest form: drop 张倩 when 张倩倩 accounts for nearly all its uses.
    for gram in sorted(candidates, key=len):
        longer = [g for g in candidates if len(g) > len(gram) and g.startswith(gram)]
        if longer and grams[gram] - sum(grams[g] for g in longer) < minimum:
            candidates.pop(gram, None)
    # A 3-character gram dominated by its 2-character prefix is the name plus a word (李强家).
    for gram in [g for g in candidates if len(g) == 3 and g[:2] in candidates]:
        if grams[gram[:2]] >= 4 * grams[gram]:
            candidates.pop(gram)
    # Drop a shorter candidate that only appears inside longer ones (倩倩 inside 张倩倩 is kept
    # as an alias below when it also stands alone).
    names = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))[:limit]
    entries = [dict(source=name, target=reading(name), count=count, auto=True) for name, count in names]
    # Given-name aliases (倩倩 for 张倩倩) when they also occur without the surname.
    for name, _ in names:
        surname = 2 if name[:2] in compound_surnames else 1
        given = name[surname:]
        alone = text.count(given) - text.count(name)
        if len(given) >= 2 and alone >= 2 and not is_word(given) and given_reading(given):
            if all(entry['source'] != given for entry in entries):
                entries.append(dict(source=given, target=given_reading(given), count=alone, auto=True))
    return sorted(entries, key=lambda entry: (-len(entry['source']), -entry['count']))
