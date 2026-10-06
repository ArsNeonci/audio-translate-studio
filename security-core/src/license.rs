use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use chrono::DateTime;
use ed25519_dalek::{Signature, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

pub type Result<T> = std::result::Result<T, &'static str>;
pub const PRODUCT: &str = env!("EMBEDDED_PRODUCT_ID");
pub const ROOT: &str = env!("EMBEDDED_ROOT_PUBLIC_KEY");
/// Separate Ed25519 key for the payload manifest; never the license root. Empty when
/// a release manifest key has not been embedded (dev builds): integrity stays unconfigured.
pub const MANIFEST: &str = env!("EMBEDDED_MANIFEST_PUBLIC_KEY");
/// Content key for the asset vault (Phase 2B). Empty in dev builds. Phase 2C prefers a
/// lease-delivered key over this embedded fallback.
#[cfg_attr(not(feature = "dev_fallback"), allow(dead_code))]
pub const CONTENT_KEY: &str = env!("EMBEDDED_CONTENT_KEY");
/// Edition decided by the compiled Product ID; the legacy single product keeps full features.
pub fn tier(product: &str) -> &'static str { if product.ends_with("-basic") { "basic" } else { "plus" } }

#[derive(Deserialize, Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct Certificate {
    pub product_id: String,
    pub key_version: u64,
    pub public_key: String,
}
#[derive(Deserialize, Serialize, Clone, Debug)]
#[serde(deny_unknown_fields)]
pub struct Payload {
    pub license_id: String,
    pub entitlement_id: String,
    pub customer_id: String,
    pub product_id: String,
    pub machine_id: String,
    pub sequence: u64,
    pub activated_at: String,
    pub issued_at: String,
    pub expires_at: String,
    pub key_version: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SignedCertificate { payload: Certificate, signature: String }
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope { scheme: String, certificate: SignedCertificate, payload: Payload, signature: String }

// Existing Python wire format uses sorted keys and ensure_ascii=True.
pub(crate) fn canonical<T: Serialize>(value: &T) -> Result<Vec<u8>> {
    let v = serde_json::to_value(value).map_err(|_| "INVALID")?;
    let s = serde_json::to_string(&v).map_err(|_| "INVALID")?;
    let mut ascii = String::new();
    for c in s.chars() {
        if c.is_ascii() { ascii.push(c); }
        else {
            let mut units = [0; 2];
            for unit in c.encode_utf16(&mut units) { ascii.push_str(&format!("\\u{unit:04x}")); }
        }
    }
    Ok(ascii.into_bytes())
}
pub(crate) fn signature<T: Serialize>(public: &str, domain: &str, value: &T, encoded: &str) -> Result<()> {
    let key: [u8; 32] = URL_SAFE_NO_PAD.decode(public).map_err(|_| "INVALID")?.try_into().map_err(|_| "INVALID")?;
    let key = VerifyingKey::from_bytes(&key).map_err(|_| "INVALID")?;
    let sig = Signature::from_slice(&URL_SAFE_NO_PAD.decode(encoded).map_err(|_| "INVALID")?).map_err(|_| "INVALID")?;
    let mut message = domain.as_bytes().to_vec(); message.push(0); message.extend(canonical(value)?);
    key.verify_strict(&message, &sig).map_err(|_| "INVALID")
}
pub fn timestamp(value: &str) -> Result<i64> {
    DateTime::parse_from_rfc3339(value).map(|v| v.timestamp()).map_err(|_| "INVALID")
}
pub fn verify(token: &str, root: &str, machine: &str) -> Result<(Payload, String)> {
    if token.len() > 32768 { return Err("INVALID"); }
    let raw = URL_SAFE_NO_PAD.decode(token).map_err(|_| "INVALID")?;
    // Deserialize directly into typed structs: duplicate and unknown fields fail.
    let e: Envelope = serde_json::from_slice(&raw).map_err(|_| "INVALID")?;
    if e.scheme != "ed25519-v1" { return Err("INVALID"); }
    let c = &e.certificate.payload;
    signature(root, "product-signing-key-v1", c, &e.certificate.signature)?;
    if c.product_id != PRODUCT || e.payload.product_id != PRODUCT { return Err("WRONG_PRODUCT"); }
    signature(&c.public_key, "machine-license-v1", &e.payload, &e.signature)?;
    let p = e.payload;
    if p.sequence == 0 || p.key_version == 0 || c.key_version != p.key_version { return Err("INVALID"); }
    for id in [&p.license_id, &p.entitlement_id, &p.customer_id] {
        if id.is_empty() || id.len() > 80 || !id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-') { return Err("INVALID"); }
    }
    if p.machine_id.len() != 64 || !p.machine_id.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) { return Err("INVALID"); }
    if !(timestamp(&p.activated_at)? <= timestamp(&p.issued_at)? && timestamp(&p.issued_at)? < timestamp(&p.expires_at)?) { return Err("INVALID"); }
    if p.machine_id != machine { return Err("WRONG_MACHINE"); }
    Ok((p, c.public_key.clone()))
}
/// Local clocks and HTTPS `Date` headers disagree by a few seconds; an offline check
/// followed by an online one must not look like a rollback. Real rollbacks are larger.
pub const CLOCK_SKEW_SECONDS: i64 = 300;
pub fn expiration(p: &Payload, now: i64, last: i64) -> Result<()> {
    if now + CLOCK_SKEW_SECONDS < last || now + CLOCK_SKEW_SECONDS < timestamp(&p.activated_at)? { return Err("CLOCK_ROLLBACK"); }
    if now >= timestamp(&p.expires_at)? { return Err("EXPIRED"); }
    Ok(())
}

