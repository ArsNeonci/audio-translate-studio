"""Final release secret scan (Phase 3).

Walks a staged payload tree and fails if it finds material that must never ship: private keys,
admin/API tokens with a value, DPAPI blobs, SQLite databases or PEM private blocks. This is the
build-time backstop complementing admin-system/audit_package.py (which audits the finished EXE).
Public keys, the public-config and the signed manifest are allowed through.
"""
import argparse
import re
from pathlib import Path

# Filenames/extensions that are secret by nature and must not be inside a shipped payload.
FORBIDDEN_SUFFIXES = {'.dpapi', '.sqlite3', '.pem', '.key', '.pfx', '.p12'}
FORBIDDEN_NAMES = {'trust-anchor.json', 'admin.sqlite3'}

# High-signal content patterns (value-bearing secrets, not the word alone).
PATTERNS = [
    ('pem-private-key', re.compile(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----')),
    ('assigned-api-token', re.compile(rb'(?:ADMIN_TOKEN|GEMINI_API_KEY|API_KEY)\s*[=:]\s*["\']?[A-Za-z0-9_\-]{16,}')),
    ('named-raw-private-key', re.compile(rb'(?:private|signer_private|content_key|root_key|master)[\"\']?\s*[=:]\s*["\']?[0-9a-fA-F]{64}')),
]
TEXT_SUFFIXES = {'.py', '.js', '.ts', '.json', '.txt', '.cfg', '.ini', '.env', '.toml', '.md', '.ps1', '.cs', '.cjs', '.mjs'}
SKIP_DIRS = {'node_modules', '__pycache__', '.git', '.venv', 'models', 'runtime'}


def scan(root):
    """Return a list of (path, reason) findings. Empty means the tree is clean."""
    root = Path(root)
    findings = []
    for path in root.rglob('*'):
        if not path.is_file() or set(path.relative_to(root).parts) & SKIP_DIRS:
            continue
        name = path.name.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or name in FORBIDDEN_NAMES:
            findings.append((path, f'forbidden file: {path.name}'))
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 8 * 1024 * 1024:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for label, pattern in PATTERNS:
            match = pattern.search(data)
            # The *.example templates intentionally carry empty-valued placeholders.
            if match and not name.endswith('.example'):
                findings.append((path, label))
                break
    return findings


def main():
    parser = argparse.ArgumentParser(description='Fail if a payload tree contains secrets')
    parser.add_argument('--root', required=True)
    args = parser.parse_args()
    findings = scan(args.root)
    for path, reason in findings:
        print(f'SECRET: {reason}: {path}')
    if findings:
        raise SystemExit(f'Secret scan failed: {len(findings)} finding(s)')
    print('Secret scan passed: no private keys, tokens, DPAPI blobs or databases in payload.')


if __name__ == '__main__':
    main()
