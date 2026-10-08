"""Build one paid edition's installer from start to finish.

    python packaging/build_edition.py basic            (or plus)
    python packaging/build_edition.py plus --dry-run   show every step, change nothing
    python packaging/build_edition.py plus --push-lease  also send the new version's key to the gateway when done

Run it with this repository's own Python (.venv\\Scripts\\python.exe). It only sequences the steps documented in
docs/BUILD_RELEASE.md, stops at the first failure and never prints a key:

  1. check the machine (free RAM and disk, tools, model, Admin environment, no build already running)
  2. admin-system/release_config.py     re-reads the manifest, then writes the edition's public config and trust anchor
  3. admin-system/export_build_keys.py  writes this version's vault key OUTSIDE every repository
  4. packaging/build_installer.py       builds the installer (long: 10 to 30 minutes, heavy on RAM and disk)
  5. admin-system/audit_package.py      scans the installer for private keys, tokens and customer data
  6. (--push-lease) Admin pushes lease materials so the gateway can serve the new version

To change what is built, change the version first (docs/BUILD_RELEASE.md, section 5).

Once the authority has moved to the online admin (docs/ADMIN_ONLINE.md) set ADMIN_REMOTE_URL, CF_ACCESS_CLIENT_ID and
CF_ACCESS_CLIENT_SECRET: the key, config and lease steps then talk to the online admin with a Cloudflare Access service token
instead of reading a local database, and nothing else changes.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent
ADMIN = WORKSPACE / 'admin-system'
ADMIN_PYTHON = ADMIN / '.venv' / 'Scripts' / 'python.exe'
EDITIONS = {'basic': 'audio-translate-basic', 'plus': 'audio-translate-plus'}
MIN_FREE_RAM_GIB, MIN_FREE_DISK_GIB = 5.0, 20.0  # a build compiles Rust, bundles Next.js and zips ~600 MB; measured nowhere, deliberately generous


class Memory(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong), ('available', ctypes.c_ulonglong), ('page_total', ctypes.c_ulonglong),
                ('page_free', ctypes.c_ulonglong), ('virtual_total', ctypes.c_ulonglong), ('virtual_free', ctypes.c_ulonglong), ('extended', ctypes.c_ulonglong)]


def free_ram_gib():
    info = Memory(); info.length = ctypes.sizeof(Memory)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info))
    return info.available / 2**30


def check(name, ok, detail=''):
    print(f"  [{'ok' if ok else 'FAIL'}] {name}{(' - ' + detail) if detail else ''}")
    return ok


def remote_mode():
    return bool(os.environ.get('ADMIN_REMOTE_URL'))


def preflight(product, manifest, force):
    print('Preflight')
    ram, disk = free_ram_gib(), shutil.disk_usage(ROOT).free / 2**30
    results = [
        check('Windows', os.name == 'nt'),
        check('repository Python is the interpreter', Path(sys.executable).resolve().parent.parent == (ROOT / '.venv').resolve(), f'running {sys.executable}'),
    ]
    if remote_mode():
        results += [check('online admin address', os.environ['ADMIN_REMOTE_URL'].startswith('https://'), 'ADMIN_REMOTE_URL'),
                    check('Access service token', bool(os.environ.get('CF_ACCESS_CLIENT_ID') and os.environ.get('CF_ACCESS_CLIENT_SECRET')), 'CF_ACCESS_CLIENT_ID / CF_ACCESS_CLIENT_SECRET')]
    else:
        results += [check('Admin environment', ADMIN_PYTHON.is_file(), str(ADMIN_PYTHON)), check('Admin database', (ADMIN / 'data' / 'admin.sqlite3').is_file())]
    results += [
        check('node_modules installed', (ROOT / 'node_modules').is_dir(), 'run npm install'),
        check('Rust toolchain', bool(shutil.which('cargo')) or (WORKSPACE / '.tools' / 'rust' / 'cargo' / 'bin' / 'cargo.exe').is_file()),
        check('.NET compiler (installer stub)', (Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Microsoft.NET' / 'Framework64' / 'v4.0.30319' / 'csc.exe').is_file()),
        check('translation model', any((ROOT / 'models' / 'Hy-MT2-7B-Q4_K_M').glob('*.gguf'))),
        check('manifest names this edition', manifest.get('product_id') == product),
        check(f'free RAM >= {MIN_FREE_RAM_GIB:.0f} GiB', ram >= MIN_FREE_RAM_GIB or force, f'{ram:.1f} GiB free (close other programs, or pass --force)'),
        check(f'free disk >= {MIN_FREE_DISK_GIB:.0f} GiB', disk >= MIN_FREE_DISK_GIB or force, f'{disk:.0f} GiB free'),
    ]
    if os.environ.get('AUDIO_RELEASE_HARDENED') == '1':
        for variable in ('AUDIO_SIGNING_CERT', 'AUDIO_MANIFEST_KEY_FILE'):
            results.append(check(f'hardened release needs {variable}', bool(os.environ.get(variable))))
    return all(results)


def run(command, cwd, env=None, dry=False):
    print('  $', ' '.join(f'"{c}"' if ' ' in str(c) else str(c) for c in command), f'   (in {cwd})')
    if dry: return
    result = subprocess.run([str(c) for c in command], cwd=cwd, env=env)
    if result.returncode != 0: raise SystemExit(f'Step failed with exit code {result.returncode}. Nothing after it was run.')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('edition', choices=sorted(EDITIONS))
    parser.add_argument('--keys-dir', type=Path, default=Path.home() / 'audio-translate-keys', help='where the version key file goes; must be outside every repository')
    parser.add_argument('--dry-run', action='store_true'); parser.add_argument('--force', action='store_true', help='build even when RAM or disk are below the preflight minimum')
    parser.add_argument('--push-lease', action='store_true', help='after the build, push lease materials to the gateway (Admin must have the gateway configured)')
    args = parser.parse_args()
    product = EDITIONS[args.edition]
    manifest = json.loads((ROOT / 'products' / args.edition / 'product.manifest.json').read_text(encoding='utf-8'))
    version = manifest['version']
    print(f'Edition {args.edition}: {product} {version} -> {manifest["artifact_path"]}' + ('   [DRY RUN]' if args.dry_run else ''))
    if not preflight(product, manifest, args.force):
        raise SystemExit('Preflight failed. Fix the items marked FAIL, then run again.')
    label = f'{product}-{version}'
    if (ROOT / 'dist' / f'release-{label}.json').exists():
        print(f'Note: dist/release-{label}.json exists. If the code is unchanged the builder verifies the installer and stops; if the code changed it refuses'
              ' (VERSION_ALREADY_RELEASED). Raise the version in products/%s/product.manifest.json first (docs/BUILD_RELEASE.md, section 5).' % args.edition)
    key_file = args.keys_dir / f'{product}-{version}.key'
    remote = remote_mode()
    admin_python = sys.executable if remote else ADMIN_PYTHON
    print('\n1/5 Public config and trust anchor (Admin first re-reads the manifest, so a raised version is picked up)')
    if remote:
        run([admin_python, 'release_config.py', '--remote', product], ADMIN, dry=args.dry_run)  # sends the manifest to the online admin, then fetches the public config
    else:
        register = 'import sys; from core import Authority; Authority("data/admin.sqlite3").register_product(sys.argv[1])'
        run([admin_python, '-c', register, ROOT / 'products' / args.edition / 'product.manifest.json'], ADMIN, dry=args.dry_run)
        run([admin_python, 'release_config.py', product], ADMIN, dry=args.dry_run)
    print('\n2/5 Vault key for this version (written outside every repository, never printed)')
    run([admin_python, 'export_build_keys.py', *(['--remote'] if remote else []), '--product', product, '--version', version, '--out', key_file], ADMIN, dry=args.dry_run)
    print('\n3/5 Build the installer (10 to 30 minutes)')
    env = {**os.environ, 'AUDIO_CONTENT_KEY_FILE': str(key_file)}
    run([sys.executable, 'packaging/build_installer.py', '--product', product], ROOT, env, args.dry_run)
    print('\n4/5 Audit the installer for private material')
    if (ADMIN / 'data' / 'admin.sqlite3').is_file():  # a moved database is still readable; it knows every key issued before the move
        run([ADMIN_PYTHON, 'audit_package.py', '--edition', args.edition], ADMIN, dry=args.dry_run)
    else:
        print("  (no local admin database: skipped; the builder's own secret scan already ran)")
    if args.push_lease:
        print('\n5/5 Push lease materials to the gateway')
        code = ('from remote_admin import RemoteAdmin; print(RemoteAdmin.from_env().push_lease())' if remote
                else 'from core import Authority; from billing import Billing; print(Billing(Authority("data/admin.sqlite3")).push_lease_materials())')
        run([admin_python, '-c', code], ADMIN, dry=args.dry_run)
    else:
        print('\n5/5 Not pushing lease materials (no --push-lease). Do it in Admin > Billing > Push Lease Keys (or rerun with --push-lease) before giving the installer to anyone.\n'
              '     Without it the gateway answers LEASE_VERSION_UNSUPPORTED, the app never gets its usage key and the voice list stays on "loading".')
    artifact = ROOT / manifest['artifact_path']
    print(f'\nDone. Installer: {artifact}' if not args.dry_run else '\nDry run finished; nothing was changed.')


if __name__ == '__main__':
    main()
