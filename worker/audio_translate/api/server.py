"""Serve the local API and, with --ui, the built UI: python worker/app_api.py --port N [--ui out] (AUDIO_API_TOKEN in the environment, 32+ characters).

Listens on 127.0.0.1 only. Prints "AUDIO_API_READY <port>" once it accepts connections, so a starter can wait for it.
"""
import argparse
import os
from pathlib import Path
import socket

import uvicorn

from audio_translate.api.app import create_app
from audio_translate.api.web import api_token


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=0, help='0 picks a free port')
    parser.add_argument('--ui', default=os.environ.get('AUDIO_UI_DIR', ''), help='folder of the built UI to serve (default: AUDIO_UI_DIR; none: API only)')
    args = parser.parse_args()
    if args.ui and not (Path(args.ui) / 'index.html').is_file(): raise SystemExit(f'No built UI in {args.ui}')
    token = api_token()
    port = args.port
    if not port:
        with socket.socket() as probe: probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    config = uvicorn.Config(create_app(token, args.ui or None), host='127.0.0.1', port=port, proxy_headers=False, server_header=False,
                            access_log=False, log_level='warning')
    server = uvicorn.Server(config)
    original = server.startup

    async def startup(*a, **k):
        await original(*a, **k)
        print(f'AUDIO_API_READY {port}', flush=True)
        from audio_translate.api.app_update import write_health
        write_health()   # tells updater.exe that this version started
    server.startup = startup
    server.run()


if __name__ == '__main__':
    main()
