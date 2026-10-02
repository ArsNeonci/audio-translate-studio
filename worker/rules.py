"""Literal, non-cascading NFC replacements and persistent rule CRUD."""
from contextlib import contextmanager
import json
import re
import sys
import unicodedata
import uuid

from storage import DATA, LockedError, atomic_json, file_lock, read_json

LOCK_MESSAGE = "Replacement rules are locked while moderation is running."


class RuleError(ValueError):
    pass


def normalize(value):
    return unicodedata.normalize("NFC", value)


class ReplacementRules:
    def __init__(self, config_dir=None):
        self.directory = config_dir or DATA / "config"
        self.path = self.directory / "replacement-rules.json"
        self.lock_path = self.directory / "replacement-rules.lock"

    def read(self):
        return read_json(self.path) if self.path.exists() else []

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
                return {"rules": self.read(), "locked": False}
        except LockedError:
            return {"rules": self.read(), "locked": True}

    def mutate(self, action, payload):
        # Lock covers the read/validate/write transaction. Moderation holds this
        # same OS lock for its entire run, across all Next.js/Python processes.
        with self.locked():
            rules = self.read()
            if action in ("add", "edit"):
                source, replacement = payload.get("source"), payload.get("replacement")
                if not isinstance(source, str) or not source.strip() or not isinstance(replacement, str):
                    raise RuleError("Original phải có nội dung; Replacement phải là chuỗi (có thể để trống).")
                source, replacement = normalize(source), normalize(replacement)
                if len(source) > 1000 or len(replacement) > 10000:
                    raise RuleError("Original tối đa 1.000 ký tự; Replacement tối đa 10.000 ký tự.")
                if any(normalize(r["source"]) == source and r["id"] != payload.get("id") for r in rules):
                    raise RuleError("Original đã có trong danh sách.")
            if action == "add":
                rules.append({"id": str(uuid.uuid4()), "source": source, "replacement": replacement})
            elif action in ("edit", "delete"):
                index = next((i for i, rule in enumerate(rules) if rule["id"] == payload.get("id")), None)
                if index is None:
                    raise RuleError("Không tìm thấy rule.")
                if action == "delete":
                    rules.pop(index)
                else:
                    rules[index] = {"id": rules[index]["id"], "source": source, "replacement": replacement}
            else:
                raise RuleError("Unknown rule action")
            atomic_json(self.path, rules)
            return {"rules": rules, "locked": False}


class ReplaceEngine:
    def __init__(self, rules):
        self.rules = [{**rule, "source": normalize(rule["source"]), "replacement": normalize(rule["replacement"])} for rule in rules]
        if any(not rule["source"] for rule in self.rules):
            raise RuleError("Empty replacement source")
        self.lookup = {r["source"]: r for r in self.rules}
        if len(self.lookup) != len(self.rules):
            raise RuleError("Duplicate normalized replacement source")
        # At each position the longest literal wins; output is never re-matched.
        alternatives = sorted(self.lookup, key=len, reverse=True)
        self.pattern = re.compile("|".join(re.escape(s) for s in alternatives)) if alternatives else None

    def apply(self, text):
        text = normalize(text)
        counts = {}
        def replace(match):
            rule = self.lookup[match.group(0)]
            counts[rule["id"]] = counts.get(rule["id"], 0) + 1
            return rule["replacement"]
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