#[derive(Deserialize, Serialize, Clone)]
pub struct State {
    pub current_license: String,
    pub current_public_key: String,
    pub machine_id: String,
    #[serde(alias = "license_sequence")]
    pub highest_sequence: u64,
    pub last_verified_time: i64,
    #[serde(default)]
    pub key_version: u64,
}
pub fn verified(state: &State, root: &str, machine: &str) -> Result<Payload> {
    let (p, public) = verify(&state.current_license, root, machine)?;
    if state.machine_id != machine || state.highest_sequence != p.sequence || state.current_public_key != public
        || (state.key_version != 0 && state.key_version != p.key_version) { return Err("INVALID"); }
    Ok(p)
}
pub fn adopt(old: Option<&State>, token: &str, renewal: bool, root: &str, machine: &str) -> Result<State> {
    let (p, public) = verify(token, root, machine)?;
    if let Some(old) = old {
        let current = verified(old, root, machine)?;
        if !renewal { return Err("ALREADY_ACTIVATED"); }
        if (&p.license_id, &p.entitlement_id, &p.customer_id, &p.activated_at) != (&current.license_id, &current.entitlement_id, &current.customer_id, &current.activated_at) { return Err("INVALID"); }
        if old.highest_sequence.checked_add(1) != Some(p.sequence) { return Err("SEQUENCE_REPLAY"); }
        if p.key_version < current.key_version || timestamp(&p.expires_at)? <= timestamp(&current.expires_at)? { return Err("INVALID"); }
    } else if renewal || p.sequence != 1 { return Err("RENEWAL_REQUIRED"); }
    Ok(State { current_license: token.into(), current_public_key: public, machine_id: machine.into(), highest_sequence: p.sequence,
        last_verified_time: old.map(|s| s.last_verified_time).unwrap_or(0), key_version: p.key_version })
}
pub fn status(state: &State, root: &str, machine: &str, now: i64) -> Result<Value> {
    let p = verified(state, root, machine)?; expiration(&p, now, state.last_verified_time)?;
    Ok(json!({"status":"ACTIVE", "sequence":p.sequence, "expires_at":p.expires_at, "product_id":PRODUCT}))
}
