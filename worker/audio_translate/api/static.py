"""Serving the built UI (the static export of the Next.js app) from the API itself.

Files are looked up as the export lays them out: /history -> history.html, /history/view -> history/view.html, assets under
/_next. Nothing outside the UI folder is ever served.
"""
import mimetypes
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

mimetypes.add_type('text/javascript', '.js')
mimetypes.add_type('application/json', '.json')
mimetypes.add_type('image/x-icon', '.ico')
HEADERS = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY'}
LOCKED = ('<!doctype html><meta charset="utf-8"><title>Audio Translate</title>'
          '<body style="font:16px system-ui;max-width:32em;margin:15vh auto;padding:0 1em">'
          '<h1>Audio Translate</h1><p>Hãy mở ứng dụng bằng shortcut Audio Translate trong Start menu.</p>'
          '<p>Open the app with the Audio Translate shortcut in the Start menu.</p>')


def locate(ui_dir: Path, path: str):
    """The file for a URL path, or None. Refuses anything that resolves outside the UI folder."""
    root = ui_dir.resolve()
    relative = path.strip('/')
    if '\\' in relative or '\x00' in relative or any(part in ('..', '.') for part in relative.split('/')) or (len(relative) > 1 and relative[1] == ':'): return None
    candidates = ['index.html'] if not relative else [relative, f'{relative}.html', f'{relative}/index.html']
    # Next's client asks for a page's data as /history/__next.history.__PAGE__.txt but the export writes it as
    # history/__next.history/__PAGE__.txt (a folder where the request has a dot).
    folder, _, name = relative.rpartition('/')
    if name.startswith('__next.') and name.endswith('.txt') and not name.startswith('__next._'):
        candidates.append((folder + '/' if folder else '') + '__next.' + name[len('__next.'):-len('.txt')].replace('.', '/') + '.txt')
    for name in candidates:
        found = (root / name).resolve()
        if found.is_file() and found.is_relative_to(root): return found
    return None


def is_page(path: str):
    """A request for a page (what a person types or follows), as opposed to an asset."""
    last = path.rstrip('/').rsplit('/', 1)[-1]
    return not path.startswith('/_next/') and ('.' not in last or last.endswith('.html'))


def serve(ui_dir: Path, path: str):
    found = locate(ui_dir, path)
    if not found:
        missing = locate(ui_dir, '/404')
        return FileResponse(missing, 404, {**HEADERS, 'Cache-Control': 'no-cache'}) if missing else HTMLResponse('Not found', 404, HEADERS)
    cache = 'public, max-age=31536000, immutable' if '/_next/static/' in found.as_posix() else 'no-cache'
    return FileResponse(found, headers={**HEADERS, 'Cache-Control': cache})


def locked_page():
    return HTMLResponse(LOCKED, 403, {**HEADERS, 'Cache-Control': 'no-store'})
