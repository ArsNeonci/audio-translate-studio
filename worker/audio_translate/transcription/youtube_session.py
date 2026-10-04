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


class YouTubeSessionError(RuntimeError):
    pass


def session_root():
    custom = os.getenv('YOUTUBE_SESSION_ROOT')
    if custom:
        return Path(custom).resolve()
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'AudioTranslate' / 'youtube'
    return Path(os.getenv('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'AudioTranslate' / 'youtube'


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
            'profile_path': str(session_root() / 'profile')}


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


def command(ws, method, params=None):
    command.sequence = getattr(command, 'sequence', 0) + 1
    identity = command.sequence
    ws.send(json.dumps({'id': identity, 'method': method, 'params': params or {}}))
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
    args = [binary, f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
            '--disable-background-mode', '--restore-last-session']
    if not interactive:
        args.extend(['--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                     '--headless=new', '--disable-gpu'])
    args.append('https://www.youtube.com/' if interactive else 'about:blank')
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
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
        if process.poll() is not None:
            break
        time.sleep(.15)
    if process.poll() is None:
        process.terminate()
    raise YouTubeSessionError('Không mở được profile YouTube. Đóng cửa sổ profile riêng rồi thử lại; kiểm tra chính sách trình duyệt.')


def manual_profile_running():
    """Only inspect this app's explicit profile, not personal browser cookies."""
    import psutil
    profile=(session_root()/'profile').resolve()
    for process in psutil.process_iter(['cmdline']):
        try:
            args=process.info.get('cmdline') or []
            for arg in args:
                if arg.startswith('--user-data-dir=') and Path(arg.split('=',1)[1]).resolve()==profile:
                    return True
        except (psutil.Error,OSError,ValueError):
            continue
    return False


def open_login():
    with file_lock(session_root()/'session.lock'):
        url = live_endpoint()
        if url and configuration().get('browser_mode') == 'headless':
            with socket_for(url) as ws:
                command(ws, 'Browser.close')
            for _ in range(30):
                if not live_endpoint():
                    break
                time.sleep(.1)
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


def refresh_page(url):
    """Visit YouTube in a background tab so the browser can update its own session."""
    with socket_for(url) as ws:
        target = command(ws, 'Target.createTarget', {'url': 'https://www.youtube.com/', 'background': True})['targetId']
    try:
        # Use a target-scoped CDP session; no cookie values cross the web API.
        with socket_for(url) as ws:
            session = command(ws, 'Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                command.sequence = getattr(command, 'sequence', 0) + 1
                identity = command.sequence
                ws.send(json.dumps({'id': identity, 'sessionId': session, 'method': 'Runtime.evaluate',
                                    'params': {'expression': 'document.readyState', 'returnByValue': True}}))
                response = json.loads(ws.recv(timeout=2))
                while response.get('id') != identity:
                    response = json.loads(ws.recv(timeout=2))
                if response.get('result', {}).get('result', {}).get('value') == 'complete':
                    break
                time.sleep(.2)
    except Exception:
        pass  # Offline/slow page: persisted cookies may still work for yt-dlp.
    finally:
        try:
            with socket_for(url) as ws:
                command(ws, 'Target.closeTarget', {'targetId': target})
        except Exception:
            pass


def cookies_for_download():
    if not configuration().get('enabled'):
        return None
    owned = None
    with file_lock(session_root()/'session.lock'):
        url = live_endpoint()
        try:
            if not url:
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


def mark_auth_required():
    if configuration().get('enabled'):
        # A download may fail after a later interactive login; serialize metadata writes.
        with file_lock(session_root()/'session.lock'):
            save_state(state='SIGN_IN_REQUIRED')


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
            if not configuration().get('enabled'):
                raise YouTubeSessionError('Bấm Kết nối YouTube và đăng nhập trước khi kiểm tra.')
            cookies_for_download()
            result = status()
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
