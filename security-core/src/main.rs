#![cfg(windows)]
mod ipc;
mod lease;
mod license;
mod manifest;
mod windows;
#[cfg(test)] mod tests;

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use license::{tier, Result, PRODUCT, ROOT};
use serde_json::{json, Value};
use std::{env, io::{Read, Write}, path::{Path, PathBuf}, process::{Command, Stdio}, time::{Duration, SystemTime, UNIX_EPOCH}};

fn now() -> i64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64 }
fn state_path() -> Result<PathBuf> {
    // Storage location only; no environment setting changes the embedded anchor.
    let base = env::var_os("AUDIO_LICENSE_STATE_ROOT").map(PathBuf::from)
        .or_else(|| env::var_os("LOCALAPPDATA").map(|p| PathBuf::from(p).join("AudioTranslate/license"))).ok_or("INVALID")?;
    // Each edition keeps its own license; Basic state never blocks activating Plus.
    Ok(base.join(if PRODUCT == "audio-translate" { "state.dpapi".to_string() } else { format!("state-{PRODUCT}.dpapi") }))
}
fn trusted_time() -> Result<i64> {
    let mut handles = Vec::new();
    for url in ["https://www.microsoft.com/", "https://www.google.com/", "https://www.cloudflare.com/"] {
        handles.push(std::thread::spawn(move || -> Option<i64> {
            let client = reqwest::blocking::Client::builder().timeout(Duration::from_secs(6))
                .redirect(reqwest::redirect::Policy::none()).build().ok()?;
            let response = client.head(url).query(&[("time_nonce", format!("{}-{}", std::process::id(), now()))])
                .header("Cache-Control", "no-cache").send().ok()?;
            if response.headers().get("Age").map(|v| v.to_str().ok()?.parse::<u64>().ok()).flatten().unwrap_or(0) > 5 { return None; }
            chrono::DateTime::parse_from_rfc2822(response.headers().get("Date")?.to_str().ok()?).ok().map(|d| d.timestamp())
        }));
    }
    let mut values: Vec<i64> = handles.into_iter().filter_map(|h| h.join().ok().flatten()).collect(); values.sort();
    if values.len() < 2 || values.last().unwrap()-values.first().unwrap() > 60 { return Err("TRUSTED_TIME_UNAVAILABLE"); }
    Ok((values[(values.len()-1)/2]+values[values.len()/2])/2)
}
fn check(internet: bool) -> Result<Value> {
    let machine = windows::machine_id()?;
    let store = windows::Store::open(&state_path()?)?;
    let mut state = store.read()?.ok_or("UNACTIVATED")?;
    let p = license::verified(&state, ROOT, &machine)?;
    license::expiration(&p, now(), state.last_verified_time)?;
    let time = if internet { trusted_time()? } else { now() };
    license::expiration(&p, time, state.last_verified_time)?;
    state.last_verified_time = time.max(state.last_verified_time);
    state.key_version = p.key_version;
    store.write(&state)?;
    Ok(json!({"status":"ACTIVE", "allowed":true, "product_id":PRODUCT, "tier":tier(PRODUCT)}))
}
/// The signed license authenticates this machine to the Genius gateway. It is already
/// the customer's own token; the gateway verifies signature, product and expiry itself.
fn credential() -> Result<Value> {
    let machine = windows::machine_id()?;
    let store = windows::Store::open(&state_path()?)?;
    let state = store.read()?.ok_or("UNACTIVATED")?;
    let p = license::verified(&state, ROOT, &machine)?;
    license::expiration(&p, now(), state.last_verified_time)?;
    Ok(json!({"status":"ACTIVE", "token":state.current_license, "customer_id":p.customer_id, "product_id":PRODUCT, "tier":tier(PRODUCT)}))
}
fn app_root() -> Result<PathBuf> {
    // app/security-core/bin/audio-security-core.exe (same structure in development).
    let exe = env::current_exe().map_err(|_| "CORE_UNAVAILABLE")?;
    Ok(exe.parent().and_then(Path::parent).and_then(Path::parent).ok_or("CORE_UNAVAILABLE")?.to_path_buf())
}
/// Append a tamper/security event to a local log only (no network, no user content). Canary and
/// integrity failures land here so an operator can see them without any data leaving the machine.
fn note_tamper(code: &str) {
    let Ok(state) = state_path() else { return; };
    let Some(dir) = state.parent() else { return; };
    let _ = std::fs::create_dir_all(dir);
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("security-events.log")) {
        let _ = writeln!(file, "{{\"time\":{},\"event\":\"{}\",\"product_id\":\"{}\"}}", now(), code, PRODUCT);
    }
}
/// Verify the signed payload manifest. Dev builds have no manifest key embedded, so integrity
/// reports itself unconfigured and is skipped; release builds fail closed with a tamper state.
fn app_integrity(app: &Path, scope: manifest::Scope) -> Result<()> {
    match manifest::load_and_verify(app, scope) {
        Ok(()) | Err("INTEGRITY_UNCONFIGURED") => Ok(()),
        Err(code) => { note_tamper(code); Err(code) }
    }
}
/// Map a status string received from the service back to a static code for error emission.
fn known(code: &str) -> &'static str {
    match code {
        "EXPIRED" => "EXPIRED", "WRONG_MACHINE" => "WRONG_MACHINE", "WRONG_PRODUCT" => "WRONG_PRODUCT",
        "CLOCK_ROLLBACK" => "CLOCK_ROLLBACK", "UNACTIVATED" => "UNACTIVATED",
        "INTEGRITY_FAILURE" => "INTEGRITY_FAILURE", "UNTRUSTED_BINARY" => "UNTRUSTED_BINARY",
        "TAMPER_DETECTED" => "TAMPER_DETECTED", "SECURE_STATE_INVALID" => "SECURE_STATE_INVALID",
        "SECURITY_SERVICE_UNAVAILABLE" => "SECURITY_SERVICE_UNAVAILABLE",
        "TRUSTED_TIME_UNAVAILABLE" => "TRUSTED_TIME_UNAVAILABLE", "MACHINE_ID_UNAVAILABLE" => "MACHINE_ID_UNAVAILABLE",
        _ => "INVALID",
    }
}
/// The authority runs in the service: integrity plus the license check live there, so stopping
/// the service blocks new processing. Dev builds fall back to an in-process decision when the
/// pipe is absent; release builds (no dev_fallback feature) fail with SECURITY_SERVICE_UNAVAILABLE.
fn authorize(kind: &str, script: &str, action: &str) -> Result<()> {
    let mut request = json!({"action": "authorize", "kind": kind});
    if kind == "command" { request["script"] = json!(script); request["payload_action"] = json!(action); }
    match ipc::call(&request) {
        Ok(value) => if value["status"] == "AUTHORIZED" { Ok(()) } else { Err(known(value["status"].as_str().unwrap_or("INVALID"))) },
        Err(code) => {
            let _ = code;
            #[cfg(feature = "dev_fallback")]
            { app_integrity(&app_root()?, manifest::Scope::Runtime)?; check(true)?; return Ok(()); }
            #[cfg(not(feature = "dev_fallback"))]
            return Err(code);
        }
    }
}
/// Pipe dispatch for the service: license/identity/integrity queries plus launch authorization.
fn service_dispatch(request: &Value) -> Result<Value> {
    if request["action"].as_str() == Some("authorize") {
        let app = app_root()?;
        app_integrity(&app, manifest::Scope::Runtime)?;
        match request["kind"].as_str() {
            Some("workflow") => { check(true)?; Ok(json!({"status": "AUTHORIZED", "product_id": PRODUCT})) }
            Some("command") => {
                let script = request["script"].as_str().ok_or("INVALID_ACTION")?;
                let action = request["payload_action"].as_str().ok_or("INVALID_ACTION")?;
                if command_protected(script, action)? { check(true)?; }
                Ok(json!({"status": "AUTHORIZED", "product_id": PRODUCT}))
            }
            _ => Err("INVALID_ACTION"),
        }
    } else {
        execute(request)
    }
}
fn python(app: &Path) -> Result<PathBuf> {
    let bundled = app.parent().ok_or("CORE_UNAVAILABLE")?.join("runtime/python/python.exe");
    let dev = app.join(".venv/Scripts/python.exe");
    if bundled.is_file() { Ok(bundled) } else if dev.is_file() { Ok(dev) } else { Err("CORE_UNAVAILABLE") }
}
pub fn command_protected(script: &str, action: &str) -> Result<bool> {
    // Default deny unknown commands. Read/history/download/cancel remain available.
    match (script, action) {
        // "review" continues or ends a run held before paid Voice generation (Basic).
        ("manage.py", "create"|"convert"|"reprocess"|"resume"|"preflight"|"review") => Ok(true),
        ("retry.py", "retry") => Ok(true),
        ("manage.py", "initialize"|"voices"|"history"|"resolve"|"cancel"|"pause"|"abort"|"finish_abort"|"delete") => Ok(false),
        ("retry.py", "errors"|"error"|"guide") => Ok(false),
        _ => Err("INVALID_ACTION"),
    }
}
fn launch(request: &Value, workflow: bool) -> Result<i32> {
    let app = app_root()?;
    let script;
    let mut args = Vec::new();
    if workflow {
        authorize("workflow", "", "")?;
        script = "orchestrator.py";
        let input = PathBuf::from(request["job_dir"].as_str().ok_or("INVALID_ACTION")?);
        let job = input.canonicalize().map_err(|_| "INVALID_ACTION")?;
        let data = env::var_os("AUDIO_DATA_DIR").map(PathBuf::from).unwrap_or_else(|| app.join("data"));
        let data = data.canonicalize().map_err(|_| "INVALID_ACTION")?;
        let valid = ["tmp", "jobs", "tool-tmp"].iter().any(|p| job.parent() == Some(data.join(p).as_path()));
        let name = job.file_name().and_then(|s| s.to_str()).ok_or("INVALID_ACTION")?;
        if !valid || name.len() != 36 || !name.bytes().all(|c| c.is_ascii_hexdigit() || c==b'-') { return Err("INVALID_ACTION"); }
        args.push(job.to_string_lossy().to_string());
    } else {
        script = request["script"].as_str().ok_or("INVALID_ACTION")?;
        let action = request["payload"]["action"].as_str().ok_or("INVALID_ACTION")?;
        if command_protected(script, action)? { authorize("command", script, action)?; }
    }
    let mut command = Command::new(python(&app)?);
    command.arg(app.join("worker").join(script)).args(args).current_dir(&app)
        .stdin(if workflow { Stdio::null() } else { Stdio::piped() }).stdout(Stdio::inherit()).stderr(Stdio::inherit());
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x08000000);
    let mut child = command.spawn().map_err(|_| "CORE_UNAVAILABLE")?;
    if !workflow {
        let raw = serde_json::to_vec(&request["payload"]).map_err(|_| "INVALID_ACTION")?;
        child.stdin.take().ok_or("CORE_UNAVAILABLE")?.write_all(&raw).map_err(|_| "CORE_UNAVAILABLE")?;
    }
    Ok(child.wait().map_err(|_| "CORE_UNAVAILABLE")?.code().unwrap_or(1))
}
fn execute(request: &Value) -> Result<Value> {
    match request["action"].as_str().ok_or("INVALID_ACTION")? {
        "identity" => Ok(json!({"product_id":PRODUCT,"tier":tier(PRODUCT),"root_public_key":ROOT,"protocol":1})),
        "credential" => credential(),
        "machine" => Ok(json!({"machine_id":windows::machine_id()?, "product_id":PRODUCT})),
        "integrity" => {
            let scope = if request["scope"].as_str() == Some("runtime") { manifest::Scope::Runtime } else { manifest::Scope::Install };
            app_integrity(&app_root()?, scope)?;
            Ok(json!({"status":"VERIFIED", "configured":manifest::configured(), "product_id":PRODUCT}))
        }
        // Asset vault key (Phase 2B): released only after integrity and an offline license check.
        // Phase 2C will prefer a lease-wrapped key over the embedded one.
        "content_key" => {
            app_integrity(&app_root()?, manifest::Scope::Runtime)?;
            check(false)?;
            let state = state_path()?;
            let dir = state.parent().ok_or("INVALID")?;
            let machine = windows::machine_id()?;
            match lease::content_key(dir, ROOT, &machine, now())? {
                // A lease-wrapped key is machine-bound; expiry/rollback are enforced in lease::content_key.
                Some(key) => Ok(json!({"status":"OK", "content_key":URL_SAFE_NO_PAD.encode(key), "source":"lease", "product_id":PRODUCT})),
                None if !license::CONTENT_KEY.is_empty() => Ok(json!({"status":"OK", "content_key":license::CONTENT_KEY, "source":"embedded", "product_id":PRODUCT})),
                None => Err("VAULT_UNCONFIGURED"),
            }
        }
        "machine_pubkey" => {
            let state = state_path()?;
            Ok(json!({"status":"OK", "machine_pubkey":lease::machine_public(state.parent().ok_or("INVALID")?)?, "machine_id":windows::machine_id()?, "product_id":PRODUCT}))
        }
        "install_lease" => {
            let state = state_path()?;
            let dir = state.parent().ok_or("INVALID")?;
            let payload = lease::install(dir, request["token"].as_str().ok_or("INVALID")?, ROOT, &windows::machine_id()?, now())?;
            Ok(json!({"status":"OK", "counter":payload.counter, "expires_at":payload.expires_at, "license_id":payload.license_id, "product_id":PRODUCT}))
        }
        "check" => check(request["internet"].as_bool().unwrap_or(true)),
        "status" => {
            let result = (|| {
                let store = windows::Store::open(&state_path()?)?;
                license::status(&store.read()?.ok_or("UNACTIVATED")?, ROOT, &windows::machine_id()?, now())
            })();
            Ok(result.unwrap_or_else(|code| json!({"status":code,"product_id":PRODUCT})))
        }
        "activate"|"renew" => {
            let machine = windows::machine_id()?;
            let store = windows::Store::open(&state_path()?)?;
            let old = store.read()?;
            let state = license::adopt(old.as_ref(), request["token"].as_str().ok_or("INVALID")?, request["action"] == "renew", ROOT, &machine)?;
            store.write(&state)?;
            // Expired imports are accepted for renewal recovery, never for authorization.
            Ok(license::status(&state, ROOT, &machine, now()).unwrap_or_else(|code| json!({"status":code,"product_id":PRODUCT})))
        }
        _ => Err("INVALID_ACTION"),
    }
}
fn emit_error(code: &str, broker: bool) {
    if broker { println!("{}", json!({"status":403,"error":code,"license_status":code})); }
    else { println!("{}", json!({"http_status":403,"status":code,"error":code,"product_id":PRODUCT})); }
}
fn main() {
    // Service / console server modes are selected by argument; the default stdin path is the
    // CLI used by the launcher (workflow/command) and dev tools.
    match env::args().nth(1).as_deref() {
        Some("service") => { ipc::set_dispatch(service_dispatch); let _ = ipc::run_service(); return; }
        Some("serve") => { ipc::set_dispatch(service_dispatch); let _ = ipc::serve(); return; }
        _ => {}
    }
    let mut raw = String::new();
    let parsed = std::io::stdin().take(65537).read_to_string(&mut raw).ok().filter(|_| raw.len() <= 65536)
        .and_then(|_| serde_json::from_str::<Value>(raw.trim_start_matches('\u{feff}')).ok());
    let Some(request) = parsed else { emit_error("INVALID_ACTION", false); std::process::exit(2); };
    let workflow = request["action"] == "workflow";
    if workflow || request["action"] == "command" {
        match launch(&request, workflow) {
            Ok(code) => std::process::exit(code),
            Err(code) => { emit_error(code, true); std::process::exit(if workflow { 3 } else { 0 }); }
        }
    }
    match execute(&request) {
        Ok(mut value) => { value["http_status"] = json!(200); println!("{value}"); }
        Err(code) => emit_error(code, false),
    }
}
