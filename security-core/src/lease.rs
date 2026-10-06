//! Short-lived lease and machine-wrapped content key (Phase 2C).
//!
//! The server issues a lease signed by the product signer (domain `machine-lease-v1`, same cert
//! chain as the license) carrying a monotonic counter, expiry, and the content key wrapped for this
//! machine with ECIES (X25519 → HKDF-SHA256 → AES-256-GCM). The service holds a machine X25519
//! keypair (DPAPI-sealed), unwraps the key into memory only, and stores the lease with the highest
//! counter it has seen so an older lease restored offline is detected as a rollback.
use crate::license::{signature as verify_sig, timestamp, Certificate, Result, PRODUCT};
use crate::windows;
use aes_gcm::aead::{Aead, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use hkdf::Hkdf;
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::path::{Path, PathBuf};
use x25519_dalek::{PublicKey, StaticSecret};

/// Default offline grace after a lease expires before new processing is blocked (configurable).
pub const GRACE_SECONDS: i64 = 3 * 24 * 3600;
const INFO: &[u8] = b"audio-content-key-v1";

#[derive(Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct WrappedKey {
    pub eph: String,
    pub nonce: String,
    pub ct: String,
}
#[derive(Deserialize, Serialize, Clone)]
#[serde(deny_unknown_fields)]
pub struct LeasePayload {
    pub license_id: String,
    pub machine_id: String,
    pub product_id: String,
    pub counter: u64,
    pub nonce: String,
    pub issued_at: String,
    pub expires_at: String,
    pub key_version: u64,
    pub wrapped_key: WrappedKey,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SignedCertificate { payload: Certificate, signature: String }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope { scheme: String, certificate: SignedCertificate, payload: LeasePayload, signature: String }

#[derive(Deserialize, Serialize, Default, Clone)]
pub struct LeaseState {
    pub lease: String,
    pub highest_counter: u64,
    pub last_verified_time: i64,
}

/// Verify a lease envelope's cert chain and signature; returns its payload.
pub fn verify_lease(token: &str, root: &str, machine: &str) -> Result<LeasePayload> {
    if token.len() > 8192 { return Err("SECURE_STATE_INVALID"); }
    let raw = URL_SAFE_NO_PAD.decode(token).map_err(|_| "SECURE_STATE_INVALID")?;
    let e: Envelope = serde_json::from_slice(&raw).map_err(|_| "SECURE_STATE_INVALID")?;
    if e.scheme != "ed25519-lease-v1" { return Err("SECURE_STATE_INVALID"); }
    let c = &e.certificate.payload;
    verify_sig(root, "product-signing-key-v1", c, &e.certificate.signature).map_err(|_| "SECURE_STATE_INVALID")?;
    if c.product_id != PRODUCT || e.payload.product_id != PRODUCT { return Err("WRONG_PRODUCT"); }
    verify_sig(&c.public_key, "machine-lease-v1", &e.payload, &e.signature).map_err(|_| "SECURE_STATE_INVALID")?;
    let p = e.payload;
    if p.machine_id != machine { return Err("WRONG_MACHINE"); }
    if p.counter == 0 || p.key_version == 0 || c.key_version != p.key_version { return Err("SECURE_STATE_INVALID"); }
    timestamp(&p.issued_at)?; timestamp(&p.expires_at)?;
    Ok(p)
}

fn machine_key_file(state_dir: &Path) -> PathBuf { state_dir.join("machine.x25519.dpapi") }

/// Load or create the machine X25519 secret (DPAPI-sealed at rest).
pub fn machine_secret(state_dir: &Path) -> Result<StaticSecret> {
    let path = machine_key_file(state_dir);
    if path.exists() {
        let bytes: [u8; 32] = windows::unseal(&std::fs::read(&path).map_err(|_| "SECURE_STATE_INVALID")?)?
            .try_into().map_err(|_| "SECURE_STATE_INVALID")?;
        return Ok(StaticSecret::from(bytes));
    }
    std::fs::create_dir_all(state_dir).map_err(|_| "SECURE_STATE_INVALID")?;
    let secret = StaticSecret::random_from_rng(OsRng);
    let sealed = windows::seal(secret.as_bytes())?;
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    std::fs::write(&temp, &sealed).map_err(|_| "SECURE_STATE_INVALID")?;
    let _ = std::fs::rename(&temp, &path);
    Ok(secret)
}

pub fn machine_public(state_dir: &Path) -> Result<String> {
    Ok(URL_SAFE_NO_PAD.encode(PublicKey::from(&machine_secret(state_dir)?).to_bytes()))
}

/// Unwrap the ECIES-wrapped content key with the machine secret.
pub fn unwrap_content_key(state_dir: &Path, w: &WrappedKey) -> Result<[u8; 32]> {
    let eph: [u8; 32] = URL_SAFE_NO_PAD.decode(&w.eph).map_err(|_| "SECURE_STATE_INVALID")?
        .try_into().map_err(|_| "SECURE_STATE_INVALID")?;
    let nonce = URL_SAFE_NO_PAD.decode(&w.nonce).map_err(|_| "SECURE_STATE_INVALID")?;
    let ct = URL_SAFE_NO_PAD.decode(&w.ct).map_err(|_| "SECURE_STATE_INVALID")?;
    if nonce.len() != 12 { return Err("SECURE_STATE_INVALID"); }
    let shared = machine_secret(state_dir)?.diffie_hellman(&PublicKey::from(eph));
    let mut okm = [0u8; 32];
    Hkdf::<Sha256>::new(None, shared.as_bytes()).expand(INFO, &mut okm).map_err(|_| "SECURE_STATE_INVALID")?;
    let cipher = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(&okm));
    let plain = cipher.decrypt(Nonce::from_slice(&nonce), Payload { msg: &ct, aad: INFO }).map_err(|_| "SECURE_STATE_INVALID")?;
    plain.try_into().map_err(|_| "SECURE_STATE_INVALID")
}

