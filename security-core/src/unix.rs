//! Linux counterparts of the Windows machine identity and DPAPI sealing (`windows.rs`), with the same function names and the same file format rules.
//!
//! Machine identity: the same recipe as Windows (`machine-v1|<install id>|<hardware uuid>`, SHA-256), with /etc/machine-id as the install id and the
//! SMBIOS product UUID (/sys/class/dmi/id/product_uuid, readable by root) as the hardware id, so cloning a disk image does not clone the identity.
//! Sealing: AES-256-GCM under a key made from a random 32-byte secret kept in a root-only file (`core.key`) and this machine's identity.
//! The state files are therefore readable only by the service (root) on this machine, the property DPAPI gave on Windows. Root on the machine can
//! of course read everything: the customer owning the server is outside what this layer can defend, exactly as an administrator is on Windows.
use crate::license::{Result, State};
use aes_gcm::{aead::{Aead, KeyInit}, Aes256Gcm, Nonce};
use fs2::FileExt;
use hkdf::Hkdf;
use sha2::{Digest, Sha256};
use std::{fs::{self, File, OpenOptions}, io::{Read, Write}, os::unix::fs::{OpenOptionsExt, PermissionsExt}, path::{Path, PathBuf}, sync::OnceLock};

const MAGIC: &[u8] = b"AT1";
const KEY_FILE: &str = "/var/lib/audio-translate/core.key";

fn normalize(s: &str) -> Result<String> {
    let value: String = s.to_ascii_lowercase().chars().filter(|c| c.is_ascii_hexdigit()).collect();
    if value.len() != 32 || value == "0".repeat(32) || value == "f".repeat(32) { return Err("MACHINE_ID_UNAVAILABLE"); }
    Ok(value)
}
fn first_line(paths: &[&str]) -> Option<String> {
    paths.iter().find_map(|p| fs::read_to_string(p).ok()).map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}
pub fn machine_id() -> Result<String> {
    let guid = normalize(&first_line(&["/etc/machine-id", "/var/lib/dbus/machine-id"]).ok_or("MACHINE_ID_UNAVAILABLE")?)?;
    let uuid = match first_line(&["/sys/class/dmi/id/product_uuid"]) {
        Some(value) => normalize(&value)?,
        // Containers and some hosts have no SMBIOS: only a development build may go on without it.
        #[cfg(feature = "dev_fallback")]
        None => hex::encode(&Sha256::digest(b"dev-no-smbios")[..16]),
        #[cfg(not(feature = "dev_fallback"))]
        None => return Err("MACHINE_ID_UNAVAILABLE"),
    };
    Ok(hex::encode(Sha256::digest(format!("machine-v1|{guid}|{uuid}").as_bytes())))
}

