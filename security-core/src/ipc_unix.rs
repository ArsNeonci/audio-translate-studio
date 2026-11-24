//! Unix-socket IPC for the security core on Linux (the counterpart of the Windows named pipe in `ipc.rs`, same framing and the same fixed action set).
//!
//! The service is the authority: it answers licence/identity/integrity queries and authorizes workflow/command launches over a local socket. The
//! socket (/run/audio-translate/<product>.sock) belongs to root and to the group `audio-translate`, mode 0660: only the service user's group can
//! connect, the way the pipe's ACL named the interactive user, SYSTEM and Administrators. Release clients trust only a server running as root
//! (SO_PEERCRED), the counterpart of "LocalSystem" on Windows, so a look-alike server started by an ordinary user is refused. No TCP port is opened;
//! requests are length-framed and capped; no arbitrary command runs.
use crate::license::{Result, PRODUCT};
use serde_json::{json, Value};
use std::ffi::CString;
use std::io::{Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::io::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Duration;

const MAX_REQUEST: usize = 65536;
const MAX_RESPONSE: usize = 16 * 1024 * 1024;
const GROUP: &str = "audio-translate";
const IO_TIMEOUT: Duration = Duration::from_secs(30);

static DISPATCH: OnceLock<fn(&Value) -> Result<Value>> = OnceLock::new();

/// Register the dispatch function used by the socket server before `serve`/`run_service`.
pub fn set_dispatch(f: fn(&Value) -> Result<Value>) { let _ = DISPATCH.set(f); }

fn socket_path() -> PathBuf {
    // Development builds (tests, a console run) may name another socket; a release build has one fixed path.
    #[cfg(feature = "dev_fallback")]
    if let Some(path) = std::env::var_os("AUDIO_SECURITY_SOCKET") { return PathBuf::from(path); }
    PathBuf::from(format!("/run/audio-translate/{PRODUCT}.sock"))
}

fn frame(body: &[u8]) -> Vec<u8> {
    let mut out = (body.len() as u32).to_be_bytes().to_vec();
    out.extend_from_slice(body);
    out
}
fn read_exact(stream: &mut UnixStream, n: usize) -> std::result::Result<Vec<u8>, ()> {
    let mut buf = vec![0u8; n];
    stream.read_exact(&mut buf).map_err(|_| ())?;
    Ok(buf)
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

fn handle(mut stream: UnixStream) {
    let _ = stream.set_read_timeout(Some(IO_TIMEOUT)); let _ = stream.set_write_timeout(Some(IO_TIMEOUT));
    let _ = (|| -> std::result::Result<(), ()> {
        let len = u32::from_be_bytes(read_exact(&mut stream, 4)?.try_into().map_err(|_| ())?) as usize;
        if len == 0 || len > MAX_REQUEST { return Err(()); }
        let body = read_exact(&mut stream, len)?;
        let response = match serde_json::from_slice::<Value>(&body) {
            Ok(request) => dispatch(&request),
            Err(_) => json!({"http_status": 400, "status": "INVALID_ACTION", "error": "INVALID_ACTION"}),
        };
        let out = serde_json::to_vec(&response).map_err(|_| ())?;
        if out.len() > MAX_RESPONSE { return Err(()); }
        stream.write_all(&frame(&out)).and_then(|_| stream.flush()).map_err(|_| ())
    })();
}

/// Who is on the other end of the socket: (uid, pid) from the kernel, not from anything the peer says.
fn peer(stream: &UnixStream) -> Option<(u32, i32)> {
    let mut cred = libc::ucred { pid: 0, uid: 0, gid: 0 };
    let mut len = std::mem::size_of::<libc::ucred>() as libc::socklen_t;
    let done = unsafe { libc::getsockopt(stream.as_raw_fd(), libc::SOL_SOCKET, libc::SO_PEERCRED, (&mut cred as *mut libc::ucred).cast(), &mut len) };
    if done == 0 { Some((cred.uid, cred.pid)) } else { None }
}

/// Make the socket reachable by the service group only (root-only when the group does not exist: fail closed; a development build opens it).
fn restrict(path: &std::path::Path) {
    let group = CString::new(GROUP).ok().map(|name| unsafe { libc::getgrnam(name.as_ptr()) }).filter(|g| !g.is_null()).map(|g| unsafe { (*g).gr_gid });
    let mode = match (group, cfg!(feature = "dev_fallback")) {
        (Some(gid), _) => {
            if let Ok(c) = CString::new(path.as_os_str().to_string_lossy().as_bytes()) { unsafe { libc::chown(c.as_ptr(), u32::MAX, gid) }; }
            0o660
        }
        (None, true) => 0o666,
        (None, false) => 0o600,
    };
    let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode));
}

/// Run the socket server loop (the systemd service and the console mode of development). Blocks forever.
pub fn serve() -> Result<()> {
    let path = socket_path();
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|_| "CORE_UNAVAILABLE")?;
        let _ = std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o755));
    }
    let _ = std::fs::remove_file(&path);   // a socket left by a crashed run; a live service would have kept its own
    let listener = UnixListener::bind(&path).map_err(|_| "CORE_UNAVAILABLE")?;
    restrict(&path);
    for stream in listener.incoming() {
        if let Ok(stream) = stream { std::thread::spawn(move || handle(stream)); }
    }
    Ok(())
}

/// Connect to the service socket, send one request and read one response.
pub fn call(request: &Value) -> std::result::Result<Value, &'static str> {
    let body = serde_json::to_vec(request).map_err(|_| "INVALID_ACTION")?;
    if body.len() > MAX_REQUEST { return Err("INVALID_ACTION"); }
    let mut stream = UnixStream::connect(socket_path()).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
    stream.set_read_timeout(Some(IO_TIMEOUT)).and_then(|_| stream.set_write_timeout(Some(IO_TIMEOUT))).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
    // Release builds trust only a server running as root; development builds accept the console `serve` of any user.
    #[cfg(not(feature = "dev_fallback"))]
    if peer(&stream).map(|(uid, _)| uid) != Some(0) { return Err("SECURITY_SERVICE_UNAVAILABLE"); }
    #[cfg(feature = "dev_fallback")]
    let _ = peer(&stream);
    stream.write_all(&frame(&body)).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
    let header = read_exact(&mut stream, 4).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
    let len = u32::from_be_bytes(header.try_into().unwrap()) as usize;
    if len == 0 || len > MAX_RESPONSE { return Err("SECURITY_SERVICE_UNAVAILABLE"); }
    let response = read_exact(&mut stream, len).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")?;
    serde_json::from_slice(&response).map_err(|_| "SECURITY_SERVICE_UNAVAILABLE")
}

/// systemd starts the service as a plain foreground process (Type=simple), so there is nothing to hand over to a service manager.
pub fn run_service() -> Result<()> { serve() }
