use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use std::{env, fs};

fn main() {
    // Build input only. The executable never opens this file or public-config.json.
    let source = env::var("AUDIO_TRUST_ANCHOR_BUILD_FILE")
        .unwrap_or_else(|_| "trust-anchor.json".into());
    println!("cargo:rerun-if-env-changed=AUDIO_TRUST_ANCHOR_BUILD_FILE");
    println!("cargo:rerun-if-changed={source}");
    let data: serde_json::Value = serde_json::from_slice(&fs::read(&source).expect("trust anchor required")).expect("invalid anchor");
    // Legacy single product plus the two editions; each has its own root key in Admin.
    let product = data["product_id"].as_str().expect("product required");
    assert!(["audio-translate", "audio-translate-basic", "audio-translate-plus"].contains(&product), "unknown product");
    let key = data["root_public_key"].as_str().expect("root required");
    assert_eq!(URL_SAFE_NO_PAD.decode(key).expect("invalid root encoding").len(), 32);
    println!("cargo:rustc-env=EMBEDDED_PRODUCT_ID={product}");
    println!("cargo:rustc-env=EMBEDDED_ROOT_PUBLIC_KEY={key}");
    // Optional separate manifest key. Admin embeds it for release; absent in dev builds,
    // where integrity verification reports itself unconfigured instead of failing closed.
    let manifest = match data.get("manifest_public_key").and_then(|v| v.as_str()) {
        Some(m) => { assert_eq!(URL_SAFE_NO_PAD.decode(m).expect("invalid manifest encoding").len(), 32); m.to_string() }
        None => String::new(),
    };
    println!("cargo:rustc-env=EMBEDDED_MANIFEST_PUBLIC_KEY={manifest}");
    // Optional content key for the asset vault (Phase 2B). The service releases it only to an
    // authorized caller; absent in dev builds, where the vault falls back to plaintext sources.
    // Phase 2C replaces this embedded key with a lease-delivered key when a lease is present.
    let content = match data.get("content_key").and_then(|v| v.as_str()) {
        Some(c) => { assert_eq!(URL_SAFE_NO_PAD.decode(c).expect("invalid content key encoding").len(), 32); c.to_string() }
        None => String::new(),
    };
    println!("cargo:rustc-env=EMBEDDED_CONTENT_KEY={content}");
}
