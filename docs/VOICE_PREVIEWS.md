# System voice previews

The voice picker uses a custom popover because a native option cannot reliably
contain an independent play button. Playing a sample never changes the selected
voice and never starts TTS. Only one audio element is used per picker, with the
previous clip stopped on switching. Browser audio is requested by user clicks.

Generate all 25 samples once:

    $env:PYTHONPATH="worker"; .venv/Scripts/python.exe -m audio_translate.tts.voice_previews --wait-idle

The default blocks model loading while any workflow/tool is active. --wait-idle
waits without importing torch/TTS, then renders sequentially on CPU with one
thread and existing offline weights. --allow-active is an explicit opt-in to
resource competition; it does not cancel or modify jobs. Check each next sample
for newly active work. Failed builds can be rerun and reuse validated files.

Every clip says “Tên tôi là [voice id].” WAV samples and an atomic manifest live
in public/voice-previews and are versioned system assets, not user output or
workflow cache. Packaging copies public/ and fingerprints it. New installations
therefore play the same shipped samples without needing a model to preview.
If the model/presets change, bump VERSION and regenerate before packaging.

Playback route /api/voices/preview/{sha256} only reads validated manifest entries
and audio files; it has no synthesis fallback. Content-addressed URLs permit
immutable browser caching. Missing files disable preview buttons and display
generation status rather than secretly running a model on a click.

The voice picker and audition controls are integrated into Studio, Tools and
Reprocess. The temporary /voices audition page has been removed. Playback API
routes remain because the picker uses them to read the stored system assets.
