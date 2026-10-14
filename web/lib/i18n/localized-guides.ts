import type { Language } from '@/lib/i18n/i18n';

type Guide = { cause: string; config: string; checks_and_fixes: string[]; commands: string[] };
// Mirror the known worker guide codes; paths and commands remain literal.
const english: Record<string, Omit<Guide, 'commands'>> = {
  UNACTIVATED: { cause: 'The application is not activated.', config: 'License / Renewal', checks_and_fixes: ['Open License, copy the Machine ID and send it to your administrator.', 'Enter the activation token issued for this machine.'] },
  EXPIRED: { cause: 'The license has expired.', config: 'License / Renewal', checks_and_fixes: ['Ask your administrator for a renewal token for the same machine.', 'Apply renewal tokens in order. History and downloads remain available.'] },
  CLOCK_ROLLBACK: { cause: 'The system clock is earlier than the previous check.', config: 'Windows Date & Time', checks_and_fixes: ['Enable Windows time synchronization and check the time zone.', 'Keep the license state; synchronize the clock and retry.'] },
  TRUSTED_TIME_UNAVAILABLE: { cause: 'Internet time could not be verified.', config: 'Windows HTTPS / proxy connection', checks_and_fixes: ['Check your Internet connection and HTTPS certificates.', 'Retry when at least two time sources are reachable.'] },
  DEPENDENCY_MISSING: { cause: 'A Python dependency is missing.', config: 'worker/requirements.txt; .venv', checks_and_fixes: ['Check the Python interpreter in .venv.', 'Install the project dependencies, then retry the stage.'] },
  MODEL_MISSING: { cause: 'The model was not found or its weights are incomplete.', config: '.env.local: HY_MT_MODEL_PATH / VIENEU_SOURCE; models/Hy-MT2-7B-Q4_K_M; data/model-cache; data/hf-cache', checks_and_fixes: ['Check the model path and access to its repository.', 'Correct the path or download the complete official model, then retry the stage.'] },
  FFMPEG_MISSING: { cause: 'FFmpeg/ffprobe is not on PATH.', config: 'Server PATH', checks_and_fixes: ['Install FFmpeg from its official source and add its bin directory to PATH.', 'Open a new terminal and restart the server.'] },
  PATH_MISSING: { cause: 'A file, directory or program does not exist.', config: '.env.local; paths in the error message', checks_and_fixes: ['Check paths and input files.', 'Correct the path; restart the server after changing .env.local.'] },
  FILE_PERMISSION: { cause: 'Read/write access is denied or a file is locked by another program.', config: 'data/tmp; data/jobs (legacy); RESULTS_ROOT; data/config; model directory', checks_and_fixes: ['Check write permissions for the account running the server.', 'Close programs holding the file; grant access to the correct directory and retry the stage.'] },
  DISK_FULL: { cause: 'There is not enough free disk space.', config: 'Drive containing data/tmp, RESULTS_ROOT and model cache', checks_and_fixes: ['Check available disk space.', 'Move or remove unneeded files of your choice; keep job inputs, checkpoints and saved results.'] },
  CUDA_OOM: { cause: 'The GPU has insufficient memory.', config: 'Settings → CPU/GPU; data/settings/compute.json; job.json: compute_device', checks_and_fixes: ['Close GPU applications, then retry.', 'To use CPU, select CPU in Settings and create a new workflow. Retrying the old workflow retains its device.'] },
  CUDA_CONFIG: { cause: 'CUDA/PyTorch or the GPU backend configuration is incompatible.', config: 'Settings → CPU/GPU; installed PyTorch and llama-cpp-python', checks_and_fixes: ['Check torch.cuda.is_available() and llama_supports_gpu_offload().', 'Install compatible GPU backends and retry, or choose CPU in Settings and create a new workflow. Started workflows retain their device.'] },
  YOUTUBE_AUTH: { cause: 'YouTube requires authentication or the saved session is invalid.', config: 'Settings → YouTube Connection', checks_and_fixes: ['Click Sign in again / Open YouTube and sign in in the dedicated profile window.', 'Click Check connection and retry Download; no server restart is needed.', 'If using a legacy cookie file, update the Netscape-format YTDLP_COOKIES_FILE.'] },
  RATE_LIMIT: { cause: 'YouTube is rate-limiting access.', config: 'Network / VPN / proxy', checks_and_fixes: ['Wait before retrying the stage.', 'Check the network and verify your browser session if requested by YouTube.'] },
  ENV_CONFIG: { cause: 'An environment variable or configuration value is invalid.', config: '.env.local; .env.example; working/adapters.json; RESULTS_ROOT', checks_and_fixes: ['Compare .env.example and check batch/device/path values. RESULTS_ROOT must be separate from data/tmp and data/jobs.', 'Update .env.local and restart the server. For an existing job with fixed adapters.json, update its relevant configuration field before retrying.'] },
};

export function localizeGuide(guide: Guide, code: string, language: Language): Guide {
  return language === 'en' && english[code] ? { ...guide, ...english[code] } : guide;
}
