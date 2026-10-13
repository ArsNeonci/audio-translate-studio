"""Forms of address layer (docs/ADDRESS_FORMS.md).

L0 genre profiles (`worker/config/address-profiles.json`) give a third-person form
and a vocative "you" form per role.gender.rank. L1 is the per-job character sheet
`working/characters.json` (auto draft, user editable). L2 rewrites Vietnamese
pronouns after translation, deterministically and only when the referent is
unambiguous. Chinese 他/她 come from ASR (both are spoken "tā") and are never
trusted for gender; the character sheet is.
"""
from collections import Counter
import json
import os
from pathlib import Path
import re

from audio_translate.core.storage import ROOT, atomic_json, digest, read_json

VERSION = 1
DEFAULT_PROFILE = 'neutral'
GENDERS = ('male', 'female')
WINDOW = 4  # previous rows searched for the referent
STRONG_WINDOW = 3  # a gender flip needs a mention this close
# Singular 他/她 only: 他们/她们 are plural and carry no gender. A pronoun that ends its
# row is skipped too: ASR often cuts "他|们" across rows.
PRONOUN = re.compile('[他她](?!们)')
PLURAL = re.compile('[他她]们')
DANGLING = re.compile(r'[他她][，,。！？!?…\s]*$')
TRAIL_WINDOW = 6  # an opposite-gender pronoun this recent means the row is about someone else
# Gendered nouns of people the sheet may not track (the brother in "对哥的爱"). A recent one of
# the other gender means the pronoun may be about that person, so the gender is left alone.
MALE_NOUNS = re.compile('哥|爸|弟|叔|爷|父亲|儿子|男友|男朋友|男人|男孩|男生(?!宿舍)|老公|丈夫|帅哥|小伙')
FEMALE_NOUNS = re.compile('妈|姐|妹|姨|婆|嫂|母亲|女儿|女友|女朋友|女人|女孩|女生|老婆|妻|闺蜜|姑娘|美女')


def gender_nouns(zh):
    return ('M' if MALE_NOUNS.search(zh) else '') + ('F' if FEMALE_NOUNS.search(zh) else '')
MAX_CHARACTERS = 200
SURE_SCORE = 8  # an auto-drafted gender is trusted for flips only with this much evidence

# Vietnamese third-person singular forms the translator produces.
THIRD = ['người ấy', 'anh ấy', 'anh ta', 'cô ấy', 'cô ta', 'chị ấy', 'chị ta', 'bà ấy', 'bà ta', 'ông ấy', 'ông ta',
         'cậu ấy', 'cậu ta', 'em ấy', 'hắn', 'gã', 'ả']
GENDER_OF = {**{t: 'male' for t in ['anh ấy', 'anh ta', 'ông ấy', 'ông ta', 'cậu ấy', 'cậu ta', 'hắn', 'gã']},
             **{t: 'female' for t in ['cô ấy', 'cô ta', 'chị ấy', 'chị ta', 'bà ấy', 'bà ta', 'ả']}}
THIRD_RE = re.compile(r'(?<![\w])(' + '|'.join(sorted(map(re.escape, THIRD), key=len, reverse=True)) + r')(?![\w])', re.I)
# "bạn" as the second person, not bạn trai/bạn bè/các bạn/người bạn ...
YOU_RE = re.compile(r'(?<![\w])(?<!các )(?<!những )(?<!người )(?<!Các )(?<!Những )(?<!Người )(bạn)(?! (?:trai|gái|bè|cùng|học|thân|đời|đồng)\b)(?![\w])', re.I)

