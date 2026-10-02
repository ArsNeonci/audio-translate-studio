import { existsSync } from "node:fs";
import path from "node:path";

export const dataRoot = process.env.AUDIO_DATA_DIR || path.join(/*turbopackIgnore: true*/ process.cwd(), "data");
export const resultsRoot = path.resolve(/*turbopackIgnore: true*/ process.cwd(), process.env.RESULTS_ROOT || path.join(/*turbopackIgnore: true*/ dataRoot, "results"));

export function pythonBin(): string {
  const venv = path.join(/*turbopackIgnore: true*/ process.cwd(), ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return process.env.PYTHON_BIN || (existsSync(/*turbopackIgnore: true*/ venv) ? venv : process.platform === "win32" ? "python" : "python3");
}

export function workerEnv(): NodeJS.ProcessEnv {
  return { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1", AUDIO_DATA_DIR: dataRoot, RESULTS_ROOT: resultsRoot,
    MODELSCOPE_CACHE: process.env.MODELSCOPE_CACHE || path.join(/*turbopackIgnore: true*/ dataRoot, "model-cache"),
    HF_HOME: process.env.HF_HOME || path.join(/*turbopackIgnore: true*/ dataRoot, "hf-cache") };
}
