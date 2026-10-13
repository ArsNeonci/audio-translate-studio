"""CLI entry point; the path is fixed by the native broker allowlist and lib/worker-client.ts."""
import runpy

runpy.run_module('audio_translate.core.compute_settings', run_name='__main__', alter_sys=True)
