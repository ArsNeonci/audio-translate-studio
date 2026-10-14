"""Look at the built UI in a real browser: open every page, record console errors and failed requests, save screenshots.
A scratch tool for building ui_smoke.py; it changes nothing."""
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
PAGES = ['/', '/history', '/tools', '/reprocess', '/rules', '/settings', '/license']


def main():
    work = Path(tempfile.mkdtemp(prefix='ui-explore-'))
    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else work / 'shots'
    shots.mkdir(parents=True, exist_ok=True)
    api = None
    try:
        seeded = subprocess.run([sys.executable, str(HERE / 'seed_app_data.py'), str(work / 'data')], cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
        if seeded.returncode: raise SystemExit(seeded.stderr[-1500:])
        ids = json.loads(seeded.stdout.strip().splitlines()[-1])
        api = harness.start_api(work, ui=ROOT / 'web' / 'out')
        base, token = api[1], api[2]
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context(viewport={'width': 1360, 'height': 900})
            page = context.new_page()
            problems = []
            page.on('console', lambda m: problems.append(f'console.{m.type}: {m.text[:200]}') if m.type in ('error', 'warning') else None)
            page.on('pageerror', lambda e: problems.append(f'pageerror: {str(e)[:200]}'))
            page.on('response', lambda r: problems.append(f'HTTP {r.status} {r.request.method} {r.url.replace(base, "")}') if r.status >= 400 else None)
            r = page.goto(base + '/'); print('without a session:', r.status, page.inner_text('body')[:60].replace('\n', ' '))
            page.goto(f'{base}/?launch={token}'); print('after the launch link:', page.url.replace(base, ''))
            print('cookies:', [(c['name'], c['httpOnly'], c['sameSite']) for c in context.cookies()])
            for path in PAGES + [f'/history/view?id={ids["completed"]}', f'/tools/view?id={ids["tool"]}']:
                problems.clear()
                page.goto(base + path); page.wait_for_load_state('networkidle')
                name = path.strip('/').replace('/', '_').split('?')[0] or 'home'
                page.screenshot(path=str(shots / f'{name}.png'), full_page=True)
                print(f'{path:55} h1={page.locator("h1").first.inner_text()[:40] if page.locator("h1").count() else "-"!r}  problems={problems}')
            browser.close()
        print('screenshots:', shots)
    finally:
        if api: harness.stop_server(api[0])
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
