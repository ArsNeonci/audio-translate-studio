"""Put files on the gateway server's own disk over ssh (the folder the gateway serves models and the yt-dlp channel from, MODEL_DIR).

Used by upload_model.py and publish_youtube_update.py with --ssh. The server needs a key login and passwordless sudo for the account
(deploy/deploy_gateway.py works the same way). Files end up owned by audio-gateway with mode 640, so only the gateway reads them.
Standard library only. Nothing secret is printed or put on a command line.
"""
import hashlib
from pathlib import Path
import shlex
import shutil
import subprocess
import uuid

DEFAULT_ROOT = '/var/lib/audio-gateway/files'
SERVICE = 'audio-gateway'


def _tool(name):
    found = shutil.which(name) or shutil.which(name + '.exe')
    if not found: raise SystemExit(f'{name} was not found on PATH (Windows: Settings > Optional features > OpenSSH Client).')
    return found


def _checked_name(name):
    parts = name.split('/')
    if not name or name.startswith('/') or any(p in ('', '.', '..') or p.startswith('-') for p in parts): raise ValueError(f'Unsafe name: {name!r}')
    return name


class SshFiles:
    def __init__(self, target, key=None, root=DEFAULT_ROOT, run=subprocess.run):
        self.target, self.key, self.root, self._run = target, key, root.rstrip('/'), run

    def _options(self):
        return ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new', *(['-i', str(self.key), '-o', 'IdentitiesOnly=yes'] if self.key else [])]

    def ssh(self, command, binary=False):
        return self._run([_tool('ssh'), *self._options(), self.target, command], capture_output=True, text=not binary)

    def _remote(self, name):
        return shlex.quote(f'{self.root}/{_checked_name(name)}')

    def exists(self, name):
        return self.ssh(f'sudo test -e {self._remote(name)}').returncode == 0

    def put(self, local, name, replace=False):
        """Copy `local` to <root>/<name>. Without `replace` an existing file is left alone and False is returned (like --no-clobber)."""
        if not replace and self.exists(name): return False
        temp = f'.upload-{uuid.uuid4().hex}'
        copied = self._run([_tool('scp'), '-q', *self._options(), str(local), f'{self.target}:{temp}'], capture_output=True, text=True)
        if copied.returncode: raise SystemExit(f'Copy of {Path(local).name} failed:\n' + copied.stderr[-800:])
        target = self._remote(name)
        folder = shlex.quote(f'{self.root}/{_checked_name(name).rpartition("/")[0]}') if '/' in name else shlex.quote(self.root)
        # mv within the same disk is a rename, so a 4.6 GB model does not need room for a second copy.
        command = (f'sudo install -d -o {SERVICE} -g {SERVICE} -m 750 {folder} && sudo mv {shlex.quote(temp)} {target}.part '
                   f'&& sudo chown {SERVICE}:{SERVICE} {target}.part && sudo chmod 640 {target}.part && sudo mv -f {target}.part {target}; '
                   f'status=$?; rm -f {shlex.quote(temp)}; exit $status')
        done = self.ssh(command)
        if done.returncode: raise SystemExit(f'Install of {name} on the server failed:\n' + (done.stderr or '')[-800:])
        return True

    def cat(self, name):
        """The file's bytes, or None when it does not exist."""
        result = self.ssh(f'sudo cat {self._remote(name)}', binary=True)
        return result.stdout if result.returncode == 0 else None

    def sizes(self, prefix):
        """{name: size} of every file under <root>/<prefix>."""
        result = self.ssh(f"sudo find {self._remote(prefix.rstrip('/'))} -type f ! -name '*.part' -printf '%P %s\\n'")
        found = {}
        for line in (result.stdout or '').splitlines():
            path, _, size = line.rpartition(' ')
            if size.isdigit(): found[f'{prefix.rstrip("/")}/{path}'] = int(size)
        return found

    def sha256(self, names):
        """{name: sha256 hex} computed on the server."""
        names = list(names)
        if not names: return {}
        result = self.ssh('sudo sha256sum ' + ' '.join(self._remote(n) for n in names))
        if result.returncode: raise SystemExit('Could not hash the files on the server:\n' + (result.stderr or '')[-800:])
        prefix, found = self.root + '/', {}
        for line in result.stdout.splitlines():
            digest, _, path = line.partition(' ')
            path = path.strip().lstrip('*')
            if path.startswith(prefix): found[path[len(prefix):]] = digest
        return found


def local_sha256(path):
    hasher = hashlib.sha256()
    with Path(path).open('rb') as handle:
        while chunk := handle.read(8 * 1024 * 1024): hasher.update(chunk)
    return hasher.hexdigest()
