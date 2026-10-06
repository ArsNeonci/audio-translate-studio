//! Signed payload manifest and integrity verification.
//!
//! The manifest lists every protected file with its SHA-256, type and version, signed by a
//! dedicated Ed25519 key (never the license root). The private key stays Admin/build side;
//! only its public half is embedded at compile time (`license::MANIFEST`). Install verifies the
//! whole tree; runtime verifies the entries flagged `runtime` (binaries, config, encrypted
//! payloads) and never rehashes multi-gigabyte public model weights.
use crate::license::{signature, Result, MANIFEST};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::{Component, Path}};

#[derive(Deserialize, Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct Entry {
    pub path: String,
    pub sha256: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub version: String,
    /// Checked on every runtime verification; all entries are checked at install time.
    #[serde(default)]
    pub runtime: bool,
}

#[derive(Serialize)]
struct Signed<'a> { version: &'a str, entries: &'a [Entry] }

#[derive(Deserialize, Serialize, Debug)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    pub version: String,
    pub entries: Vec<Entry>,
    pub signature: String,
}

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Scope { Install, Runtime }

/// A release build has a manifest key embedded; dev builds leave it empty.
pub fn configured() -> bool { !MANIFEST.is_empty() }

fn safe_relative(p: &str) -> Result<()> {
    if p.is_empty() || p.len() > 1024 { return Err("INTEGRITY_FAILURE"); }
    // Only ordinary path segments; reject absolute paths, drive prefixes and `..` traversal.
    if Path::new(p).components().any(|c| !matches!(c, Component::Normal(_))) { return Err("INTEGRITY_FAILURE"); }
    Ok(())
}

/// Parse a manifest and verify its signature against `pubkey`.
pub fn parse_with(json: &str, pubkey: &str) -> Result<Manifest> {
    if json.len() > 4 * 1024 * 1024 { return Err("INTEGRITY_FAILURE"); }
    let m: Manifest = serde_json::from_str(json).map_err(|_| "INTEGRITY_FAILURE")?;
    let signed = Signed { version: &m.version, entries: &m.entries };
    signature(pubkey, "payload-manifest-v1", &signed, &m.signature).map_err(|_| "INTEGRITY_FAILURE")?;
    for e in &m.entries {
        if e.sha256.len() != 64 || !e.sha256.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) { return Err("INTEGRITY_FAILURE"); }
        safe_relative(&e.path)?;
    }
    Ok(m)
}

fn hash_file(path: &Path) -> std::result::Result<String, ()> {
    let mut file = File::open(path).map_err(|_| ())?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = file.read(&mut buf).map_err(|_| ())?;
        if n == 0 { break; }
        hasher.update(&buf[..n]);
    }
    Ok(hex::encode(hasher.finalize()))
}

/// Hash every file in scope under `app_root` and compare against the manifest. A missing or
/// altered binary reports UNTRUSTED_BINARY; any other mismatch reports INTEGRITY_FAILURE.
pub fn verify_tree(app_root: &Path, m: &Manifest, scope: Scope) -> Result<()> {
    for e in &m.entries {
        if scope == Scope::Runtime && !e.runtime { continue; }
        let code = if e.kind == "binary" { "UNTRUSTED_BINARY" } else { "INTEGRITY_FAILURE" };
        let actual = hash_file(&app_root.join(&e.path)).map_err(|_| code)?;
        if actual != e.sha256 { return Err(code); }
    }
    Ok(())
}

/// Load `payload.manifest.json` from `app_root` and verify it against the embedded key.
/// Returns INTEGRITY_UNCONFIGURED (dev builds) so the caller can downgrade to a warning.
pub fn load_and_verify(app_root: &Path, scope: Scope) -> Result<()> {
    if !configured() { return Err("INTEGRITY_UNCONFIGURED"); }
    let json = std::fs::read_to_string(app_root.join("payload.manifest.json")).map_err(|_| "INTEGRITY_FAILURE")?;
    let m = parse_with(&json, MANIFEST)?;
    verify_tree(app_root, &m, scope)
}