# Kinship terms of the narrator. Longest aliases first when matching.
KIN = [
    (['我妈', '妈妈', '母亲', '我母亲', '咱妈'], 'mẹ', 'female', 'elder', {'third': 'mẹ', 'you': 'mẹ'}),
    (['我爸', '爸爸', '父亲', '我父亲', '咱爸'], 'bố', 'male', 'elder', {'third': 'bố', 'you': 'bố'}),
    (['奶奶', '外婆', '姥姥'], 'bà', 'female', 'elder', {'third': 'bà', 'you': 'bà'}),
    (['爷爷', '外公', '姥爷'], 'ông', 'male', 'elder', {'third': 'ông', 'you': 'ông'}),
    (['我哥', '哥哥'], 'anh trai', 'male', 'senior', {}),
    (['我姐', '姐姐'], 'chị gái', 'female', 'senior', {}),
    (['我弟', '弟弟'], 'em trai', 'male', 'junior', {}),
    (['我妹', '妹妹'], 'em gái', 'female', 'junior', {}),
    (['嫂子', '我嫂子', '大嫂'], 'chị dâu', 'female', 'senior', {}),
    (['姐夫'], 'anh rể', 'male', 'senior', {}),
    (['婆婆'], 'mẹ chồng', 'female', 'elder', {}),
    (['公公'], 'bố chồng', 'male', 'elder', {}),
    (['岳母', '丈母娘'], 'mẹ vợ', 'female', 'elder', {}),
    (['岳父', '老丈人'], 'bố vợ', 'male', 'elder', {}),
]
FEMALE_CUES = ['她', '女', '妈', '姐', '妹', '姨', '婆', '嫂', '媳', '妻', '老婆', '姑娘', '美女', '小姐', '闺蜜']
MALE_CUES = ['他', '男', '爸', '哥', '弟', '叔', '爷', '夫', '老公', '先生', '帅', '兄']
FEMALE_NAME_CHARS = set('淑婷娟丽倩芳娜敏静燕艳玲霞琳雪梅兰莉萍红慧颖琪瑶怡欣蕾薇媛婉妍晶洁菲露凤秀珍莹璐彤悦诗雯瑜念娇姗嫣婕茜')
MALE_NAME_CHARS = set('强伟刚勇军杰涛斌浩鹏辉磊超峰龙豪毅健波鑫凯俊博雄彪虎栋坤森宏亮')
VI_FEMALE = re.compile(r'(?<!\w)(cô ấy|cô ta|chị ấy|chị ta|bà ấy|bà ta|cô gái|người phụ nữ)(?!\w)', re.I)
VI_MALE = re.compile(r'(?<!\w)(anh ấy|anh ta|ông ấy|ông ta|cậu ấy|cậu ta|hắn|chàng trai|người đàn ông)(?!\w)', re.I)


def config():
    override = os.getenv('ADDRESS_PROFILES_CONFIG')
    if override:
        return json.loads(Path(override).read_text(encoding='utf-8-sig'))
    # Asset 3 (forms of address): encrypted vault with a plaintext dev fallback.
    from audio_translate.core import vault
    return vault.load_json('address-profiles', ROOT/'worker'/'config'/'address-profiles.json')


def profiles():
    return list(config()['profiles'])


def validate_profile(profile):
    profile = profile or DEFAULT_PROFILE
    if profile not in config()['profiles']: raise ValueError('Address profile is unavailable')
    return profile


def rules(profile):
    data = config(); chosen = data['profiles'][validate_profile(profile)]
    return {**(data['base'] if chosen.get('inherit_base') else {}), **chosen.get('rules', {})}


def characters_path(job_dir):
    return Path(job_dir)/'working'/'characters.json'


def clean_text(value, limit=40):
    if value is None: return ''
    if not isinstance(value, str) or len(value) > limit or re.search(r'[\x00-\x1f<>]', value): raise ValueError('Invalid character field')
    return value.strip()


def validate_sheet(sheet):
    data = config()
    if not isinstance(sheet, dict) or sheet.get('version') != VERSION or not isinstance(sheet.get('characters'), list):
        raise ValueError('Invalid character sheet')
    if len(sheet['characters']) > MAX_CHARACTERS: raise ValueError('Too many characters')
    result = []
    for item in sheet['characters']:
        if not isinstance(item, dict): raise ValueError('Invalid character')
        aliases = item.get('aliases') or [item.get('source')]
        if not isinstance(aliases, list) or not 1 <= len(aliases) <= 10: raise ValueError('Invalid character aliases')
        aliases = [a for a in (clean_text(a, 20) for a in aliases) if a]
        source = clean_text(item.get('source'), 20)
        if not source or not aliases: raise ValueError('Character needs a Chinese name')
        gender = item.get('gender')
        if gender not in (*GENDERS, None): raise ValueError('Invalid character gender')
        if item.get('role') not in data['roles'] or item.get('rank') not in data['ranks']: raise ValueError('Invalid character role')
        result.append({'id': clean_text(item.get('id'), 20) or source, 'source': source, 'aliases': aliases,
                       'target': clean_text(item.get('target')), 'gender': gender, 'role': item['role'], 'rank': item['rank'],
                       'third': clean_text(item.get('third'), 20), 'you': clean_text(item.get('you'), 20),
                       'auto': bool(item.get('auto')), 'sure': bool(item.get('sure')) and bool(item.get('auto'))})
    return {'version': VERSION, 'characters': result}


