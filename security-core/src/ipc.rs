//! Named-pipe IPC and Windows service wrapper for the security core.
//!
//! The service is the authority: it answers license/identity/integrity queries and authorizes
//! workflow/command launches over a local named pipe. The pipe's ACL grants only the interactive
//! user, SYSTEM and Administrators, and rejects remote clients; requests are length-framed and
//! capped. No TCP port is opened and no arbitrary command runs — dispatch is the fixed action set.
use crate::license::{Result, PRODUCT};
use serde_json::{json, Value};
use std::ffi::{c_void, OsStr};
use std::os::windows::ffi::OsStrExt;
use std::ptr::{null, null_mut};
use std::sync::OnceLock;
use windows_sys::core::PWSTR;
use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::{CreateFileW, FlushFileBuffers, ReadFile, WriteFile};
use windows_sys::Win32::System::Pipes::{ConnectNamedPipe, CreateNamedPipeW, DisconnectNamedPipe, WaitNamedPipeW};
use windows_sys::Win32::System::Services::{
    RegisterServiceCtrlHandlerExW, SetServiceStatus, StartServiceCtrlDispatcherW, SERVICE_STATUS,
    SERVICE_STATUS_HANDLE, SERVICE_TABLE_ENTRYW,
};

const PIPE_ACCESS_DUPLEX: u32 = 0x0000_0003;
const PIPE_REJECT_REMOTE_CLIENTS: u32 = 0x0000_0008;
const PIPE_UNLIMITED_INSTANCES: u32 = 255;
const ERROR_PIPE_CONNECTED: u32 = 535;
const ERROR_PIPE_BUSY: u32 = 231;
const GENERIC_READ: u32 = 0x8000_0000;
const GENERIC_WRITE: u32 = 0x4000_0000;
const OPEN_EXISTING: u32 = 3;
const SDDL_REVISION_1: u32 = 1;
const BUFFER: u32 = 65536;
const MAX_REQUEST: usize = 65536;
const MAX_RESPONSE: usize = 16 * 1024 * 1024;

const SERVICE_WIN32_OWN_PROCESS: u32 = 0x0000_0010;
const SERVICE_STOPPED: u32 = 1;
const SERVICE_RUNNING: u32 = 4;
const SERVICE_STOP_PENDING: u32 = 3;
const SERVICE_ACCEPT_STOP: u32 = 1;
const SERVICE_ACCEPT_SHUTDOWN: u32 = 4;
const SERVICE_CONTROL_STOP: u32 = 1;
const SERVICE_CONTROL_SHUTDOWN: u32 = 5;

static DISPATCH: OnceLock<fn(&Value) -> Result<Value>> = OnceLock::new();
static STATUS_HANDLE: OnceLock<usize> = OnceLock::new();

/// Register the dispatch function used by the pipe server before `serve`/`run_service`.
pub fn set_dispatch(f: fn(&Value) -> Result<Value>) { let _ = DISPATCH.set(f); }

fn pipe_name() -> Vec<u16> {
    OsStr::new(&format!(r"\\.\pipe\AudioTranslate.{PRODUCT}")).encode_wide().chain(Some(0)).collect()
}

struct Security { attr: SECURITY_ATTRIBUTES }
// The descriptor is process-lifetime and only read by the OS; sharing it across threads is safe.
unsafe impl Send for Security {}
unsafe impl Sync for Security {}
fn security() -> Result<Security> {
    // Allow SYSTEM and Administrators full access and the interactive user read/write; deny others.
    let sddl: Vec<u16> = OsStr::new("D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGW;;;IU)").encode_wide().chain(Some(0)).collect();
    let mut psd: *mut c_void = null_mut();
    if unsafe { ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl.as_ptr(), SDDL_REVISION_1, &mut psd, null_mut()) } == 0 {
        return Err("CORE_UNAVAILABLE");
    }
    Ok(Security { attr: SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32, lpSecurityDescriptor: psd, bInheritHandle: 0,
    } })
}

struct Conn(HANDLE);
unsafe impl Send for Conn {}

fn read_exact(h: HANDLE, n: usize) -> std::result::Result<Vec<u8>, ()> {
    let mut buf = vec![0u8; n];
    let mut got = 0usize;
    while got < n {
        let mut read = 0u32;
        let ok = unsafe { ReadFile(h, buf[got..].as_mut_ptr(), (n - got) as u32, &mut read, null_mut()) };
        if ok == 0 || read == 0 { return Err(()); }
        got += read as usize;
    }
    Ok(buf)
}
fn write_all(h: HANDLE, data: &[u8]) -> std::result::Result<(), ()> {
    let mut sent = 0usize;
    while sent < data.len() {
        let mut wrote = 0u32;
        let ok = unsafe { WriteFile(h, data[sent..].as_ptr(), (data.len() - sent) as u32, &mut wrote, null_mut()) };
        if ok == 0 || wrote == 0 { return Err(()); }
        sent += wrote as usize;
    }
    Ok(())
}
fn frame(body: &[u8]) -> Vec<u8> {
    let mut out = (body.len() as u32).to_be_bytes().to_vec();
    out.extend_from_slice(body);
    out
}

fn dispatch(request: &Value) -> Value {
    match DISPATCH.get() {
        Some(f) => match f(request) {
            Ok(mut value) => { value["http_status"] = json!(200); value }
            Err(code) => json!({"http_status": 403, "status": code, "error": code, "product_id": PRODUCT}),
        },
        None => json!({"http_status": 503, "status": "SECURITY_SERVICE_UNAVAILABLE", "error": "SECURITY_SERVICE_UNAVAILABLE"}),
    }
}

