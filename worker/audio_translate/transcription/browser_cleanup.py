"""The app's own YouTube browser profile: find its processes, stop the hidden ones, tie a hidden browser's life to its parent.

Light on purpose (psutil and the standard library only): the launcher imports it too, to clean up when the app starts and quits.

Only processes whose `--user-data-dir` is exactly this app's profile are ever touched, so the person's ordinary Edge or Chrome is safe.
A hidden browser is the one started with `--headless`; the window the person signs in with is never closed by force.
"""
import os
from pathlib import Path
import subprocess

_jobs = []   # Windows job handles stay open as long as the process lives: closing the last one kills everything inside


def session_root():
    custom = os.getenv('YOUTUBE_SESSION_ROOT')
    if custom:
        return Path(custom).resolve()
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'AudioTranslate' / 'youtube'
    return Path(os.getenv('XDG_DATA_HOME', str(Path.home() / '.local' / 'share'))) / 'AudioTranslate' / 'youtube'


def profile_processes():
    """Every process (browser, renderers, GPU, utilities) that belongs to the app's profile."""
    import psutil
    profile = (session_root() / 'profile').resolve()
    found = []
    for process in psutil.process_iter(['cmdline']):
        try:
            for arg in process.info.get('cmdline') or []:
                if arg.startswith('--user-data-dir=') and Path(arg.split('=', 1)[1]).resolve() == profile:
                    found.append(process); break
        except (psutil.Error, OSError, ValueError):
            continue
    return found


def is_main(process):
    return not any(arg.startswith('--type=') for arg in process.info.get('cmdline') or [])


def is_headless(process):
    return '--headless' in ' '.join(process.info.get('cmdline') or []) and is_main(process)


def hidden_processes():
    """The hidden browser and everything it started. Empty when the profile is in use by a normal window."""
    processes = profile_processes()
    mains = [p for p in processes if is_main(p)]
    if not mains or not all(is_headless(p) for p in mains):
        return [p for p in mains if is_headless(p)]
    return processes


def window_processes():
    """The main process of a normal (visible) browser window on the profile."""
    return [p for p in profile_processes() if is_main(p) and not is_headless(p)]


def stop(processes, grace=4):
    """Ask each process to end, then kill what is left. Returns how many were stopped."""
    import psutil
    alive = []
    for process in processes:
        try: process.terminate(); alive.append(process)
        except psutil.Error: pass
    _, left = psutil.wait_procs(alive, timeout=grace)
    for process in left:
        try: process.kill()
        except psutil.Error: pass
    if left: psutil.wait_procs(left, timeout=grace)
    return len(alive)


def stop_hidden():
    return stop(hidden_processes())


def close_window(wait=8):
    """Close a visible sign-in window the way the person would: a close request, never a kill, so Edge can save the session.
    Returns True when the window is gone."""
    import psutil
    mains = window_processes()
    for process in mains:
        try:
            subprocess.run(['taskkill', '/PID', str(process.pid)], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        except OSError:
            pass
    if mains: psutil.wait_procs(mains, timeout=wait)
    return not window_processes()


def running():
    return {'hidden': len(hidden_processes()), 'window': bool(window_processes())}


def browser_env():
    """The environment for Edge/Chrome without __COMPAT_LAYER. Windows gives the app `__COMPAT_LAYER=DetectorsAppHealth`; Edge that sees it
    restarts itself without it and the first process exits at once. The app then took the exit for a failure ("Không mở được profile
    YouTube"), and the restarted browser was left running. Measured 2026-10-09: 3/3 launches failed with the variable, none without."""
    return {key: value for key, value in os.environ.items() if key.upper() != '__COMPAT_LAYER'}


def start_hidden(args):
    """Popen for a hidden browser. On Windows it is created suspended, put in a job object that kills its whole tree when this
    process ends (for any reason, a crash or a kill included), and only then resumed, so no child can escape the job."""
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=browser_env())
    if os.name != 'nt':
        return subprocess.Popen(args, **kwargs)
    suspended = 0x00000004
    process = subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | suspended, **kwargs)
    try:
        _join_job(process)
    except Exception:
        pass   # without the job the cleanup on the next start still removes it
    finally:
        _resume(process)
    return process


def _join_job(process):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64), ('LimitFlags', wintypes.DWORD),
                    ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                    ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]

    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ('Read', 'Write', 'Other', 'ReadBytes', 'WriteBytes', 'OtherBytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('Basic', Basic), ('Io', Counters), ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                    ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    job = kernel.CreateJobObjectW(None, None)
    if not job: raise OSError(ctypes.get_last_error(), 'CreateJobObject')
    info = Extended(); info.Basic.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)): raise OSError(ctypes.get_last_error(), 'SetInformationJobObject')
    if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(int(process._handle))): raise OSError(ctypes.get_last_error(), 'AssignProcessToJobObject')
    _jobs.append(job)


def _resume(process):
    import ctypes
    from ctypes import wintypes
    ntdll = ctypes.WinDLL('ntdll')
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess(wintypes.HANDLE(int(process._handle)))
