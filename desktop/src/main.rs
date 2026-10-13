//! Audio Translate desktop shell: a window around the local API, which it starts, watches and ends. It holds no product logic and
//! does not talk to the security service; the Python API does that.
#![cfg_attr(not(test), windows_subsystem = "windows")]
mod core;
mod platform;

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use tauri::webview::NewWindowResponse;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder, WindowEvent};

use core::*;

struct Shell {
    root: PathBuf,
    data: PathBuf,
    exe: PathBuf,
    port: u16,
    token: String,
    child: Mutex<Option<Child>>,
    quitting: Mutex<bool>,
}

fn fatal(message: &str) {
    let log = PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("AudioTranslate").join("launcher-error.log");
    if let Some(dir) = log.parent() { let _ = fs::create_dir_all(dir); }
    let _ = fs::write(&log, message);
    if std::env::var_os("AUDIO_LAUNCHER_NO_DIALOG").is_none() {
        platform::message_box(&format!("Audio Translate could not start: {message}\n\nDetails: {}", log.display()), false);
    }
}

/// Ends whatever an earlier run left under the installation folder (a worker started by the service can outlive the API), except this process.
fn cleanup(root: &Path) {
    let script = root.join("app_cleanup.py");
    let python = root.join("runtime").join("python").join("python.exe");
    if !script.is_file() || !python.is_file() { return; }
    let mut command = Command::new(python);
    command.arg(&script).arg("--keep").arg(std::process::id().to_string()).env("PYTHONNOUSERSITE", "1").env("PYTHONUTF8", "1")
        .current_dir(root.join("app")).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    platform::hide_window(&mut command);
    if let Ok(mut child) = command.spawn() {
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(20) {
            if matches!(child.try_wait(), Ok(Some(_))) { return; }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
    }
}

fn start_api(shell: &Shell) -> Result<Child, String> {
    fs::create_dir_all(&shell.data).map_err(|e| e.to_string())?;
    let tmp = shell.data.join("local-api.tmp");
    fs::write(&tmp, serde_json::json!({"port": shell.port, "token": shell.token}).to_string()).map_err(|e| e.to_string())?;
    fs::rename(&tmp, shell.data.join("local-api.json")).map_err(|e| e.to_string())?;
    let log = fs::OpenOptions::new().create(true).append(true).open(shell.data.join("local-api.log")).map_err(|e| e.to_string())?;
    let mut command = Command::new(shell.root.join("runtime").join("python").join("python.exe"));
    command.arg(shell.root.join("app").join("worker").join("app_api.py")).arg("--port").arg(shell.port.to_string())
        .arg("--ui").arg(shell.root.join("app").join("ui")).current_dir(shell.root.join("app"))
        .envs(api_env(&shell.root, &shell.data, &shell.exe, &shell.token))
        .stdin(Stdio::null()).stdout(log.try_clone().map_err(|e| e.to_string())?).stderr(log);
    platform::hide_window(&mut command);
    let child = command.spawn().map_err(|e| format!("STARTUP_FAILED: {e}"))?;
    platform::keep_with_shell(&child);
    Ok(child)
}

/// Waits until the API answers for this installation's product. False when it exits first or does not come up in time.
fn wait_ready(shell: &Shell, product: &str, child: &mut Child) -> bool {
    for _ in 0..240 {
        if probe(shell.port, &shell.token, Duration::from_secs(5)).as_deref() == Some(product) { return true; }
        if matches!(child.try_wait(), Ok(Some(_))) { return false; }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn fail(app: &tauri::AppHandle, message: &str) { fatal(message); app.exit(1); }

/// Starts the API, opens the page in the window, and starts the API again if it stops for any reason but the person's Quit.
fn run(app: tauri::AppHandle, shell: Arc<Shell>) {
    if !shell.root.join("app").join("security-core").join("bin").join("audio-security-core.exe").is_file() { return fail(&app, "NATIVE_SECURITY_CORE_MISSING"); }
    let Some(product) = product_id(&shell.root) else { return fail(&app, "PRODUCT_CONFIG_MISSING") };
    cleanup(&shell.root);
    if port_busy(shell.port) { return fail(&app, "PORT_IN_USE"); }
    let address = format!("http://127.0.0.1:{}/?launch={}", shell.port, shell.token);
    let mut policy = RestartPolicy::new(5, Duration::from_secs(120));
    let mut first = true;
    loop {
        if !policy.allow(Instant::now()) { return fail(&app, "STARTUP_FAILED: the local API keeps stopping; see local-api.log"); }
        let mut child = match start_api(&shell) { Ok(c) => c, Err(e) => return fail(&app, &e) };
        if !wait_ready(&shell, &product, &mut child) {
            let _ = child.kill();
            return fail(&app, "STARTUP_FAILED: see local-api.log");
        }
        if let Some(window) = app.get_webview_window("main") {
            if first { let _ = window.navigate(address.parse().unwrap()); } else { let _ = window.eval("location.reload()"); }
        }
        first = false;
        *shell.child.lock().unwrap() = Some(child);
        let code = loop {
            std::thread::sleep(Duration::from_millis(300));
            let mut guard = shell.child.lock().unwrap();
            match guard.as_mut().map(|c| c.try_wait()) {
                Some(Ok(Some(status))) => { guard.take(); break status.code(); }
                None => break None,   // the shell took the process to end it
                _ => {}
            }
        };
        if code == Some(QUIT_EXIT_CODE) || *shell.quitting.lock().unwrap() { return app.exit(0); }
    }
}

fn main() {
    let exe = std::env::current_exe().expect("the shell's own path");
    let root = exe.parent().expect("an installation folder").to_path_buf();
    let port = std::env::var("AUDIO_API_PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(DEFAULT_PORT);
    let shell = Arc::new(Shell { root, data: data_dir(), exe, port, token: token_hex(), child: Mutex::new(None), quitting: Mutex::new(false) });
    platform::prepare();
    let first = platform::first_instance(&shell.root.to_string_lossy());
    let for_setup = shell.clone();
    let for_exit = shell.clone();
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.unminimize(); let _ = window.set_focus(); }
        }))
        .setup(move |app| {
            if !first { return Ok(()); }   // a second start: the plugin has told the first one, which brings its window forward
            let shell = for_setup.clone();
            let (nav_shell, new_shell) = (shell.clone(), shell.clone());
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Audio Translate").inner_size(1360.0, 900.0).min_inner_size(960.0, 640.0)
                .on_navigation(move |url| {
                    if stays_in_window(url.as_str(), nav_shell.port) { return true; }
                    if url.scheme() == "http" || url.scheme() == "https" { platform::open_in_browser(url.as_str()); }
                    false
                })
                .on_new_window(move |url, _| {
                    // A link that asks for a new window (target=_blank, window.open) goes to the person's browser, never a second app window.
                    if (url.scheme() == "http" || url.scheme() == "https") && !stays_in_window(url.as_str(), new_shell.port) { platform::open_in_browser(url.as_str()); }
                    NewWindowResponse::Deny
                })
                .build()?;
            let (handle, for_close) = (app.handle().clone(), shell.clone());
            window.on_window_event(move |event| {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let (handle, shell) = (handle.clone(), for_close.clone());
                    std::thread::spawn(move || {
                        let running = active_jobs(shell.port, &shell.token);
                        if running > 0 && !platform::message_box(&format!("{running} workflow(s) are running. Quit anyway?\nThey continue from where they stopped the next time the app starts."), true) { return; }
                        *shell.quitting.lock().unwrap() = true;
                        handle.exit(0);
                    });
                }
            });
            let handle = app.handle().clone();
            std::thread::spawn(move || run(handle, shell));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("the window system")
        .run(move |_app, event| {
            if let RunEvent::Exit = event {
                *for_exit.quitting.lock().unwrap() = true;
                if let Some(mut child) = for_exit.child.lock().unwrap().take() { let _ = child.kill(); let _ = child.wait(); }
                cleanup(&for_exit.root);
            }
        });
}