fn handle(h: HANDLE) {
    let _ = (|| -> std::result::Result<(), ()> {
        let len = u32::from_be_bytes(read_exact(h, 4)?.try_into().map_err(|_| ())?) as usize;
        if len == 0 || len > MAX_REQUEST { return Err(()); }
        let body = read_exact(h, len)?;
        let response = match serde_json::from_slice::<Value>(&body) {
            Ok(request) => dispatch(&request),
            Err(_) => json!({"http_status": 400, "status": "INVALID_ACTION", "error": "INVALID_ACTION"}),
        };
        let out = serde_json::to_vec(&response).map_err(|_| ())?;
        if out.len() > MAX_RESPONSE { return Err(()); }
        write_all(h, &frame(&out))?;
        unsafe { FlushFileBuffers(h) };
        Ok(())
    })();
    unsafe { DisconnectNamedPipe(h); CloseHandle(h); }
}

/// Run the pipe server loop (console mode for dev/test, and the service worker). Blocks forever.
pub fn serve() -> Result<()> {
    let security = security()?;
    let name = pipe_name();
    loop {
        let h = unsafe {
            CreateNamedPipeW(name.as_ptr(), PIPE_ACCESS_DUPLEX, PIPE_REJECT_REMOTE_CLIENTS,
                PIPE_UNLIMITED_INSTANCES, BUFFER, BUFFER, 0, &security.attr)
        };
        if h == INVALID_HANDLE_VALUE { return Err("CORE_UNAVAILABLE"); }
        let connected = unsafe { ConnectNamedPipe(h, null_mut()) } != 0 || unsafe { GetLastError() } == ERROR_PIPE_CONNECTED;
        if !connected { unsafe { CloseHandle(h) }; continue; }
        let conn = Conn(h);
        std::thread::spawn(move || { let conn = conn; handle(conn.0); });
    }
}

/// Connect to the service pipe, send one request and read one response.
pub fn call(request: &Value) -> std::result::Result<Value, &'static str> {
    let body = serde_json::to_vec(request).map_err(|_| "INVALID_ACTION")?;
    if body.len() > MAX_REQUEST { return Err("INVALID_ACTION"); }
    let name = pipe_name();
    let h = loop {
        let h = unsafe { CreateFileW(name.as_ptr(), GENERIC_READ | GENERIC_WRITE, 0, null(), OPEN_EXISTING, 0, null_mut()) };
        if h != INVALID_HANDLE_VALUE { break h; }
        if unsafe { GetLastError() } == ERROR_PIPE_BUSY {
            if unsafe { WaitNamedPipeW(name.as_ptr(), 5000) } == 0 { return Err("SECURITY_SERVICE_UNAVAILABLE"); }
            continue;
        }
        return Err("SECURITY_SERVICE_UNAVAILABLE");
    };
    let result = (|| -> std::result::Result<Value, &'static str> {
        write_all(h, &frame(&body)).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
        let header = read_exact(h, 4).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
        let len = u32::from_be_bytes(header.try_into().unwrap()) as usize;
        if len == 0 || len > MAX_RESPONSE { return Err("SECURITY_SERVICE_UNAVAILABLE"); }
        let response = read_exact(h, len).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
        serde_json::from_slice(&response).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")
    })();
    unsafe { CloseHandle(h) };
    result
}

fn set_status(state: u32, accept: u32) {
    if let Some(handle) = STATUS_HANDLE.get() {
        let status = SERVICE_STATUS {
            dwServiceType: SERVICE_WIN32_OWN_PROCESS, dwCurrentState: state, dwControlsAccepted: accept,
            dwWin32ExitCode: 0, dwServiceSpecificExitCode: 0, dwCheckPoint: 0, dwWaitHint: 0,
        };
        unsafe { SetServiceStatus(*handle as SERVICE_STATUS_HANDLE, &status) };
    }
}

unsafe extern "system" fn control_handler(control: u32, _event: u32, _data: *mut c_void, _context: *mut c_void) -> u32 {
    if control == SERVICE_CONTROL_STOP || control == SERVICE_CONTROL_SHUTDOWN {
        set_status(SERVICE_STOP_PENDING, 0);
        set_status(SERVICE_STOPPED, 0);
        std::process::exit(0);
    }
    0 // NO_ERROR
}

unsafe extern "system" fn service_main(_argc: u32, _argv: *mut PWSTR) {
    // The service name is ignored for an own-process service; a fixed internal label is fine.
    let name: Vec<u16> = OsStr::new("AudioTranslateSecurityCore").encode_wide().chain(Some(0)).collect();
    let handle = RegisterServiceCtrlHandlerExW(name.as_ptr(), Some(control_handler), null());
    if handle.is_null() { return; }
    let _ = STATUS_HANDLE.set(handle as usize);
    set_status(SERVICE_RUNNING, SERVICE_ACCEPT_STOP | SERVICE_ACCEPT_SHUTDOWN);
    let _ = serve();
    set_status(SERVICE_STOPPED, 0);
}

/// Hand control to the SCM. Returns an error when not launched as a service.
pub fn run_service() -> Result<()> {
    let mut name: Vec<u16> = OsStr::new("AudioTranslateSecurityCore").encode_wide().chain(Some(0)).collect();
    let table = [
        SERVICE_TABLE_ENTRYW { lpServiceName: name.as_mut_ptr(), lpServiceProc: Some(service_main) },
        SERVICE_TABLE_ENTRYW { lpServiceName: null_mut(), lpServiceProc: None },
    ];
    if unsafe { StartServiceCtrlDispatcherW(table.as_ptr()) } == 0 { return Err("SECURITY_SERVICE_UNAVAILABLE"); }
    Ok(())
}