fn key_path() -> PathBuf {
    // A development build (tests, a console run without root) may name another place; a release build has one fixed path, no setting changes it.
    #[cfg(feature = "dev_fallback")]
    if let Some(path) = std::env::var_os("AUDIO_CORE_KEY_FILE") { return PathBuf::from(path); }
    PathBuf::from(KEY_FILE)
}
fn secret() -> Result<[u8; 32]> {
    static SECRET: OnceLock<[u8; 32]> = OnceLock::new();
    if let Some(value) = SECRET.get() { return Ok(*value); }
    let path = key_path();
    fs::create_dir_all(path.parent().ok_or("INVALID")?).map_err(|_| "INVALID")?;
    let value: [u8; 32] = match fs::read(&path) {
        Ok(raw) if raw.len() == 32 => raw.try_into().map_err(|_| "INVALID")?,
        Ok(_) => return Err("INVALID"),
        Err(_) => {
            let mut fresh = [0u8; 32];
            File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut fresh)).map_err(|_| "INVALID")?;
            // The key is written complete under a private name and then linked into place: the link fails if a key is already there, so two processes
            // starting together cannot both publish one, and nobody ever sees a half-written file. The loser reads the winner's key.
            let temp = path.with_extension(format!("{}.{}.tmp", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0)));
            let mut file = OpenOptions::new().write(true).create_new(true).mode(0o600).open(&temp).map_err(|_| "INVALID")?;
            file.write_all(&fresh).and_then(|_| file.sync_all()).map_err(|_| "INVALID")?; drop(file);
            let linked = fs::hard_link(&temp, &path);
            let _ = fs::remove_file(&temp);
            match linked {
                Ok(()) => fresh,
                Err(_) => fs::read(&path).map_err(|_| "INVALID")?.try_into().map_err(|_| "INVALID")?,
            }
        }
    };
    let _ = SECRET.set(value);
    Ok(value)
}
fn cipher() -> Result<Aes256Gcm> {
    let machine = machine_id()?;
    let mut key = [0u8; 32];
    Hkdf::<Sha256>::new(Some(machine.as_bytes()), &secret()?).expand(b"audio-core-seal-v1", &mut key).map_err(|_| "INVALID")?;
    Aes256Gcm::new_from_slice(&key).map_err(|_| "INVALID")
}
/// Seal arbitrary bytes for this machine (machine X25519 key, lease state, licence state).
pub fn seal(plain: &[u8]) -> Result<Vec<u8>> {
    let mut nonce = [0u8; 12];
    File::open("/dev/urandom").and_then(|mut f| f.read_exact(&mut nonce)).map_err(|_| "INVALID")?;
    let body = cipher()?.encrypt(Nonce::from_slice(&nonce), plain).map_err(|_| "INVALID")?;
    Ok([MAGIC, &nonce, &body].concat())
}
pub fn unseal(raw: &[u8]) -> Result<Vec<u8>> {
    if raw.len() < MAGIC.len() + 12 + 16 || !raw.starts_with(MAGIC) { return Err("INVALID"); }
    let (nonce, body) = raw[MAGIC.len()..].split_at(12);
    cipher()?.decrypt(Nonce::from_slice(nonce), body).map_err(|_| "INVALID")
}

pub struct Store { pub path: PathBuf, _lock: File }
impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        let parent = path.parent().ok_or("INVALID")?;
        fs::create_dir_all(parent).map_err(|_| "INVALID")?;
        let _ = fs::set_permissions(parent, fs::Permissions::from_mode(0o700));
        let lock = OpenOptions::new().create(true).truncate(false).read(true).write(true).mode(0o600).open(path.with_extension("lock")).map_err(|_| "INVALID")?;
        lock.lock_exclusive().map_err(|_| "INVALID")?;
        Ok(Self { path: path.into(), _lock: lock })
    }
    pub fn read(&self) -> Result<Option<State>> {
        if !self.path.exists() { return Ok(None); }
        if fs::metadata(&self.path).map_err(|_| "INVALID")?.len() > 65536 { return Err("INVALID"); }
        let raw = fs::read(&self.path).map_err(|_| "INVALID")?;
        let mut plain = unseal(&raw)?;
        let result = (|| {
            let mut value: serde_json::Value = serde_json::from_slice(&plain).map_err(|_| "INVALID")?;
            if let Some(time) = value["last_verified_time"].as_f64() {
                if !time.is_finite() || time < 0.0 || time > i64::MAX as f64 { return Err("INVALID"); }
                value["last_verified_time"] = serde_json::json!(time.ceil() as i64);
            }
            serde_json::from_value(value).map(Some).map_err(|_| "INVALID")
        })();
        plain.fill(0); result
    }
    pub fn write(&self, state: &State) -> Result<()> {
        let mut plain = serde_json::to_vec(state).map_err(|_| "INVALID")?;
        let raw = seal(&plain); plain.fill(0);
        let raw = raw?;
        let temp = self.path.with_extension(format!("{}.tmp", std::process::id()));
        let result = (|| {
            let mut file = OpenOptions::new().create_new(true).write(true).mode(0o600).open(&temp).map_err(|_| "INVALID")?;
            file.write_all(&raw).and_then(|_| file.sync_all()).map_err(|_| "INVALID")?; drop(file);
            fs::rename(&temp, &self.path).map_err(|_| "INVALID")?;
            // The rename is durable only once the directory entry is: the equivalent of MOVEFILE_WRITE_THROUGH.
            if let Some(dir) = self.path.parent().and_then(|d| File::open(d).ok()) { let _ = dir.sync_all(); }
            Ok(())
        })();
        let _ = fs::remove_file(temp); result
    }
}
