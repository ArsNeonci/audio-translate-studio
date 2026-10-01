# Audio Studio — YouTube → Chinese transcript

Local Next.js Studio with a filesystem job queue and a Python FunASR worker. Each job keeps its source audio, resumable intermediate chunks, timestamped JSONL, and a readable UTF-8 Markdown transcript in `data/jobs/<job_id>/`.

## Run

Use Python 3.11 or 3.12, a compatible PyTorch installation, FFmpeg/ffprobe on `PATH`, and Node.js for Next.js and yt-dlp's YouTube support. The pinned Python packages come from the official yt-dlp and FunASR projects; the sibling source checkouts used during development are optional.

```powershell
cd <cloned-repo>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r worker/requirements.txt
npm install
$env:PYTHON_BIN = (Resolve-Path .\.venv\Scripts\python.exe).Path
npm run dev
```

Open <http://localhost:3000>. On Linux/macOS, activate `.venv/bin/activate` and set `PYTHON_BIN` to the virtualenv's `python` path. The first conversion downloads `paraformer-zh`, `fsmn-vad`, and `ct-punc` weights from ModelScope into `data/model-cache/`. Set `FUNASR_DEVICE=cuda:0` if the installed PyTorch build supports CUDA; CPU is the default.

yt-dlp uses the installed Node.js runtime for YouTube JavaScript challenges. If YouTube requires sign-in for your network, you may set `YTDLP_COOKIES_FILE` to a Netscape-format cookie file before starting the server; the app never reads browser cookies automatically.

The Next.js process must run as a persistent local server with a writable `data/jobs/` directory. This MVP uses one Python worker at a time and filesystem state instead of a database. Do not deploy the API to a serverless runtime.

## Pipeline

1. yt-dlp selects `bestaudio` only, writes the stream as received, and resumes partial downloads.
2. FFmpeg decodes that source directly to a mono 16 kHz PCM pipe. It does not create a full decoded audio file or extract video.
3. FSMN-VAD consumes 200 ms PCM frames with a persistent streaming cache and writes global speech intervals to `working/vad.jsonl`.
4. Intervals are grouped at silence, capped near 30 seconds, and given 2.5 second overlap only where VAD had to split continuous speech. PCM processing keeps at most one chunk plus a six second overlap tail in memory.
5. FunASR's integrated `paraformer-zh` + `fsmn-vad` + `ct-punc` pipeline runs on each bounded chunk with `sentence_timestamp=True`. Sentence timestamps are shifted to the source timeline. Timestamp ownership removes overlapping output at forced boundaries.
6. Each completed chunk is stored atomically in `working/chunk-xxxxxx.json`. The merge writes canonical `transcript.jsonl` and `transcript.zh.md` atomically.

The worker restarts incomplete VAD passes, reuses downloaded source audio, skips completed ASR chunks, and rebuilds final outputs after a retry or server restart. `working/worker.log` and the job's `error` field explain failures. The Studio polls every three seconds and offers Retry for failed jobs.

## Verify

```powershell
npm run lint
npm run build
python -m unittest discover -s worker -p "test_*.py" -v
```

The tests cover yt-dlp's audio-only configuration, VAD chunk boundaries, PCM overlap, global ordering, duplicate suppression, and Chinese Unicode output. The full FunASR pipeline was also verified with the short Chinese WAV bundled in the supplied FunASR checkout. Live YouTube downloading depends on the network and YouTube access policy; a 429/sign-in challenge can require `YTDLP_COOKIES_FILE`.

## References

- [yt-dlp README, audio-only format and Python API](https://github.com/yt-dlp/yt-dlp#format-selection)
- [FunASR Python tutorial, VAD and sentence timestamps](https://github.com/modelscope/FunASR/blob/main/docs/tutorial/README.md)
- [FunASR Paraformer examples, streaming FSMN-VAD](https://github.com/modelscope/FunASR/blob/main/examples/industrial_data_pretraining/paraformer/README.md)
