"""CLI entry point; the path is fixed by the native broker allowlist and lib/worker-client.ts."""
import runpy

runpy.run_module('audio_translate.workflow.results', run_name='__main__', alter_sys=True)
