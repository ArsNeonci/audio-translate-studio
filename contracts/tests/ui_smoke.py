"""The built UI in a real browser (the installed Microsoft Edge, through Playwright), served by the local API as the installed app
serves it: launch link -> session cookie, every page, client-side navigation, a saved workflow's detail, a rule added through
the form, language and theme that survive a reload.

    npm run build
    .venv\\Scripts\\python.exe contracts\\tests\\ui_smoke.py [--shots <folder>]

Uses a temporary data folder seeded by seed_app_data.py and no licence, so only what works without one is exercised.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_app_contract as harness  # noqa: E402

ROOT = harness.ROOT
failures = []


def check(name, ok, detail=''):
    print(f'{"PASS" if ok else "FAIL"}  {name}' + (f'  ({detail})' if detail and not ok else ''))
    if not ok: failures.append(name)


def main():
    shots = Path(sys.argv[sys.argv.index('--shots') + 1]) if '--shots' in sys.argv else None
    if not (ROOT / 'out' / 'index.html').is_file(): raise SystemExit('No build yet: run `npm run build` first.')
    work = Path(tempfile.mkdtemp(prefix='ui-smoke-'))
    api = None
    try:
        seeded = subprocess.run([sys.executable, str(HERE / 'seed_app_data.py'), str(work / 'data')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        if seeded.returncode: raise SystemExit(seeded.stderr[-1500:])
        ids = json.loads(seeded.stdout.strip().splitlines()[-1])
        api = harness.start_api(work, ui=ROOT / 'out')
        base, token = api[1], api[2]
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 1360, 'height': 900})
            page = context.new_page()
            problems = []
            page.on('console', lambda m: problems.append(f'console.{m.type}: {m.text[:160]}') if m.type in ('error', 'warning') else None)
            page.on('pageerror', lambda e: problems.append(f'pageerror: {str(e)[:160]}'))
            page.on('response', lambda r: problems.append(f'HTTP {r.status} {r.request.method} {r.url.replace(base, "")}') if r.status >= 400 else None)
            settle = lambda: page.wait_for_load_state('networkidle')

            # Signing in
            response = page.goto(base + '/')
            check('a page without a session is refused with a note', response.status == 403 and 'shortcut' in page.inner_text('body'))
            problems.clear()
            page.goto(base + '/?launch=' + 'x' * 43)
            check('a wrong launch link gets no session', not [c for c in context.cookies() if c['name'] == 'audio_session'])
            problems.clear()
            page.goto(f'{base}/?launch={token}'); settle()
            cookie = next((c for c in context.cookies() if c['name'] == 'audio_session'), None)
            check('the launch link leaves the address clean', page.url == base + '/', page.url)
            check('the session cookie is HttpOnly and SameSite=Strict', bool(cookie) and cookie['httpOnly'] and cookie['sameSite'] == 'Strict', str(cookie))
            check('the page cannot read the cookie', page.evaluate('document.cookie') == '')

            # Every page loads cleanly
            pages = [('/', 'Tạo Audio Việt Nam'), ('/history', 'Lịch sử'), ('/tools', 'Sử dụng công cụ đơn'), ('/reprocess', 'Tạo lại quy trình'),
                     ('/rules', None), ('/settings', 'Cài đặt hệ thống'), ('/license', 'Giấy phép của máy này'),
                     (f'/history/view?id={ids["completed"]}', '#000001'), (f'/tools/view?id={ids["tool"]}', '#000001')]
            for path, heading in pages:
                problems.clear()
                page.goto(base + path); settle()
                title = page.locator('h1').first.inner_text() if page.locator('h1').count() else ''
                check(f'{path.split("?")[0]} opens without console or network errors', not problems and (heading is None or heading in title), f'{title!r} {problems[:3]}')
                if shots: page.screenshot(path=str(shots / (path.strip('/').replace('/', '_').split('?')[0] or 'home') + '.png'), full_page=True)
            problems.clear()
            page.goto(f'{base}/history/view'); settle()
            check('a detail page without an id says so', 'không tồn tại' in page.inner_text('main'))
            page.goto(f'{base}/history/view?id=00000000-0000-4000-8000-000000000000'); settle()
            check('a detail page of an unknown id shows an error, not a blank page', 'không tồn tại' in page.inner_text('main').lower() or 'not found' in page.inner_text('main').lower(), page.inner_text('main')[:120])
            problems.clear()

            # Client-side navigation through the header
            page.goto(base + '/'); settle()
            for label, path in (('Lịch sử', '/history'), ('Công cụ', '/tools'), ('Tạo lại', '/reprocess'), ('Quy tắc cộng đồng', '/rules'), ('Cài đặt', '/settings'), ('Giấy phép', '/license'), ('Studio', '/')):
                page.locator('nav.site-nav').get_by_text(label, exact=True).click()
                try: page.wait_for_url(base + path, timeout=15000)
                except Exception: pass
                settle()
                check(f'the header link "{label}" goes to {path}', page.url == base + path, page.url)
            check('navigating around raised no errors', not problems, str(problems[:3]))

            # History -> detail
            page.goto(base + '/history'); settle()
            first = page.locator(f'a[href="/history/view?id={ids["completed"]}"]').first
            try: first.wait_for(timeout=15000)
            except Exception: pass
            check('History lists all three workflows, each with a link to its detail', page.locator('a[href^="/history/view?id="]').count() >= 3 and first.count() == 1)
            first.click(); page.wait_for_url('**/history/view?id=*'); settle()
            check('the link opens the detail page', '#000001' in page.locator('h1').first.inner_text())
            check('the detail page lists the saved files with download links', page.locator('a[href*="/files/"][href$="/download"]').count() >= 5, str(page.locator('a').evaluate_all('e => e.map(x => x.getAttribute("href"))')[:12]))
            download = page.request.get(base + page.locator('a[href*="/download"]').first.get_attribute('href'))
            check('a download link answers with the file', download.status == 200 and len(download.body()) > 0, str(download.status))

            # A rule added through the form
            page.goto(base + '/rules'); settle()
            page.get_by_role('button', name='Thêm quy tắc').first.click()
            page.get_by_label('Từ gốc').fill('测试') if page.get_by_label('Từ gốc').count() else page.locator('.rule-form input').nth(0).fill('测试')
            page.locator('.rule-form input').nth(1).fill('thử nghiệm')
            page.locator('.rule-form button[type=submit]').click()
            try: page.wait_for_function('document.querySelector(\".rules-section\").innerText.includes(\"thử nghiệm\")', timeout=15000)
            except Exception: pass
            check('a rule added through the form appears in the list', '测试' in page.inner_text('.rules-section') and 'thử nghiệm' in page.inner_text('.rules-section'))
            page.reload(); settle()
            check('the rule is still there after a reload (saved by the API)', '测试' in page.inner_text('.rules-section'))
            page.once('dialog', lambda dialog: dialog.accept())   # a native confirm, if the page asks one
            page.locator('button.rule-icon-delete').last.click()
            try: page.wait_for_function('!document.querySelector(\".rules-section\").innerText.includes(\"测试\")', timeout=15000)
            except Exception: pass
            check('deleting the rule removes it', '测试' not in page.inner_text('.rules-section'), page.inner_text('.rules-section')[:200])

            # Language and theme survive a reload (they live in this browser, per address: the port must stay the same)
            page.goto(base + '/settings'); settle()
            page.get_by_role('button', name='English').click()
            page.get_by_role('button', name='Dark').click() if page.get_by_role('button', name='Dark').count() else page.get_by_role('button', name='Tối').click()
            page.reload(); settle()
            check('the English language is kept after a reload', page.locator('html').get_attribute('lang') in ('vi', 'en') and 'Settings' in page.inner_text('h1') or 'System' in page.inner_text('h1'), page.inner_text('h1'))
            check('the dark theme is kept after a reload', page.locator('html').get_attribute('data-theme') == 'dark')
            if shots: page.screenshot(path=str(shots / 'settings_dark_en.png'), full_page=True)
            problems.clear()

            # The page cannot be used from another origin: a state change from a page on another local port is refused
            other = context.new_page()
            other.goto('about:blank')
            result = other.evaluate(f'''async () => (await fetch("{base}/api/rules", {{method: "POST", credentials: "include", headers: {{"Content-Type": "application/json"}},
                                                  body: JSON.stringify({{source: "x", replacement: "y"}})}}).then(r => r.status).catch(() => "blocked"))''')
            check('a page from elsewhere cannot add a rule through the browser', result in ('blocked', 403), str(result))
            browser.close()
        print(f'\n{len(failures)} failed' + (f': {failures}' if failures else ''))
        return 1 if failures else 0
    finally:
        if api: harness.stop_server(api[0])
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