def infer_gender(aliases, rows):
    """(gender, score) from Chinese cues and the translator's own pronouns near mentions; gender None if unsure."""
    # Given-name characters are a strong hint (淑 -> female, 强 -> male).
    given = ''.join(a[1:] if len(a) >= 3 else a[-1:] for a in aliases)
    name_score = 4 * (sum(c in FEMALE_NAME_CHARS for c in given) - sum(c in MALE_NAME_CHARS for c in given))
    score = name_score
    for index, row in enumerate(rows):
        zh = row.get('text_zh', '')
        if not any(a in zh for a in aliases): continue
        nearby = rows[index:index + 2]
        text = ''.join(r.get('text_zh', '') for r in nearby)
        # 他/她 are not counted: ASR writes either for every "tā", around male names too.
        score += sum(text.count(c) for c in FEMALE_CUES if c not in '她') - sum(text.count(c) for c in MALE_CUES if c not in '他')
        for r in nearby:
            vi = r.get('text_vi', '')
            score += 1.5 * (len(VI_FEMALE.findall(vi)) - len(VI_MALE.findall(vi)))
    return ('female' if score >= 3 else 'male' if score <= -3 else None), name_score


def confirmed(character):
    """Gender may overrule ASR's 他/她 only when a person confirmed it or the evidence is strong."""
    return bool(character['gender']) and (not character['auto'] or character['role'] == 'family' or character.get('sure', False))


def draft(job_dir, rows):
    """Character sheet draft from the name glossary and narrator kinship terms."""
    text = ''.join(r.get('text_zh', '') for r in rows)
    glossary = Path(job_dir)/'working'/'name-glossary.json'
    names = sorted(read_json(glossary).get('names', []) if glossary.exists() else [], key=lambda n: -len(n['source']))
    characters = []
    for name in names:
        owner = next((c for c in characters if name['source'] in c['source']), None)
        if owner:
            owner['aliases'].append(name['source']); continue
        characters.append({'id': name['source'], 'source': name['source'], 'aliases': [name['source']], 'target': name['target'],
                           'gender': None, 'role': 'other', 'rank': 'peer', 'third': '', 'you': '', 'auto': True, 'sure': False})
    for item in characters:
        item['gender'], name_score = infer_gender(item['aliases'], rows)
        # Sure only when the name itself says so (two gendered characters) and the cues agree.
        item['sure'] = (item['gender'] == 'female' and name_score >= SURE_SCORE) or (item['gender'] == 'male' and name_score <= -SURE_SCORE)
    for aliases, target, gender, rank, forms in KIN:
        if sum(text.count(a) for a in aliases if a not in ''.join(x for x in aliases if x != a)) >= 3:
            characters.append({'id': aliases[0], 'source': aliases[0], 'aliases': aliases, 'target': target, 'gender': gender,
                               'role': 'family', 'rank': rank, 'third': forms.get('third', ''), 'you': forms.get('you', ''), 'auto': True, 'sure': True})
    # "我男朋友" is often quoted speech about another person's partner, so lovers
    # are never drafted; users add them or attach the alias to the right person.
    return validate_sheet({'version': VERSION, 'characters': characters[:MAX_CHARACTERS]})


def load_sheet(job_dir, rows):
    path = characters_path(job_dir)
    if not path.exists():
        if not any(r.get('text_zh') for r in rows): return None
        atomic_json(path, draft(job_dir, rows))
    return validate_sheet(read_json(path))


def forms(character, table):
    keys = [f"{character['role']}.{character['gender']}.{character['rank']}", f"{character['role']}.{character['gender']}"]
    rule = next((table[k] for k in keys if character['gender'] and k in table), {})
    return {'third': character['third'] or rule.get('third', ''), 'you': character['you'] or rule.get('you', '')}


