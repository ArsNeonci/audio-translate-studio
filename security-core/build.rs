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
}
