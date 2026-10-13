"""CLI entry point; the path is fixed by lib/server/worker-client.ts."""
import runpy

runpy.run_module('audio_translate.workflow.scheduling', run_name='__main__', alter_sys=True)
