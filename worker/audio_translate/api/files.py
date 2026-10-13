"""Answering with a saved output file (was lib/server/file-response.ts): inline or as a download, a bounded text preview,
and byte ranges for audio seeking."""
import json
import os
import re

from fastapi.responses import Response, StreamingResponse

from audio_translate.api.license import license_denial
from audio_translate.api.web import json_response

MIME = {'wav': 'audio/wav', 'm4a': 'audio/mp4', 'mp4': 'audio/mp4', 'mp3': 'audio/mpeg', 'webm': 'audio/webm', 'ogg': 'audio/ogg', 'opus': 'audio/ogg',
        'flac': 'audio/flac', 'aac': 'audio/aac', 'md': 'text/markdown; charset=utf-8', 'txt': 'text/plain; charset=utf-8',
        'json': 'application/json; charset=utf-8', 'jsonl': 'application/x-ndjson; charset=utf-8'}
TEXT = ('md', 'txt', 'json', 'jsonl')
PIECE = 65536
RANGE = re.compile(r'^bytes=(\d*)-(\d*)$')


def js_number(text):
    """JavaScript's Number(string) for the query values the UI sends ('' is 0; anything unreadable is NaN)."""
    text = (text or '').strip()
    if not text: return 0.0
    if text.lower().startswith(('0x', '0o', '0b')):
        try: return float(int(text, 0))
        except ValueError: return float('nan')
    if '_' in text or text.lower() in ('inf', 'nan', '+inf', '-inf'): return float('nan')
    if text in ('Infinity', '+Infinity'): return float('inf')
    if text == '-Infinity': return float('-inf')
    try: return float(text)
    except ValueError: return float('nan')


def safe_integer(value): return value == value and value not in (float('inf'), float('-inf')) and value == int(value) and abs(value) <= 2 ** 53 - 1


def preview(file, size, offset_text, extension):
    offset = js_number(offset_text)
    if not safe_integer(offset) or offset < 0 or offset > size: return json_response({'error': 'Invalid preview offset'}, 400)
    offset = int(offset)
    with open(file, 'rb') as handle:
        handle.seek(offset); buffer = handle.read(min(PIECE, size - offset))
    used = len(buffer)
    if offset + used < size:
        newline = buffer[:used].rfind(b'\n')
        if newline >= 0: used = newline + 1
        else:   # stop before a multi-byte character that the piece cuts in two
            lead = used - 1
            while lead >= 0 and buffer[lead] & 0xC0 == 0x80: lead -= 1
            if lead >= 0:
                byte = buffer[lead]
                width = 4 if byte >= 0xF0 else 3 if byte >= 0xE0 else 2 if byte >= 0xC0 else 1
                if lead + width > used: used = lead
    content = buffer[:used].decode('utf-8', 'replace')
    if extension == 'json' and offset == 0 and used == size:
        try: content = json.dumps(json.loads(content), ensure_ascii=False, indent=2)
        except ValueError: pass   # plain text fallback
    following = offset + used if offset + used < size else None
    return json_response({'content': content, 'offset': offset, 'next_offset': following, 'size': size}, no_store=True)


def stream(file, start, length):
    with open(file, 'rb') as handle:
        handle.seek(start)
        while length > 0:
            piece = handle.read(min(PIECE, length))
            if not piece: return
            length -= len(piece); yield piece


def saved_file_response(request, file, download=False):
    """Blocking (reads the disk and may ask the licence core): call it through web.threaded."""
    if not download:
        denied = license_denial(False)
        if denied: return denied
    size = os.stat(file).st_size
    extension = os.path.splitext(file)[1][1:]
    headers = {'Content-Type': MIME.get(extension, 'application/octet-stream'),
               'Content-Disposition': f'{"attachment" if download else "inline"}; filename="{os.path.basename(file)}"',
               'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
    if request.query_params.get('preview') == '1' and extension in TEXT: return preview(file, size, request.query_params.get('offset'), extension)
    start, end, status = 0, size - 1, 200
    headers['Accept-Ranges'] = 'bytes'
    asked = request.headers.get('range')
    if asked is not None:
        match = RANGE.match(asked)
        if match and (match[1] or match[2]):
            if not match[1]: start = max(0, size - int(match[2]))
            else:
                start = int(match[1])
                if match[2]: end = min(end, int(match[2]))
        if not match or (not match[1] and not match[2]) or start > end or start >= size:
            return Response(None, 416, {'Content-Range': f'bytes */{size}'})
        status = 206; headers['Content-Range'] = f'bytes {start}-{end}/{size}'
    headers['Content-Length'] = str(max(0, end - start + 1))
    content_type = headers.pop('Content-Type')
    if not size: return Response(b'', 200, headers, content_type)
    return StreamingResponse(stream(file, start, end - start + 1), status, headers, content_type)
