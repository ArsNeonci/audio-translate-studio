import { spawn } from "node:child_process";
import { activeJobCount } from "@/lib/server/jobs";

// "Quit" for the installed app. Closing the browser tab does not stop it: the web server and the workers run in the background
// without a window. The launcher that came with this installation (AUDIO_LAUNCHER) stops every process started from the
// installation folder. A development checkout has no launcher, so there is nothing to quit and the answer says so.
export type QuitInfo = { installed: boolean; active_jobs: number };
export const quitInfo = (): QuitInfo => ({ installed: Boolean(process.env.AUDIO_LAUNCHER && process.env.PYTHON_BIN), active_jobs: activeJobCount() });

export function quitApp(force: boolean): QuitInfo & { stopped: boolean } {
  const info = quitInfo();
  if (!info.installed) return { ...info, stopped: false };
  // Running workflows are kept unless the caller confirmed. Stopped ones resume by themselves the next time the app starts.
  if (info.active_jobs > 0 && !force) return { ...info, stopped: false };
  const child = spawn(process.env.PYTHON_BIN!, [process.env.AUDIO_LAUNCHER!, "--quit"], { detached: true, stdio: "ignore", windowsHide: true });
  child.unref();
  return { ...info, stopped: true };
}
