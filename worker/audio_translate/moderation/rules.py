"""Literal, non-cascading NFC replacements and persistent rule CRUD."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
import uuid

from audio_translate.core.storage import DATA, LockedError, atomic_json, file_lock, read_json

LOCK_MESSAGE = "Replacement rules are locked while moderation is running."


class RuleError(ValueError):
    pass


def normalize(value):
    return unicodedata.normalize("NFC", value)


ROOT = Path(__file__).resolve().parents[3]   # app root: worker/audio_translate/moderation/rules.py


def community_rules():
    """The community list that ships with the app: [{source, replacement}], from the vault (the plaintext file only in development)."""
    from audio_translate.core import vault
    return vault.load_json("community-rules", ROOT / "worker" / "config" / "community-rules.json")


class ReplacementRules:
    def __init__(self, config_dir=None, seed=None):
        self.directory = config_dir or DATA / "config"
        self.path = self.directory / "replacement-rules.json"
        self.lock_path = self.directory / "replacement-rules.lock"
        self.seeded_path = self.directory / "replacement-rules.seeded.json"
        # seed: the loader of the starting list (None = the one shipped with the app, False = no starting list, for tests)
        self.seed = community_rules if seed is None else seed

    def read(self, seed=True):
        if seed and self.seed and not self.seeded_path.exists(): self.seed_once()
        return read_json(self.path) if self.path.exists() else []

    def seed_once(self):
        """Puts the shipped community list in, once per installation: rules the person already has are kept and only missing words are added.
        After that the list is theirs (edit, delete); a deleted word is not put back. Called with the lock held. Nothing is marked done when
        the list cannot be read yet (for example before the licence is active), so the next read tries again."""
        if self.seed is community_rules and os.environ.get("AUDIO_NO_RULE_SEED") == "1": return   # tests and harnesses that start from an empty list
        try:
            shipped = self.seed()
            rules = read_json(self.path) if self.path.exists() else []
            known = {key(rule["source"]) for rule in rules}
            for item in shipped:
                source, replacement = normalize(item["source"]).strip(), normalize(item["replacement"])
                if source and key(source) not in known:
                    rules.append({"id": str(uuid.uuid4()), "source": source, "replacement": replacement}); known.add(key(source))
            atomic_json(self.path, rules)
            atomic_json(self.seeded_path, {"version": 1, "rules": len(shipped)})
        except Exception:
            return

    @contextmanager
    def locked(self):
        try:
            with file_lock(self.lock_path):
                yield
        except LockedError:
            raise LockedError(LOCK_MESSAGE) from None

    def list(self):
        try:
            with self.locked():
                return {"rules": annotate(self.read()), "locked": False}
        except LockedError:
            return {"rules": annotate(self.read(seed=False)), "locked": True}

    def mutate(self, action, payload):
        # Lock covers the read/validate/write transaction. Moderation holds this
        # same OS lock for its entire run, across all Next.js/Python processes.
        with self.locked():
            rules = self.read()
            if action in ("add", "edit"):
                source, replacement = payload.get("source"), payload.get("replacement")
                if not isinstance(source, str) or not source.strip() or not isinstance(replacement, str):
                    raise RuleError("Từ gốc phải có nội dung; từ thay thế phải là chữ (có thể để trống). Mã lỗi: K101.")
                source, replacement = normalize(source), normalize(replacement)
                if len(source) > 1000 or len(replacement) > 10000:
                    raise RuleError("Nội dung quá dài: từ gốc tối đa 1.000 ký tự, từ thay thế tối đa 10.000 ký tự. Mã lỗi: K102.")
                if any(key(r["source"]) == key(source) and r["id"] != payload.get("id") for r in rules):
                    raise RuleError("Từ gốc đã có trong danh sách (không phân biệt chữ hoa/thường). Hãy sửa quy tắc đã có. Mã lỗi: K103.")
            if action == "add":
                rules.append({"id": str(uuid.uuid4()), "source": source, "replacement": replacement})
            elif action in ("edit", "delete"):
                index = next((i for i, rule in enumerate(rules) if rule["id"] == payload.get("id")), None)
                if index is None:
                    raise RuleError("Không tìm thấy quy tắc. Tải lại danh sách rồi thử lại. Mã lỗi: K104.")
                if action == "delete":
                    rules.pop(index)
                else:
                    rules[index] = {"id": rules[index]["id"], "source": source, "replacement": replacement}
            else:
                raise RuleError("Unknown rule action")
            atomic_json(self.path, rules)
            return {"rules": annotate(rules), "locked": False}


def key(value):
    """Matching key: NFC, case-insensitive."""
    return normalize(normalize(value).lower())


def duplicate_ids(rules):
    """Ids of rules whose source repeats an earlier rule (ignoring case); the earliest one is the one that counts."""
    seen, duplicates = set(), set()
    for rule in rules:
        k = key(rule["source"])
        if k in seen: duplicates.add(rule["id"])
        else: seen.add(k)
    return duplicates


def annotate(rules):
    """Copy of the list for display: later duplicates get "duplicate": True so the UI can warn and offer deleting them."""
    duplicates = duplicate_ids(rules)
    return [{**rule, "duplicate": True} if rule["id"] in duplicates else dict(rule) for rule in rules]


def fit_case(matched, rule):
    """Replacement adapted to the case of the text that matched (ALL CAPS, Capitalised, lower)."""
    source, replacement = rule["source"], rule["replacement"]
    if matched == source or not replacement: return replacement
    letters = [c for c in matched if c.isalpha()]
    if len(letters) > 1 and matched.isupper(): return replacement.upper()
    if matched[:1].isupper(): return replacement[:1].upper() + replacement[1:]
    # lower-case text matched a rule written with a capital: the replacement's capital is only for the start of a sentence
    if source[:1].isupper() and replacement[:1].isupper() and not replacement[1:2].isupper():
        return replacement[:1].lower() + replacement[1:]
    return replacement


class ReplaceEngine:
    def __init__(self, rules):
        rules = [{**rule, "source": normalize(rule["source"]), "replacement": normalize(rule["replacement"])} for rule in rules]
        if any(not rule["source"] for rule in rules):
            raise RuleError("Empty replacement source")
        # Case-insensitive; when the same word appears more than once the earliest rule wins and later ones are ignored.
        self.lookup = {}
        for rule in rules:
            self.lookup.setdefault(key(rule["source"]), rule)
        self.rules = list(self.lookup.values())
        # At each position the longest literal wins; output is never re-matched.
        alternatives = sorted(self.lookup, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(s) for s in alternatives), re.IGNORECASE) if alternatives else None

    def apply(self, text):
        text = normalize(text)
        counts = {}
        def replace(match):
            matched = match.group(0)
            rule = self.lookup[key(matched)]
            counts[rule["id"]] = counts.get(rule["id"], 0) + 1
            return fit_case(matched, rule)
        output = self.pattern.sub(replace, text) if self.pattern else text
        return normalize(output), counts


def main():
    try:
        payload = json.load(sys.stdin)
        service = ReplacementRules()
        result = service.list() if payload["action"] == "list" else service.mutate(payload["action"], payload)
        response = {"status": 200, **result}
    except LockedError:
        response = {"status": 409, "error": LOCK_MESSAGE, "locked": True}
    except (ValueError, KeyError) as exc:
        response = {"status": 400, "error": str(exc)}
    except Exception:
        response = {"status": 500, "error": "Không thể đọc/ghi replacement rules."}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
