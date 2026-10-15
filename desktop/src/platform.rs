//! Windows-only pieces: a job that ends every child with the shell, no console windows, the default browser, message boxes.
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};
use std::sync::OnceLock;

use windows_sys::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS, HANDLE};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::UI::Shell::ShellExecuteW;
use windows_sys::Win32::UI::WindowsAndMessaging::{MessageBoxW, IDYES, MB_ICONERROR, MB_ICONQUESTION, MB_OK, MB_YESNO, SW_SHOWNORMAL};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;
const DETACHED_PROCESS: u32 = 0x0000_0008;
const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
static JOB: OnceLock<usize> = OnceLock::new();

fn wide(text: &str) -> Vec<u16> { text.encode_utf16().chain(std::iter::once(0)).collect() }

/// One job for the whole run; closing it (the shell ending for any reason, even a kill) ends every process in it.
pub fn prepare() {
    JOB.get_or_init(|| unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info as *const _ as *const _, std::mem::size_of_val(&info) as u32);
        job as usize
    });
}

pub fn keep_with_shell(child: &Child) {
    if let Some(job) = JOB.get() { unsafe { AssignProcessToJobObject(*job as HANDLE, child.as_raw_handle() as HANDLE); } }
}

pub fn hide_window(command: &mut Command) { command.creation_flags(CREATE_NO_WINDOW); }

/// A program that must outlive the shell (the updater): no window, no console, its own process group.
pub fn detach(command: &mut Command) { command.creation_flags(CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP); }

pub fn open_in_browser(url: &str) {
    unsafe { ShellExecuteW(std::ptr::null_mut(), wide("open").as_ptr(), wide(url).as_ptr(), std::ptr::null(), std::ptr::null(), SW_SHOWNORMAL); }
}

/// A native message box. With `ask` it is Yes/No and returns whether Yes was chosen; otherwise an error box that always returns true.
pub fn message_box(text: &str, ask: bool) -> bool {
    let flags = if ask { MB_YESNO | MB_ICONQUESTION } else { MB_OK | MB_ICONERROR };
    unsafe { MessageBoxW(std::ptr::null_mut(), wide(text).as_ptr(), wide("Audio Translate").as_ptr(), flags) == IDYES || !ask }
}

/// True when this process is the first one for this installation folder. The single-instance plugin hands a second start over to the
/// first, but it does so while the second is already starting up; this answer lets the second do nothing at all in the meantime
/// (otherwise its start-up cleanup would end the first one's API).
pub fn first_instance(name: &str) -> bool {
    let name: String = name.chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '_' }).collect();
    unsafe {
        let handle = CreateMutexW(std::ptr::null(), 0, wide(&format!("Local\\AudioTranslate_{name}")).as_ptr());
        let first = !handle.is_null() && GetLastError() != ERROR_ALREADY_EXISTS;
        if first { std::mem::forget(handle); }   // held until the process ends
        first
    }
}
