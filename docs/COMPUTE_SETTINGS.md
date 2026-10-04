# CPU / GPU workflow settings

Settings → Workflow compute device saves the machine preference in
`data/settings/compute.json` (or `$AUDIO_DATA_DIR/settings/compute.json`).
Example: `{"version":1,"device":"cpu"}`. Supported values: `cpu`, `gpu`.

The orchestrator captures this preference at a workflow's first start in its
`job.json` field `compute_device`. Queued workflows use the preference at start.
Retry, resume and reprocess keep that workflow's captured device. Previously
started legacy workflows retain CPU. Changing Settings does not move active models.

- CPU: existing ASR/Hy-MT2/TTS calibration, memory limits and CPU pools remain active.
- GPU: TRANSCRIPTION 3/4 uses FunASR `cuda:0`; Hy-MT2 uses embedded
  `llama-cpp-python` with 999 requested GPU layers; VieNeu v3turbo uses `cuda`.
  The bundled CPU llama-server is not used in GPU mode.
- TRANSCRIPTION 4/4 merges text on CPU. Downloading, VAD, splitting and moderation
  also stay on CPU, as they do not use these GPU model backends.

GPU requires CUDA-capable PyTorch for FunASR/VieNeu and a GPU-enabled
`llama-cpp-python` for Hy-MT2, plus enough VRAM for model/context allocation.
Settings checks backend capabilities without loading models. A saved GPU choice
is allowed even before dependencies are installed, but execution checks the
backends needed by pending stages and reports an error if unavailable. There is
no automatic downgrade to CPU. Model-load failures (including insufficient VRAM)
retain the normal stage failure/checkpoint behavior. CUDA readiness is not a VRAM
capacity guarantee. Existing host RAM and thermal safeguards remain applicable.

To move an existing workflow to another device, create a new workflow with the
desired Settings choice. Directly changing a started job's device can invalidate
adapter/cache fingerprints and is not supported by the UI.
