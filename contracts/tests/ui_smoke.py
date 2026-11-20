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
    if not (ROOT / 'web' / 'out' / 'index.html').is_file(): raise SystemExit('No build yet: run `npm run build` in web/ first.')
    work = Path(tempfile.mkdtemp(prefix='ui-smoke-'))
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
            page.on('console', lambda m: problems.append(f'console.{m.type}: {m.text[:160]}') if m.type in ('error', 'warning') else None)
            page.on('pageerror', lambda e: problems.append(f'pageerror: {str(e)[:160]}'))
            page.on('response', lambda r: problems.append(f'HTTP {r.status} {r.request.method} {r.url.replace(base, "")}') if r.status >= 400 else None)
            def settle():
                try: page.wait_for_load_state('networkidle', timeout=20000)
                except Exception: page.wait_for_timeout(1500)   # a busy machine can keep the page's polling from ever looking idle; the next check waits for what it needs itself

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

            # The free RAM a translation waits for: a slider from 4 to 8 GiB that saves by itself
            slider = page.locator('.memory-slider input[type=range]')
            slider.wait_for(timeout=15000)
            check('the memory slider spans 4 to 8 GiB in steps of 0.5 and starts at the one-slot default',
                  (slider.get_attribute('min'), slider.get_attribute('max'), slider.get_attribute('step'), slider.input_value()) == ('4', '8', '0.5', '5.5'),
                  (slider.get_attribute('min'), slider.get_attribute('max'), slider.input_value()))
            slider.focus(); page.keyboard.press('Home')                      # the lowest level
            page.wait_for_function('document.body.innerText.includes("uses the new level at once")', timeout=15000)
            kept = page.evaluate('fetch("/api/settings/translation-memory").then(r => r.json())')
            check('moving the slider saves the level at once', kept['start_free_gib'] == 4.0 and kept['customised'] is True, kept)
            page.reload(); settle()
            check('the saved level is shown again after a reload', page.locator('.memory-slider input[type=range]').input_value() == '4', page.locator('.memory-slider input[type=range]').input_value())
            check('below the default there is a warning and a way back', 'Below the default' in page.inner_text('body') and page.get_by_role('button', name='Reset to default (5.5 GiB)').count() == 1)
            page.get_by_role('button', name='Reset to default (5.5 GiB)').click()
            page.wait_for_function('document.body.innerText.includes("uses the new level at once") && !document.body.innerText.includes("Reset to default")', timeout=15000)
            check('the way back restores 5.5 GiB', page.evaluate('fetch("/api/settings/translation-memory").then(r => r.json())')['start_free_gib'] == 5.5)
            problems.clear()

            # Video merge (no real dialog in a test: the dialog and the estimate answers are given by the test)
            clips = [{'path': 'C:\v\a.mp4', 'name': 'a.mp4', 'duration_ms': 37000, 'width': 1920, 'height': 1080, 'fps': 25, 'codec': 'h264', 'size': 1},
                     {'path': 'C:\v\b.mov', 'name': 'b.mov', 'duration_ms': 5000, 'width': 1280, 'height': 720, 'fps': 30, 'codec': 'hevc', 'size': 1}]
            page.route('**/api/video/pick', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'files': clips})))
            estimate = {'files': clips, 'resolutions': ['keep', '1080', '720', '480'], 'resolution': 'keep', 'quality': 'high', 'free_bytes': 50 * 1024 ** 3, 'needed_bytes': None, 'enough': None,
                        'plan': {'mode': 'encode', 'repeats': None, 'size_bytes': None, 'bytes_per_hour': 3_700_000_000}}
            page.route('**/api/video/estimate', lambda route, request: route.fulfill(status=200, content_type='application/json',
                       body=json.dumps({**estimate, 'files': [clips[i] for i in ([1, 0] if json.loads(request.post_data)['paths'][0].endswith('b.mov') else [0, 1])]})))
            page.goto(base + '/'); settle()
            # Form kit: every feature is a card; nothing hides behind a toggle; three sizes of text; equal gaps; big controls
            check('Studio: no feature hides behind a toggle', page.locator('.hero details').count() == 0 and page.locator('.fsec').count() >= 5)
            gaps = page.evaluate('''() => { const cards = [...document.querySelectorAll(".fk-stack > .fsec")]; return cards.slice(1).map((card, index) => Math.round(card.getBoundingClientRect().top - cards[index].getBoundingClientRect().bottom)); }''')
            check('Studio: the cards are the same distance apart, and far enough to tell them apart', len(set(gaps)) == 1 and gaps[0] >= 28, str(gaps))
            sizes = page.evaluate('''() => ({ title: getComputedStyle(document.querySelector(".fsec-title")).fontSize, desc: getComputedStyle(document.querySelector(".fsec-desc")).fontSize,
                label: getComputedStyle(document.querySelector(".fsec .voice-style-select > span")).fontSize, input: getComputedStyle(document.querySelector(".subtitle-options input")).fontSize,
                small: [...document.querySelectorAll(".fsec small")].map(e => getComputedStyle(e).fontSize) })''')
            check('Studio: three text sizes (name 20, setting 16, description 14)', sizes['title'] == '20px' and sizes['label'] == '16px' and sizes['input'] == '16px' and sizes['desc'] == '14px' and set(sizes['small']) <= {'14px'}, str(sizes))
            boxes = page.evaluate('''() => [...document.querySelectorAll(".fsec input[type=number], .fsec select, .fsec .voice-style-option, .fsec .auto-tts-toggle")].map(e => Math.round(e.getBoundingClientRect().height))''')
            check('Studio: every field, chip and checkbox card is at least 48 px tall', boxes and min(boxes) >= 48, str(boxes))
            check('Studio: the checkbox is big', page.locator('.auto-tts-toggle input').first.evaluate('e => e.getBoundingClientRect().width') >= 26)
            for theme in ('light', 'dark'):
                page.evaluate(f'document.documentElement.dataset.theme = "{theme}"'); page.wait_for_timeout(600)   # buttons fade between the themes
                page.screenshot(path=str(Path(tempfile.gettempdir()) / f'studio-{theme}.png'), full_page=True)
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.get_by_role('button', name='Choose videos…').click()
            page.wait_for_selector('.video-list li >> nth=1', timeout=10000)
            check('Studio: the chosen videos are listed in order', page.locator('.video-name').all_inner_texts() == ['a.mp4', 'b.mov'], str(page.locator('.video-name').all_inner_texts()))
            page.get_by_role('button', name='Move down').first.click()
            check('Studio: a video can be moved down', page.locator('.video-name').all_inner_texts() == ['b.mov', 'a.mp4'], str(page.locator('.video-name').all_inner_texts()))
            page.wait_for_function('document.body.innerText.includes("per hour of voice")', timeout=10000)
            check('Studio: the size per hour of voice and the free disk are shown', 'free disk space 50.0 GB' in page.inner_text('body'))
            check('Studio: resolution, quality and the logo template can be chosen', page.locator('.video-options select').count() == 3)
            tick = page.locator('.video-burn input[type=checkbox]').first   # the subtitles tick: the label text is free to change
            check('Studio: the subtitled-video tick is offered and ticked by default (it can be unticked)', tick.is_checked() is True)
            page.wait_for_selector('.video-burn .alert', timeout=5000)
            ultra = page.locator('.video-burn input[type=checkbox]').nth(1)   # the second tick of the block: Ultra fast (the first is the subtitles)
            check('Studio: Ultra fast is ticked by default and can be turned off', ultra.is_checked() is True)
            check('Studio: with Ultra fast the warning is the one-pass one, and the tick is the only confirmation', 'Ultra fast, one pass' in page.inner_text('.video-burn') or 'about 18 seconds per minute' in page.inner_text('.video-burn') or 'Ultra fast: about' in page.inner_text('.video-burn'), page.inner_text('.video-burn')[-200:])
            ultra.uncheck()
            check('Studio: without Ultra fast the warning is the second-step one', 're-encodes the whole video' in page.inner_text('.video-burn') and page.get_by_label('I understand it takes longer').count() == 0)
            check('Studio: the .srt settings stay in their own box with the defaults 84 / 1', page.locator('.subtitle-options input[type=number]').evaluate_all('els => els.map(e => e.value)') == ['84', '1'])
            page.evaluate('document.documentElement.dataset.theme = "dark"')
            check('Studio: the video box follows the dark theme', page.evaluate('getComputedStyle(document.querySelector(".video-picker").closest(".fsec")).backgroundColor') != 'rgb(255, 255, 255)')
            page.evaluate('document.documentElement.dataset.theme = "light"')
            # The last choices are remembered (how to work, not the clips): they come back after a reload, and an empty storage gives the defaults
            page.locator('.subtitle-options input[type=number]').first.fill('60'); page.wait_for_timeout(300)
            page.reload(); settle()
            check('Studio: the clips are not remembered (no video is listed after a reload)', page.locator('.video-name').count() == 0)
            check('Studio: the subtitle settings come back after a reload', page.locator('.subtitle-options input[type=number]').evaluate_all('els => els.map(e => e.value)')[0] == '60')
            page.get_by_role('button', name='Choose videos…').click()
            page.wait_for_selector('.video-burn input[type=checkbox]', timeout=10000)
            ticks = page.locator('.video-burn input[type=checkbox]')
            page.wait_for_function('document.querySelectorAll(".video-burn input[type=checkbox]")[1] && !document.querySelectorAll(".video-burn input[type=checkbox]")[1].checked', timeout=10000)
            check('Studio: the last choices come back after a reload (Ultra fast stays unticked)', ticks.nth(0).is_checked() is True and ticks.nth(1).is_checked() is False)
            page.evaluate('localStorage.removeItem("audio-studio-settings-v1")'); page.reload(); settle()
            page.get_by_role('button', name='Choose videos…').click()
            page.wait_for_selector('.video-burn input[type=checkbox]', timeout=10000)
            check('Studio: without a memory the subtitle settings are the defaults again', page.locator('.subtitle-options input[type=number]').evaluate_all('els => els.map(e => e.value)') == ['84', '1'])
            check('Studio: without a memory the defaults are back (subtitles and Ultra fast ticked)', page.locator('.video-burn input[type=checkbox]').nth(0).is_checked() is True and page.locator('.video-burn input[type=checkbox]').nth(1).is_checked() is True)
            page.evaluate('localStorage.setItem("audio-studio-settings-v1", "{ not json")'); page.reload(); settle()
            check('Studio: a damaged memory is ignored (the page still opens)', page.locator('.fsec').count() >= 5)
            page.evaluate('localStorage.removeItem("audio-studio-settings-v1")')
            page.goto(base + '/tools'); settle()
            page.get_by_role('button', name='6. Vietnamese voice + Video → Video').click()
            for theme in ('light', 'dark'):
                page.evaluate(f'document.documentElement.dataset.theme = "{theme}"'); page.wait_for_timeout(600)   # buttons fade between the themes
                page.screenshot(path=str(Path(tempfile.gettempdir()) / f'tools-{theme}.png'), full_page=True)
            page.evaluate('document.documentElement.dataset.theme = "light"')
            check('Tools: tool 6 (video) asks for a voice made by the app', 'Voice (made by this app)' in page.inner_text('body'))
            page.get_by_role('button', name='5. Vietnamese voice → Subtitles (.srt)').click()
            check('Tools: tool 5 (subtitles) asks for a voice and offers the cue settings', page.locator('.subtitle-options input[type=number]').count() == 2 and page.get_by_role('button', name='Make subtitles').is_disabled())
            check('Tools: the subtitles come before the video, following the flow', [t[:2] for t in page.locator('.tool-card').all_inner_texts()] == ['1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.'] and page.locator('.tool-card').all_inner_texts()[4].startswith('5. Vietnamese voice → Subtitles') and page.locator('.tool-card').all_inner_texts()[5].startswith('6. Vietnamese voice + Video'))
            # A single tool refuses a file of the wrong type or size when it is chosen, not when the work starts
            page.get_by_role('button', name='2. Chinese Text → Vietnamese Text').click()
            page.set_input_files('input[type=file]', {'name': 'a.png', 'mimeType': 'image/png', 'buffer': b'x'})
            check('Tools: a picture is refused at once for a text tool', 'cannot be used here' in page.inner_text('main') and 'TXT, MD, JSONL' in page.inner_text('main') and 'a.png' not in page.inner_text('.file-picker'))
            page.set_input_files('input[type=file]', {'name': 'a.txt', 'mimeType': 'text/plain', 'buffer': 'ni hao'.encode()})
            check('Tools: a text file is taken in and the warning goes', 'cannot be used here' not in page.inner_text('main') and 'a.txt' in page.inner_text('.file-picker'))
            page.get_by_role('button', name='1. Chinese Audio → Chinese Text').click()
            page.set_input_files('input[type=file]', {'name': 'a.txt', 'mimeType': 'text/plain', 'buffer': b'x'})
            check('Tools: a text file is refused for the audio tool', 'WAV, MP3' in page.inner_text('main') and 'a.txt' not in page.inner_text('.file-picker'))
            # The runs of the single tools carry stop / continue / run again like the workflows
            def tool_run(number, status, steps):
                return {'id': f'00000000-0000-4000-8000-{number:012d}', 'workflow_no': number, 'storage_scope': 'tools', 'tool_type': 'translation', 'name': f'run {number}', 'input_file': f'in{number}.txt',
                        'created_at': '2026-10-15T10:00:00+00:00', 'status': status, 'progress': 10, 'duration_ms': 0, 'tool_steps': steps, 'files': []}
            runs = [tool_run(1, 'TRANSLATING', ['TRANSLATION']), tool_run(2, 'PAUSED', ['TRANSLATION']), tool_run(3, 'COMPLETED', ['TRANSLATION']), tool_run(4, 'FAILED', ['TRANSLATION'])]
            page.route('**/api/tools?*', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'jobs': runs, 'total': 4, 'page': 1, 'limit': 20, 'statuses': ['COMPLETED']})))
            page.goto(base + '/tools'); settle()
            page.wait_for_selector('.history-list tbody tr', timeout=10000)
            rows = page.locator('.history-list tbody tr')
            def titles(i): return [b.get_attribute('title') for b in rows.nth(i).locator('.history-actions button, .history-actions a').all()]
            check('Tools list: a running tool can be paused, not run again', 'Pause stage' in titles(0) and 'Run the tool again' not in titles(0), str(titles(0)))
            check('Tools list: a paused tool can be continued or run again', 'Resume stage' in titles(1) and 'Run the tool again' in titles(1), str(titles(1)))
            check('Tools list: a finished or failed tool can be run again', 'Run the tool again' in titles(2) and 'Run the tool again' in titles(3), str(titles(2)) + str(titles(3)))
            page.unroute('**/api/tools?*')
            page.goto(base + '/reprocess'); settle()
            check('Reprocess: Subtitles is a restart point', 'Subtitles' in page.locator('select').nth(1).inner_text())
            check('Reprocess: Video merge is a restart point', 'Video merge' in page.locator('select').nth(1).inner_text())
            check('Reprocess: Subtitles into video is a restart point', 'Subtitles into video' in page.locator('select').nth(1).inner_text())
            page.unroute('**/api/video/pick'); page.unroute('**/api/video/estimate')


            # Manual translation, tool 7 (split text), a file loaded into a run, and the logo templates
            def accept(dialog):   # an earlier once-handler may already have taken the dialog
                try: dialog.accept()
                except Exception: pass
            def solid_png(width, height, rgba):
                import struct, zlib
                def chunk(kind, data): return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
                raw = b''.join(b'\x00' + bytes(rgba) * width for _ in range(height))
                return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
            page.goto(base + '/'); settle()
            toggle = page.get_by_label('Translate by hand')
            order = page.evaluate("""() => { const before = (a, b) => !!(document.querySelector(a).compareDocumentPosition(document.querySelector(b)) & 4);
                return before('.voice-select', '.manual-toggle') && before('.manual-toggle', '.mode-select'); }""")
            check('Studio: translating by hand sits between the voice and the translation mode, off by default', toggle.is_checked() is False and order)
            toggle.check()
            check('Studio: translating by hand hides the translation mode', page.locator('.mode-select').count() == 0)
            page.wait_for_selector('.manual-split-note', timeout=5000)
            check('Studio: translating by hand says the Chinese text is cut with tool 7\'s part size', '3,000 characters' in page.inner_text('.manual-split-note'))
            toggle.uncheck()
            check('Studio: Drama is the default forms of address', page.locator('.address-select [aria-checked=true]').inner_text() == 'Drama')
            page.goto(base + '/tools'); settle()
            page.get_by_role('button', name='7. Split text').click()
            check('Tools: tool 7 offers the part size and the instruction for the chatbot', 'Most characters per part' in page.inner_text('main') and 'Keep the number [n]' in page.locator('.split-prompt textarea').input_value())
            page.fill('.split-tool input[type=number]', '100')
            check('Tools: a part size outside 500 to 20,000 is refused at once', 'not valid' in page.inner_text('.split-tool') and page.get_by_role('button', name='Split the text').is_disabled())
            page.goto(f'{base}/reprocess?id={ids["completed"]}&step=MODERATION'); settle()
            for theme in ('light', 'dark'):
                page.evaluate(f'document.documentElement.dataset.theme = "{theme}"'); page.wait_for_timeout(600)   # buttons fade between the themes
                page.screenshot(path=str(Path(tempfile.gettempdir()) / f'reprocess-{theme}.png'), full_page=True)
            page.evaluate('document.documentElement.dataset.theme = "light"')
            check('Reprocess: from the Studio link the stage is chosen and the file loader is open',
                  page.locator('.import-panel').count() == 1 and page.locator('.import-panel [aria-checked=true]').inner_text() == 'Load files' and page.locator('.import-panel input[type=file]').count() == 1)
            # Several translated parts: chosen at once, sorted by name, each with its own line of the report, and moved with ↑ ↓ (the draft answers are given by the test)
            parts_report = {'mode': 'numbered', 'found': 2, 'rows': 4, 'blocked': [], 'preview': [], 'missing': [], 'duplicate': [], 'unknown': [], 'empty': [],
                            'parts': [{'id': 1, 'name': 'part-001.md', 'first': 1, 'last': 1, 'count': 1, 'dropped_lines': 1, 'han': False, 'empty': False, 'repeats': [], 'repeats_of': []},
                                      {'id': 2, 'name': 'part-002.md', 'first': 2, 'last': 2, 'count': 1, 'dropped_lines': 0, 'han': False, 'empty': False, 'repeats': [], 'repeats_of': []}]}
            orders = []
            page.route('**/import?*', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'import_id': 'a' * 32, 'ready': True, 'report': {**parts_report, 'parts': parts_report['parts'][:1]}})))
            page.route('**/import/*/parts?*', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'import_id': 'a' * 32, 'part': {'id': 2, 'name': 'part-002.md', 'size': 5}})))
            page.route('**/import/*/check', lambda route, request: (orders.append(json.loads(request.post_data)['order']), route.fulfill(status=200, content_type='application/json', body=json.dumps({'import_id': 'a' * 32, 'ready': True, 'report': parts_report})))[1])
            page.set_input_files('.import-panel input[type=file]', [{'name': 'part-002.md', 'mimeType': 'text/markdown', 'buffer': '[2] Hai'.encode()}, {'name': 'part-001.md', 'mimeType': 'text/markdown', 'buffer': '[1] Một'.encode()}])
            page.wait_for_function('document.querySelectorAll(".import-panel .video-list li").length === 2 && document.body.innerText.includes("paragraphs [2]–[2]")', timeout=10000)
            check('Reprocess: several files are taken at once, sorted by name, and each shows what it holds', page.locator('.import-panel .video-name').all_inner_texts() == ['part-001.md', 'part-002.md']
                  and 'Dropped 1 lines' in page.locator('.import-panel .video-list li').first.inner_text())
            page.locator('.import-panel .video-list li').first.get_by_role('button', name='Move down').click()
            page.wait_for_function('document.querySelector(".import-panel .video-name").innerText === "part-002.md"', timeout=5000)
            page.wait_for_timeout(800)
            check('Reprocess: moving a file sends the new order to be checked', orders[-1:] == [[2, 1]], str(orders))
            page.evaluate('document.documentElement.dataset.theme = "dark"')
            check('Reprocess: the file list follows the dark theme', page.evaluate('getComputedStyle(document.querySelector(".import-panel")).backgroundColor') != 'rgb(255, 255, 255)')
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.unroute('**/import?*'); page.unroute('**/import/*/parts?*'); page.unroute('**/import/*/check')
            page.get_by_role('radio', name='Use the existing result').click()
            check('Reprocess: the loader closes when the existing result is used', page.locator('.import-panel input[type=file]').count() == 0)

            page.goto(base + '/overlays'); settle()
            check('Logos: the page opens empty, with the image library and the template list', 'No images yet' in page.inner_text('main') and 'No templates yet' in page.inner_text('main'))
            page.set_input_files('input[type=file]', {'name': 'logo.png', 'mimeType': 'image/png', 'buffer': solid_png(200, 100, (220, 30, 30, 255))})
            page.wait_for_selector('.overlay-asset', timeout=10000)
            check('Logos: an added picture appears in the library', page.locator('.overlay-asset').count() == 1 and 'logo' in page.inner_text('.overlay-asset') and '200×100' in page.inner_text('.overlay-asset'))
            page.get_by_role('button', name='New template').click()
            check('Logos: the frame follows the shape (landscape 16:9 first, portrait 9:16 on request)', page.locator('.overlay-board.landscape').count() == 1)
            ratio = lambda: (lambda b: round(b['width'] / b['height'], 2))(page.locator('.overlay-board').bounding_box())
            check('Logos: the landscape frame is 16:9', ratio() == 1.78, str(ratio()))
            page.get_by_label('Video frame').select_option('portrait')
            check('Logos: the portrait frame is 9:16', ratio() == 0.56, str(ratio()))
            page.get_by_label('Video frame').select_option('landscape')
            page.get_by_role('button', name='Put on the frame').click()
            page.wait_for_selector('.overlay-item.selected', timeout=5000)
            page.locator('.overlay-board').scroll_into_view_if_needed()
            first = page.locator('.overlay-item').bounding_box()
            page.mouse.move(first['x'] + first['width'] / 2, first['y'] + first['height'] / 2); page.mouse.down()
            page.mouse.move(first['x'] + first['width'] / 2 + 120, first['y'] + first['height'] / 2 + 50, steps=6); page.mouse.up()
            dragged = page.locator('.overlay-item').bounding_box()
            check('Logos: a picture is moved by dragging', dragged['x'] > first['x'] + 90 and dragged['y'] > first['y'] + 30, f"{first} -> {dragged}")
            x_before = int(page.get_by_label('Horizontal (px)').input_value())
            page.locator('.overlay-item').focus(); page.keyboard.press('Shift+ArrowRight')
            check('Logos: Shift and an arrow key move it 10 pixels of the 1920 px frame', int(page.get_by_label('Horizontal (px)').input_value()) == x_before + 10)
            page.get_by_label('Width (px)').fill('1900'); page.get_by_label('Width (px)').blur()
            inside = page.evaluate("""() => { const b = document.querySelector('.overlay-board').getBoundingClientRect(), i = document.querySelector('.overlay-item').getBoundingClientRect();
                return i.left >= b.left - 1 && i.right <= b.right + 1 && i.top >= b.top - 1 && i.bottom <= b.bottom + 1; }""")
            check('Logos: a picture can never leave the frame', inside)
            page.get_by_label('Width (px)').fill('400'); page.get_by_label('Width (px)').blur()
            check('Logos: the subtitle area is marked on the frame', page.locator('.overlay-subzone').count() == 1)
            check('Logos: an unnamed template cannot be saved', page.get_by_role('button', name='Save template').is_disabled())
            page.get_by_label('Template name').fill('Kênh A')
            page.get_by_role('button', name='Save template').click()
            page.wait_for_selector('.overlay-templates li', timeout=10000)
            check('Logos: the saved template is listed with its frame and its pictures', 'Kênh A' in page.inner_text('.overlay-templates') and '1 images' in page.inner_text('.overlay-templates') and 'Landscape' in page.inner_text('.overlay-templates'))
            page.once('dialog', accept)
            page.locator('.overlay-asset').get_by_role('button', name='Remove the image from the library').click()
            page.wait_for_function('document.body.innerText.includes("in a template")', timeout=5000)
            check('Logos: a picture that a template uses cannot be removed from the library', page.locator('.overlay-asset').count() == 1)
            page.get_by_role('button', name='Make default').click()
            page.wait_for_selector('.overlay-badge', timeout=5000)
            check('Logos: a template is made the default of its frame', page.locator('.overlay-badge').inner_text() == 'Default')
            clip = {'path': 'C:\\clips\\a.mp4', 'name': 'a.mp4', 'duration_ms': 37000, 'width': 1920, 'height': 1080, 'fps': 30, 'codec': 'h264', 'size': 1000}
            page.route('**/api/video/pick', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'files': [clip]})))
            page.route('**/api/video/estimate', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps(
                {'files': [clip], 'resolutions': ['keep'], 'resolution': 'keep', 'quality': 'high', 'free_bytes': 50_000_000_000, 'needed_bytes': None, 'enough': None,
                 'plan': {'mode': 'encode', 'repeats': None, 'size_bytes': None, 'bytes_per_hour': 3_700_000_000}})))
            page.goto(base + '/'); settle()
            page.get_by_role('button', name='Choose videos…').click()
            page.wait_for_selector('.video-list li', timeout=10000)
            check('Studio: the video box offers the default logo template, and links to the page that manages them', 'Default (Kênh A)' in page.locator('.video-options').inner_text() and page.get_by_role('link', name='Manage templates →').count() == 1)
            page.unroute('**/api/video/pick'); page.unroute('**/api/video/estimate')
            page.goto(base + '/overlays'); settle()
            page.get_by_role('button', name='Edit').click()
            page.evaluate('document.documentElement.dataset.theme = "dark"')
            colour = lambda selector: page.evaluate('(s) => getComputedStyle(document.querySelector(s)).backgroundColor', selector)
            check('Logos: the editor, the frame and the library follow the dark theme', colour('.overlay-editor') != 'rgb(255, 255, 255)' and colour('.overlay-board') != 'rgb(255, 255, 255)' and colour('.overlay-asset') != 'rgb(255, 255, 255)',
                  f"{colour('.overlay-editor')} {colour('.overlay-board')} {colour('.overlay-asset')}")
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.once('dialog', accept)
            page.get_by_role('button', name='Delete template').click()
            page.wait_for_function('document.body.innerText.includes("No templates yet")', timeout=10000)
            page.once('dialog', accept)
            page.locator('.overlay-asset').get_by_role('button', name='Remove the image from the library').click()
            page.wait_for_function('document.body.innerText.includes("No images yet")', timeout=10000)
            check('Logos: the template and then the picture can be deleted', True)
            page.goto(base + '/'); settle()

            # Tools 8 (subtitle file on a video) and 9 (logo on a video): one video, estimate, the file picked at once, both themes
            shown_clip = {'path': 'C:\\clips\\a.mp4', 'name': 'a.mp4', 'duration_ms': 600000, 'width': 1920, 'height': 1080, 'fps': 30, 'codec': 'h264', 'size': 1000}
            page.route('**/api/video/pick', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps({'files': [shown_clip, {**shown_clip, 'name': 'b.mp4'}]})))
            page.route('**/api/video/render-estimate', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps(
                {'files': [shown_clip], 'resolutions': ['keep', '1080', '720', '480'], 'resolution': 'keep', 'quality': 'high', 'free_bytes': 50_000_000_000, 'needed_bytes': 1_000_000_000, 'enough': True,
                 'plan': {'mode': 'encode', 'seconds': 180, 'size_bytes': 600_000_000}})))
            page.goto(base + '/tools'); settle()
            page.get_by_role('button', name='8. Video + Subtitle file → Subtitled video').click()
            check('Tools: tool 8 asks for one video and a subtitle file, and cannot run yet', page.get_by_role('button', name='Add the subtitles').is_disabled() and page.locator('.render-tool input[type=file]').count() == 1)
            page.get_by_role('button', name='Choose videos…').click()
            page.wait_for_selector('.render-clip', timeout=10000)
            check('Tools: tool 8 uses the first video when several are chosen, and says so', 'a.mp4' in page.inner_text('.render-clip') and 'first one you chose' in page.inner_text('.render-tool'))
            page.wait_for_function('document.body.innerText.includes("Takes about 3 min")', timeout=10000)
            check('Tools: the time and size of the render are shown', 'about 3 min' in page.inner_text('.video-estimate') and '572 MB' in page.inner_text('.video-estimate'))
            page.set_input_files('.render-tool input[type=file]', {'name': 'sub.txt', 'mimeType': 'text/plain', 'buffer': b'x'})
            check('Tools: a file that is not .srt or .vtt is refused at once', 'cannot be used here' in page.inner_text('.render-tool') and page.get_by_role('button', name='Add the subtitles').is_disabled())
            page.set_input_files('.render-tool input[type=file]', {'name': 'sub.srt', 'mimeType': 'application/x-subrip', 'buffer': b'1\n00:00:00,000 --> 00:00:01,000\nxin chao\n'})
            check('Tools: with a video and a subtitle file the button is ready (a licence is the only thing missing)', 'sub.srt' in page.inner_text('.render-tool .file-picker'))
            check('Tools: tool 8 offers no logo by default', page.locator('.render-tool select').first.input_value() == 'none')
            page.evaluate('document.documentElement.dataset.theme = "dark"')
            check('Tools: the render box follows the dark theme', page.evaluate('getComputedStyle(document.querySelector(".render-tool .fsec")).backgroundColor') != 'rgb(255, 255, 255)')
            page.evaluate('document.documentElement.dataset.theme = "light"')
            page.get_by_role('button', name='9. Video → Video with logo').click()
            page.wait_for_function('document.body.innerText.includes("no logo template yet")', timeout=10000)
            check('Tools: tool 9 needs a logo template and points to the page that makes them', 'no logo template yet' in page.inner_text('.render-tool') and page.get_by_role('link', name='Manage templates →').count() == 1)
            check('Tools: tool 9 takes no subtitle file', page.locator('.render-tool input[type=file]').count() == 0)
            page.unroute('**/api/video/pick'); page.unroute('**/api/video/render-estimate')

            # A perpetual licence and a lease that lapsed offline (the licence answers are given by the test)
            def licence(body):
                page.route('**/api/license', lambda route, request: route.fulfill(status=200, content_type='application/json', body=json.dumps(body)) if request.method == 'GET' else route.continue_())
            licence({'http_status': 200, 'product_id': 'audio-translate-plus', 'status': 'ACTIVE', 'expires_at': '2126-10-14T00:00:00+00:00', 'sequence': 1, 'lease': 'VALID', 'perpetual': True})
            page.goto(base + '/license'); settle()
            check('Licence page: a perpetual licence reads Vĩnh viễn', 'Expires: Perpetual' in page.inner_text('body'), page.locator('[role=status]').first.inner_text())
            check('Licence page: no plan to buy for a perpetual licence', page.get_by_role('button', name='Buy / renew a plan').count() == 0)
            page.unroute('**/api/license')
            licence({'http_status': 200, 'product_id': 'audio-translate-plus', 'status': 'ACTIVE', 'expires_at': '2026-12-01T00:00:00+00:00', 'sequence': 1, 'lease': 'EXPIRED', 'perpetual': False})
            page.goto(base + '/'); settle()
            check('Studio: a lapsed lease asks to go online, not "licence expired"', 'Connect to the Internet to confirm your access again' in page.inner_text('body') and page.get_by_role('button', name='Check again').count() == 1)
            page.unroute('**/api/license')
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