fn lease_file(state_dir: &Path) -> PathBuf { state_dir.join("lease.dpapi") }

pub fn load_state(state_dir: &Path) -> Result<Option<LeaseState>> {
    let path = lease_file(state_dir);
    if !path.exists() { return Ok(None); }
    let raw = std::fs::read(&path).map_err(|_| "SECURE_STATE_INVALID")?;
    let plain = windows::unseal(&raw)?;
    serde_json::from_slice(&plain).map(Some).map_err(|_| "SECURE_STATE_INVALID")
}

pub fn save_state(state_dir: &Path, state: &LeaseState) -> Result<()> {
    std::fs::create_dir_all(state_dir).map_err(|_| "SECURE_STATE_INVALID")?;
    let sealed = windows::seal(&serde_json::to_vec(state).map_err(|_| "SECURE_STATE_INVALID")?)?;
    let path = lease_file(state_dir);
    let temp = path.with_extension(format!("{}.tmp", std::process::id()));
    std::fs::write(&temp, &sealed).map_err(|_| "SECURE_STATE_INVALID")?;
    std::fs::rename(&temp, &path).map_err(|_| "SECURE_STATE_INVALID")
}

/// Install a freshly issued lease: verify, reject counter rollback, persist with the highest counter.
pub fn install(state_dir: &Path, token: &str, root: &str, machine: &str, now: i64) -> Result<LeasePayload> {
    let payload = verify_lease(token, root, machine)?;
    let previous = load_state(state_dir)?.map(|s| s.highest_counter).unwrap_or(0);
    if payload.counter < previous { return Err("SECURE_STATE_INVALID"); }
    save_state(state_dir, &LeaseState { lease: token.into(), highest_counter: payload.counter, last_verified_time: now })?;
    Ok(payload)
}

/// Resolve the current content key from a stored lease, or an error describing why not.
/// Returns None when no lease is present (the caller may fall back to the embedded key).
pub fn content_key(state_dir: &Path, root: &str, machine: &str, now: i64) -> Result<Option<[u8; 32]>> {
    let Some(state) = load_state(state_dir)? else { return Ok(None); };
    let payload = verify_lease(&state.lease, root, machine)?;
    if payload.counter < state.highest_counter { return Err("SECURE_STATE_INVALID"); }
    if now + crate::license::CLOCK_SKEW_SECONDS < state.last_verified_time { return Err("CLOCK_ROLLBACK"); }
    if now > timestamp(&payload.expires_at)? + GRACE_SECONDS { return Err("LICENSE_EXPIRED"); }
    Ok(Some(unwrap_content_key(state_dir, &payload.wrapped_key)?))
}
