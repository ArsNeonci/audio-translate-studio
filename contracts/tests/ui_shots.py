"""Screenshots of the built UI for a before/after comparison of a refactor.

    .venv\\Scripts\\python.exe contracts\\tests\\ui_shots.py <folder>              write the screenshots
    .venv\\Scripts\\python.exe contracts\\tests\\ui_shots.py <folder> --compare <baseline folder>   and compare each with the baseline

Pages without a time or an id on them, in Vietnamese Light, Vietnamese Dark and English Light, at one fixed size, so two runs of the
same UI give identical pixels. A comparison lists every image whose pixels differ.
"""
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
PAGES = ['settings', 'license', 'rules', 'tools', 'reprocess']
MODES = {'vi-light': ('vi', 'light'), 'vi-dark': ('vi', 'dark'), 'en-light': ('en', 'light')}


def main():
    folder = Path(sys.argv[1]); folder.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='ui-shots-')); api = None
    try:
        (work / 'data').mkdir()   # empty on purpose: no row, so no time or id can end up in a picture
        api = harness.start_api(work, ui=ROOT / 'web' / 'out')
        base, token = api[1], api[2]
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            for mode, (language, theme) in MODES.items():
                context = browser.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=1)
                context.add_init_script(f"try {{ localStorage.setItem('audio-studio-lang','{language}'); localStorage.setItem('audio-studio-theme','{theme}'); }} catch (e) {{}}")
                page = context.new_page()
                page.goto(f'{base}/?launch={token}'); page.wait_for_load_state('networkidle')
                for name in PAGES:
                    page.goto(f'{base}/{name}'); page.wait_for_load_state('networkidle'); page.wait_for_timeout(400)
                    page.screenshot(path=str(folder / f'{name}.{mode}.png'), full_page=True, animations='disabled')
                context.close()
            browser.close()
        print(f'{len(PAGES) * len(MODES)} screenshots in {folder}')
    finally:
        if api: harness.stop_server(api[0])
        shutil.rmtree(work, ignore_errors=True)
    if '--compare' in sys.argv:
        from PIL import Image, ImageChops
        baseline = Path(sys.argv[sys.argv.index('--compare') + 1]); different = []
        for image in sorted(folder.glob('*.png')):
            other = baseline / image.name
            if not other.exists(): different.append(f'{image.name}: no baseline'); continue
            a, b = Image.open(image).convert('RGB'), Image.open(other).convert('RGB')
            if a.size != b.size: different.append(f'{image.name}: size {a.size} vs {b.size}'); continue
            box = ImageChops.difference(a, b).getbbox()
            if box: different.append(f'{image.name}: pixels differ in {box}')
        print('identical to the baseline' if not different else 'DIFFERENT:\n  ' + '\n  '.join(different))
        sys.exit(1 if different else 0)


if __name__ == '__main__':
    main()