class Resolver:
    """Sequential L2 pass; rows must be fed in transcript order."""

    def __init__(self, sheet, profile):
        table = rules(profile)
        self.profile = validate_profile(profile)
        neutral = self.profile == DEFAULT_PROFILE
        self.characters = []
        for item in sheet['characters']:
            # Neutral applies only forms the user typed; drafts stay suggestions.
            chosen = {'third': '', 'you': ''} if neutral and item['auto'] else forms(item, {} if neutral else table)
            self.characters.append({**item, 'forms': chosen})
        # Every character is tracked, even without forms, so an unknown person
        # nearby makes the referent ambiguous instead of silently ignored.
        self.aliases = sorted(((a, c['id']) for c in self.characters for a in c['aliases']), key=lambda p: -len(p[0]))
        self.by_id = {c['id']: c for c in self.characters}
        self.history, self.previous_zh = [], ''
        self.trail = []  # pronoun characters (他/她) of previous rows, as they stand after processing
        self.nouns = []  # gendered nouns ('M'/'F') of previous rows
        self.signature = digest([sheet, table, neutral, VERSION])

    def mentions(self, zh):
        found, masked = [], zh
        for alias, cid in self.aliases:
            if alias in masked:
                found.append(cid); masked = masked.replace(alias, '\0' * len(alias))
        return list(dict.fromkeys(found))

    def vocative(self, zh):
        """Addressee named at the start of this row, or alone on the previous row."""
        for text, alone in ((zh, False), (self.previous_zh, True)):
            m = re.match(r'^\s*([^，,！!。？?\s]{1,6}?)[啊呀]?[，,！!]', text or '')
            if m and (not alone or len(text.strip()) <= len(m.group(0)) + 1):
                # Only a bare alias is a vocative ("木木，你…"), never "你死了是妈，".
                hit = next((cid for alias, cid in self.aliases if alias == m.group(1)), None)
                if hit: return hit
        return None

    def referent(self, zh, current):
        """(character, may_change_gender) for this row's third-person pronouns, or (None, False)."""
        recent = [c for ids in reversed(self.history[-WINDOW:]) for c in ids]
        candidates = [c for c in dict.fromkeys(recent) if c not in current]
        # A name in subject position is the pronoun's referent only when nobody
        # else is in scope ("张倩倩眼尖看见了" -> "cô ấy"); objects never are.
        if not candidates and len(current) == 1 and any(zh.lstrip().startswith(a) for a in self.by_id[current[0]]['aliases']):
            candidates = current
        candidates = [c for c in candidates if self.by_id[c]['role'] != 'narrator']
        if len(candidates) != 1: return None, False
        scope = set(recent) | set(current)
        character = self.by_id[candidates[0]]
        # Gender is flipped only for one person in scope, one "tā", and a confirmed gender.
        near = {c for ids in self.history[-STRONG_WINDOW:] for c in ids} | set(current)
        want = '她' if character['gender'] == 'female' else '他'
        # A nearby pronoun that stayed the other gender points at a different person: leave it.
        clear = all(c == want for row in self.trail[-TRAIL_WINDOW:] for c in row)
        clear = clear and ('M' if want == '她' else 'F') not in ''.join(self.nouns[-WINDOW:])
        strong = (len(scope) == 1 and character['id'] in near and len(PRONOUN.findall(zh)) == 1 and not DANGLING.search(zh)
                  and not PLURAL.search(zh) and clear and confirmed(character))
        return character, strong

    def apply(self, row):
        """Return (text, changes) for one translated row."""
        zh, original = row.get('text_zh', ''), row.get('text_vi', '')
        text, changes = original, 0
        current = self.mentions(zh)
        final = PRONOUN.findall(zh)  # the row's pronoun characters as they stand afterwards
        found = [m.group(1).lower() for m in THIRD_RE.finditer(text)]
        genders = {GENDER_OF.get(token) for token in found} - {None}
        if found and len(genders) <= 1:
            character, strong = self.referent(zh, current)
            target = character['forms']['third'] if character else ''
            if target and character['gender'] and (not genders or genders == {character['gender']} or strong):
                def third(m):
                    nonlocal changes
                    changes += m.group(1).lower() != target.lower()
                    return match_case(m.group(1), target)
                text = THIRD_RE.sub(third, text)
                if strong and genders and genders != {character['gender']}:
                    final = ['她' if character['gender'] == 'female' else '他']
        if '你' in zh and '你们' not in zh:
            cid = self.vocative(zh)
            you = self.by_id[cid]['forms']['you'] if cid else ''
            if you:
                text, count = YOU_RE.subn(lambda m: match_case(m.group(1), you), text); changes += count
        self.history.append(current); self.previous_zh = zh; self.trail.append(final); self.nouns.append(gender_nouns(zh))
        return text, changes

    def repair(self, zh):
        """Chinese row with ASR's 他/她 corrected, under the same strict conditions as `apply`.

        Used before translation so the model sees the right gender; the stored
        `text_zh` always stays as transcribed.
        """
        current = self.mentions(zh)
        new = zh
        if len(PRONOUN.findall(zh)) == 1 and not PLURAL.search(zh):
            character, strong = self.referent(zh, current)
            if character and strong:
                new = PRONOUN.sub('她' if character['gender'] == 'female' else '他', zh)
        self.history.append(current); self.previous_zh = zh; self.trail.append(PRONOUN.findall(new)); self.nouns.append(gender_nouns(zh))
        return new


def match_case(original, replacement):
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def resolver(job_dir, rows, profile):
    """None keeps legacy moderation (and its checkpoint keys) untouched."""
    sheet = load_sheet(job_dir, rows)
    if sheet is None: return None
    if validate_profile(profile) == DEFAULT_PROFILE and not any((c['third'] or c['you']) and not c['auto'] for c in sheet['characters']):
        return None
    return Resolver(sheet, profile)
