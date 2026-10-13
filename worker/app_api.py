"""CLI entry point of the app's local API; started by the launcher (installed) or scripts/dev.cjs (development)."""
import runpy

runpy.run_module('audio_translate.api.server', run_name='__main__', alter_sys=True)
