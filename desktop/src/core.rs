//! The parts of the shell that do not need a window: talking to the local API, the environment the API gets, the restart policy
//! and which addresses stay inside the window. Kept free of Tauri so they are unit-tested on their own.
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The API exits with this code when the person chose Quit in the page (routes_jobs.py). Any other exit is a crash.
pub const QUIT_EXIT_CODE: i32 = 75;
pub const DEFAULT_PORT: u16 = 3210;

/// 64 hex characters from the operating system's random source.
pub fn token_hex() -> String {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).expect("the system random source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// A plain HTTP/1.1 GET to the loopback API. Returns the status and the body.
pub fn http_get(port: u16, path: &str, token: &str, timeout: Duration) -> Option<(u16, String)> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, timeout).ok()?;
    stream.set_read_timeout(Some(timeout)).ok()?;
    stream.set_write_timeout(Some(timeout)).ok()?;
    let request = format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Audio-Api-Token: {token}\r\nConnection: close\r\n\r\n");
    stream.write_all(request.as_bytes()).ok()?;
    let mut raw = Vec::new();
    let _ = stream.read_to_end(&mut raw);
    parse_response(&String::from_utf8_lossy(&raw))
}

pub fn parse_response(text: &str) -> Option<(u16, String)> {
    let (head, body) = text.split_once("\r\n\r\n")?;
    let status = head.lines().next()?.split_whitespace().nth(1)?.parse().ok()?;
    Some((status, body.to_string()))
}

/// The product id the API answers with for this token; None when nothing answers or the token is not accepted.
pub fn probe(port: u16, token: &str, timeout: Duration) -> Option<String> {
    let (status, body) = http_get(port, "/api/license", token, timeout)?;
    if status != 200 { return None; }
    serde_json::from_str::<serde_json::Value>(&body).ok()?.get("product_id")?.as_str().map(str::to_string)
}

/// How many workflows are running right now; 0 when the API does not answer.
pub fn active_jobs(port: u16, token: &str) -> u64 {
    let Some((200, body)) = http_get(port, "/api/quit", token, Duration::from_secs(3)) else { return 0 };
    serde_json::from_str::<serde_json::Value>(&body).ok().and_then(|v| v.get("active_jobs")?.as_u64()).unwrap_or(0)
}

pub fn port_busy(port: u16) -> bool {
    TcpStream::connect_timeout(&SocketAddr::from(([127, 0, 0, 1], port)), Duration::from_secs(1)).is_ok()
}

/// A crashing API is started again, but not in a loop: at most `limit` starts inside `window`.
pub struct RestartPolicy { limit: usize, window: Duration, starts: Vec<Instant> }

impl RestartPolicy {
    pub fn new(limit: usize, window: Duration) -> Self { Self { limit, window, starts: Vec::new() } }
    pub fn allow(&mut self, now: Instant) -> bool {
        self.starts.retain(|t| now.duration_since(*t) < self.window);
        if self.starts.len() >= self.limit { return false; }
        self.starts.push(now);
        true
    }
}

/// Addresses the window itself shows (the local API and the splash page). Everything else opens in the person's browser.
pub fn stays_in_window(url: &str, port: u16) -> bool {
    let Some(rest) = url.strip_prefix("http://").or_else(|| url.strip_prefix("https://")) else { return false };
    let host = rest.split(['/', '?', '#']).next().unwrap_or("");
    host == format!("127.0.0.1:{port}") || host == "tauri.localhost"
}

pub fn data_dir() -> PathBuf {
    match std::env::var_os("AUDIO_DATA_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("AudioTranslate").join("data"),
    }
}

