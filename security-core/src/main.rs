#![cfg(windows)]
mod license;
mod windows;
#[cfg(test)] mod tests;

use license::{Result, PRODUCT, ROOT};
use serde_json::{json, Value};
use std::{env, io::{Read, Write}, path::{Path, PathBuf}, process::{Command, Stdio}, time::{Duration, SystemTime, UNIX_EPOCH}};

fn now() -> i64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs() as i64 }
fn state_path() -> Result<PathBuf> {
    // Storage location only; no environment setting changes the embedded anchor.
    let base = env::var_os("AUDIO_LICENSE_STATE_ROOT").map(PathBuf::from)
        .or_else(|| env::var_os("LOCALAPPDATA").map(|p| PathBuf::from(p).join("AudioTranslate/license"))).ok_or("INVALID")?;
    Ok(base.join("state.dpapi"))
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
    Ok(json!({"status":"ACTIVE", "allowed":true, "product_id":PRODUCT}))
}
fn app_root() -> Result<PathBuf> {
    // app/security-core/bin/audio-security-core.exe (same structure in development).
    let exe = env::current_exe().map_err(|_| "CORE_UNAVAILABLE")?;
    Ok(exe.parent().and_then(Path::parent).and_then(Path::parent).ok_or("CORE_UNAVAILABLE")?.to_path_buf())
}
fn python(app: &Path) -> Result<PathBuf> {
    let bundled = app.parent().ok_or("CORE_UNAVAILABLE")?.join("runtime/python/python.exe");
    let dev = app.join(".venv/Scripts/python.exe");
    if bundled.is_file() { Ok(bundled) } else if dev.is_file() { Ok(dev) } else { Err("CORE_UNAVAILABLE") }
}
pub fn command_protected(script: &str, action: &str) -> Result<bool> {
    // Default deny unknown commands. Read/history/download/cancel remain available.
    match (script, action) {
        ("manage.py", "create"|"convert"|"reprocess"|"resume"|"preflight") => Ok(true),
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
        check(true)?;
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
        if command_protected(script, request["payload"]["action"].as_str().ok_or("INVALID_ACTION")?)? { check(true)?; }
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
        "identity" => Ok(json!({"product_id":PRODUCT,"root_public_key":ROOT,"protocol":1})),
        "machine" => Ok(json!({"machine_id":windows::machine_id()?, "product_id":PRODUCT})),
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
