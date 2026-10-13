"""Per-user YouTube profile. Credentials stay in the browser, never in API responses."""
from contextlib import contextmanager
from datetime import datetime, timezone
from http.cookiejar import Cookie
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from audio_translate.core.storage import atomic_json, file_lock, LockedError, read_json
from audio_translate.transcription import browser_cleanup as cleanup
from audio_translate.transcription.browser_cleanup import session_root


class YouTubeSessionError(RuntimeError):
    pass


def browser_binary():
    custom = os.getenv('YOUTUBE_BROWSER_BIN')
    if custom:
        binary = Path(custom)
        return str(binary) if binary.is_file() else None
    candidates = []
    if os.name == 'nt':
        for directory in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
            base = Path(os.getenv(directory, 'C:/nonexistent'))
            candidates.extend((base/'Microsoft/Edge/Application/msedge.exe', base/'Google/Chrome/Application/chrome.exe'))
    for name in ('msedge', 'google-chrome', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    return next((str(p) for p in candidates if p.is_file()), None)


def configuration():
    path = session_root() / 'connection.json'
    return read_json(path) if path.is_file() else {'enabled': False, 'state': 'NOT_CONNECTED', 'last_checked': None}


def save_state(**changes):
    state = {**configuration(), **changes}
    atomic_json(session_root() / 'connection.json', state)
    return state


def status():
    state = configuration()
    return {'enabled': bool(state.get('enabled')), 'state': state.get('state', 'NOT_CONNECTED'),
            'last_checked': state.get('last_checked'), 'browser_available': browser_binary() is not None,
            'legacy_cookie_override': bool(os.getenv('YTDLP_COOKIES_FILE')) and not state.get('enabled', False),
            'profile_path': str(session_root() / 'profile'), 'downloader': downloader(), 'browser_running': browser_running()}


def browser_running():
    """{'hidden': processes of a hidden browser, 'window': a sign-in window is open}: what the "close browser" button would close."""
    try:
        return cleanup.running()
    except Exception:
        return None


def downloader():
    """Which yt-dlp the next download uses (bundled or a signed update from the gateway) and when the gateway was last asked."""
    try:
        from audio_translate.transcription.ytdlp_update import info
        return info()
    except Exception:
        return None


def endpoint():
    """Only the random loopback endpoint recorded in this app's dedicated profile."""
    try:
        lines = (session_root()/'profile'/'DevToolsActivePort').read_text().splitlines()
        port, route = int(lines[0]), lines[1]
        if not 1024 <= port <= 65535 or not re.fullmatch(r'/devtools/browser/[0-9a-f-]+', route):
            return None
        return f'ws://127.0.0.1:{port}{route}'
    except (OSError, ValueError, IndexError):
        return None


@contextmanager
def socket_for(url):
    from websockets.sync.client import connect
    with connect(url, proxy=None, open_timeout=2, close_timeout=1, max_size=4*1024*1024) as ws:
        yield ws


def command(ws, method, params=None, session=None):
    command.sequence = getattr(command, 'sequence', 0) + 1
    identity = command.sequence
    ws.send(json.dumps({'id': identity, 'method': method, 'params': params or {}, **({'sessionId': session} if session else {})}))
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = json.loads(ws.recv(timeout=max(.1, deadline-time.monotonic())))
        if response.get('id') == identity:
            if 'error' in response:
                raise YouTubeSessionError('Không đọc được phiên YouTube. Đóng cửa sổ kết nối rồi thử lại.')
            return response.get('result', {})
    raise YouTubeSessionError('Trình duyệt YouTube không phản hồi. Đóng cửa sổ kết nối rồi thử lại.')


def live_endpoint():
    url = endpoint()
    if url:
        try:
            with socket_for(url) as ws:
                command(ws, 'Browser.getVersion')
            return url
        except Exception:
            pass
    return None


def launch(interactive):
    binary = browser_binary()
    if not binary:
        raise YouTubeSessionError('Cần Microsoft Edge hoặc Google Chrome. Cài trình duyệt rồi mở lại Kết nối YouTube.')
    profile = session_root() / 'profile'
    profile.mkdir(parents=True, exist_ok=True)
    # A stale port file must not make a new process connect to an old endpoint.
    (profile / 'DevToolsActivePort').unlink(missing_ok=True)
    # No --restore-last-session: it reopened every tab of the previous run and added one more, so each launch left another
    # about:blank (hidden) or youtube.com (sign-in window) behind. The login cookies are persistent, so nothing is lost.
    args = [binary, f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check', '--disable-background-mode']
    if not interactive:
        # Extensions are not needed to read cookies; their service workers cost memory.
        args.extend(['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                     '--headless=new', '--disable-gpu', '--disable-extensions'])
    args.append('https://www.youtube.com/' if interactive else 'about:blank')
    if interactive:
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=cleanup.browser_env(),
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    else:
        # In a job object: if this process ends for any reason, the hidden browser and its children end with it.
        process = cleanup.start_hidden(args)
    if interactive:
        # Authentication is manual in an ordinary installed browser, never CDP.
        # Chromium may hand the URL to an existing profile process then exit.
        save_state(browser_mode='manual')
        return None, process
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        url = live_endpoint()
        if url:
            save_state(browser_mode='interactive' if interactive else 'headless')
            return url, process
        # The first process may hand over to a restarted one and exit (Edge does this in some environments): only when nothing of the
        # hidden browser is left is it a failure.
        if process.poll() is not None and not cleanup.hidden_processes():
            break
        time.sleep(.15)
    if process.poll() is None:
        process.terminate()
    cleanup.stop_hidden()
    raise YouTubeSessionError('Không mở được profile YouTube. Đóng cửa sổ profile riêng rồi thử lại; kiểm tra chính sách trình duyệt.')


def manual_profile_running():
    """Only inspect this app's explicit profile, not personal browser cookies."""
    return bool(cleanup.profile_processes())


def close_hidden():
    """End a hidden browser: politely first (it saves its profile), then whatever is left of it. Returns how many processes were stopped."""
    url = live_endpoint()
    if url:
        try:
            with socket_for(url) as ws:
                command(ws, 'Browser.close')
        except Exception:
            pass
        for _ in range(40):
            if not cleanup.hidden_processes():
                break
            time.sleep(.15)
    return cleanup.stop_hidden()


def open_login():
    with file_lock(session_root()/'session.lock'):
        url = live_endpoint()
        if url and configuration().get('browser_mode') == 'headless':
            close_hidden()
            url = None
        if url:
            save_state(state='CLOSE_LOGIN_WINDOW')
            raise YouTubeSessionError('Cửa sổ profile cũ đang dùng chế độ điều khiển từ xa. Hãy đóng cửa sổ YouTube riêng đó, rồi bấm Mở YouTube lại để đăng nhập trong trình duyệt bình thường.')
        launch(True)
        save_state(enabled=True, state='AWAITING_SIGN_IN')
    return status()


def youtube_domain(domain):
    domain = domain.lstrip('.').lower()
    return domain == 'youtube.com' or domain.endswith('.youtube.com')


def cookie_objects(raw):
    cookies = []
    for item in raw:
        domain = item.get('domain', '')
        if not youtube_domain(domain):
            continue
        expires = item.get('expires', -1)
        if expires > 0 and expires <= time.time():
            continue
        cookies.append(Cookie(version=0, name=item['name'], value=item['value'], port=None,
            port_specified=False, domain=domain, domain_specified=domain.startswith('.'),
            domain_initial_dot=domain.startswith('.'), path=item.get('path', '/'), path_specified=True,
            secure=bool(item.get('secure')), expires=int(expires) if expires > 0 else None,
            discard=expires <= 0, comment=None, comment_url=None,
            rest={'HttpOnly': None} if item.get('httpOnly') else {}, rfc2109=False))
    return cookies


def refresh_page(url, page='https://www.youtube.com/'):
    """Visit YouTube in the browser's existing blank tab so the browser can update its own session, then leave the tab blank again.
    Extra tabs are closed; a tab is created only when there is none."""
    with socket_for(url) as ws:
        pages = [t['targetId'] for t in command(ws, 'Target.getTargets').get('targetInfos', []) if t.get('type') == 'page']
        for extra in pages[1:]:
            try: command(ws, 'Target.closeTarget', {'targetId': extra})
            except Exception: pass
        target = pages[0] if pages else command(ws, 'Target.createTarget', {'url': 'about:blank'})['targetId']
        # Target-scoped CDP session; no cookie values cross the web API.
        session = command(ws, 'Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
        try:
            command(ws, 'Page.navigate', {'url': page}, session)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                state = command(ws, 'Runtime.evaluate', {'expression': 'document.readyState', 'returnByValue': True}, session)
                if state.get('result', {}).get('value') == 'complete':
                    break
                time.sleep(.2)
        except Exception:
            pass  # Offline/slow page: persisted cookies may still work for yt-dlp.
        finally:
            try: command(ws, 'Page.navigate', {'url': 'about:blank'}, session)
            except Exception: pass


def cookies_for_download():
    if not configuration().get('enabled'):
        return None
    owned = None
    with file_lock(session_root()/'session.lock'):
        url = None
        try:
            # A hidden browser that this call did not start is a leftover (its owner was stopped before it could close it):
            # it is ended, not reused, so it cannot stay in memory for ever.
            close_hidden()
            if manual_profile_running():
                save_state(state='CLOSE_LOGIN_WINDOW')
                raise YouTubeSessionError('Hãy đăng nhập xong và đóng các cửa sổ YouTube của profile Audio Studio trước, rồi bấm Kiểm tra kết nối. App không điều khiển cửa sổ đăng nhập.')
            url, owned = launch(False)
            refresh_page(url)
            with socket_for(url) as ws:
                cookies = cookie_objects(command(ws, 'Storage.getCookies').get('cookies', []))
            signed_in = any(c.name in ('SID', '__Secure-1PSID', '__Secure-3PSID') for c in cookies)
            save_state(state='SESSION_SAVED' if signed_in else 'SIGN_IN_REQUIRED',
                       last_checked=datetime.now(timezone.utc).isoformat())
            if not signed_in:
                raise YouTubeSessionError('Phiên YouTube cần đăng nhập. Mở Settings → Kết nối YouTube, đăng nhập rồi bấm Kiểm tra kết nối.')
            return cookies
        except YouTubeSessionError:
            raise
        except Exception:
            raise YouTubeSessionError('Không đọc được profile YouTube. Mở Settings → Kết nối YouTube rồi đăng nhập lại.') from None
        finally:
            if owned is not None:
                try:
                    with socket_for(url) as ws:
                        command(ws, 'Browser.close')
                except Exception:
                    pass
                try:
                    owned.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    owned.terminate()
                cleanup.stop_hidden()   # nothing of it stays behind, whatever happened above


def mark_auth_required():
    if configuration().get('enabled'):
        # A download may fail after a later interactive login; serialize metadata writes.
        with file_lock(session_root()/'session.lock'):
            save_state(state='SIGN_IN_REQUIRED')


def close_browser():
    """The close-browser button: end a hidden browser, and ask a sign-in window to close (never a kill: Edge saves the session)."""
    with file_lock(session_root()/'session.lock'):
        close_hidden()
        window_open = bool(cleanup.window_processes()) and not cleanup.close_window()
    return {**status(), 'window_open': window_open}


def disconnect():
    with file_lock(session_root()/'session.lock'):
        url = live_endpoint()
        if url:
            try:
                with socket_for(url) as ws:
                    command(ws, 'Browser.close')
            except Exception:
                pass
        # Keep the profile so reconnecting/upgrading does not erase the user's session.
        save_state(enabled=False, state='NOT_CONNECTED')
    return status()


def main():
    try:
        payload = json.load(sys.stdin)
        action = payload.get('action')
        if action == 'status':
            result = status()
        elif action == 'open':
            result = open_login()
        elif action == 'check':
            # Also ask the gateway for a newer yt-dlp now (at most every 15 minutes); a failure here never blocks the check.
            from audio_translate.transcription.ytdlp_update import refresh
            refresh(force=True)
            if not configuration().get('enabled'):
                raise YouTubeSessionError('Bấm Kết nối YouTube và đăng nhập trước khi kiểm tra.')
            cookies_for_download()
            result = status()
        elif action == 'close_browser':
            result = close_browser()
        elif action == 'disconnect':
            result = disconnect()
        else:
            raise ValueError('Invalid action')
        response = {'status': 200, **result}
    except LockedError:
        response = {'status': 409, 'error': 'Profile YouTube đang được sử dụng. Chờ vài giây rồi thử lại.'}
    except YouTubeSessionError as exc:
        response = {'status': 409, 'error': str(exc), **status()}
    except Exception:
        response = {'status': 500, 'error': 'Không thể quản lý kết nối YouTube. Kiểm tra quyền truy cập thư mục profile.'}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == '__main__':
    main()