/// The environment the local API starts with: the same values the earlier launcher gave it, with AUDIO_SHELL in place of AUDIO_LAUNCHER.
pub fn api_env(root: &Path, data: &Path, shell_exe: &Path, token: &str) -> Vec<(String, String)> {
    let s = |p: PathBuf| p.to_string_lossy().into_owned();
    // ffmpeg for the workers, and node.exe only because yt-dlp solves YouTube's JavaScript challenges with it (nothing else in the app runs Node).
    let path = format!("{};{};{}", root.join("runtime").join("ffmpeg").display(), root.join("runtime").join("node").display(), std::env::var("PATH").unwrap_or_default());
    vec![
        ("PYTHON_BIN".into(), s(root.join("runtime").join("python").join("python.exe"))),
        ("AUDIO_SHELL".into(), s(shell_exe.to_path_buf())),
        ("PYTHONUTF8".into(), "1".into()),
        ("PYTHONNOUSERSITE".into(), "1".into()),
        ("HY_MT_MODEL_PATH".into(), s(data.join("models").join("Hy-MT2-7B-Q4_K_M").join("Hy-MT2-7B-Q4_K_M.gguf"))),
        ("AUDIO_DATA_DIR".into(), s(data.to_path_buf())),
        ("RESULTS_ROOT".into(), s(data.join("results"))),
        ("VIENEU_SOURCE".into(), s(root.join("providers").join("VieNeu"))),
        ("PATH".into(), path),
        ("AUDIO_API_TOKEN".into(), token.to_string()),
    ]
}

pub fn product_id(root: &Path) -> Option<String> {
    let text = std::fs::read_to_string(root.join("app").join("licensing").join("public-config.json")).ok()?;
    serde_json::from_str::<serde_json::Value>(&text).ok()?.get("product_id")?.as_str().map(str::to_string)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_are_64_hex_characters_and_differ() {
        let (a, b) = (token_hex(), token_hex());
        assert_eq!(a.len(), 64);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, b);
    }

    #[test]
    fn a_response_is_split_into_status_and_body() {
        assert_eq!(parse_response("HTTP/1.1 200 OK\r\nA: b\r\n\r\n{\"x\":1}"), Some((200, "{\"x\":1}".to_string())));
        assert_eq!(parse_response("HTTP/1.1 401 Unauthorized\r\n\r\n"), Some((401, String::new())));
        assert_eq!(parse_response("garbage"), None);
    }

    #[test]
    fn restarts_are_limited_inside_the_window() {
        let mut policy = RestartPolicy::new(3, Duration::from_secs(60));
        let t0 = Instant::now();
        assert!(policy.allow(t0) && policy.allow(t0) && policy.allow(t0));
        assert!(!policy.allow(t0 + Duration::from_secs(1)));
        assert!(policy.allow(t0 + Duration::from_secs(61)));
    }

    #[test]
    fn only_the_apps_own_addresses_stay_in_the_window() {
        assert!(stays_in_window("http://127.0.0.1:3210/?launch=x", 3210));
        assert!(stays_in_window("http://tauri.localhost/index.html", 3210));
        assert!(!stays_in_window("http://127.0.0.1:3211/", 3210));
        assert!(!stays_in_window("https://billing.example/portal", 3210));
        assert!(!stays_in_window("http://127.0.0.1:3210.evil.example/", 3210));
        assert!(!stays_in_window("file:///c:/x", 3210));
    }

    #[test]
    fn the_api_environment_matches_the_old_launcher() {
        let env = api_env(Path::new(r"C:\App"), Path::new(r"C:\D"), Path::new(r"C:\App\AudioTranslate.exe"), "tok");
        let get = |k: &str| env.iter().find(|(n, _)| n == k).map(|(_, v)| v.clone()).unwrap();
        assert_eq!(get("AUDIO_API_TOKEN"), "tok");
        assert_eq!(get("RESULTS_ROOT"), r"C:\D\results");
        assert!(get("PATH").starts_with(r"C:\App\runtime\ffmpeg;C:\App\runtime\node;"));
        assert!(!env.iter().any(|(n, _)| n == "AUDIO_LAUNCHER"));
    }

    #[test]
    fn nothing_listening_means_no_answer() {
        let free = { let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap(); l.local_addr().unwrap().port() };
        assert_eq!(probe(free, "t", Duration::from_millis(300)), None);
        assert_eq!(active_jobs(free, "t"), 0);
        assert!(!port_busy(free));
    }
}
