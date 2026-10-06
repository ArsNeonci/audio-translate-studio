use super::*;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use ed25519_dalek::{Signer, SigningKey};
use license::{adopt, expiration, verify, verified, timestamp, CLOCK_SKEW_SECONDS};

fn signed(key: &SigningKey, domain: &str, value: &Value) -> String {
    let mut bytes=domain.as_bytes().to_vec(); bytes.push(0); bytes.extend(serde_json::to_vec(value).unwrap());
    URL_SAFE_NO_PAD.encode(key.sign(&bytes).to_bytes())
}
fn fixture(machine: &str, sequence: u64, key_version: u64, product: &str) -> (String, String) {
    let root=SigningKey::from_bytes(&[17;32]); let signer=SigningKey::from_bytes(&[key_version as u8;32]);
    let public=URL_SAFE_NO_PAD.encode(root.verifying_key().to_bytes());
    let cert=json!({"product_id":product,"key_version":key_version,"public_key":URL_SAFE_NO_PAD.encode(signer.verifying_key().to_bytes())});
    let payload=json!({"license_id":"test","entitlement_id":"entitlement","customer_id":"customer","product_id":product,
        "machine_id":machine,"sequence":sequence,"activated_at":"2026-01-01T00:00:00+00:00","issued_at":"2026-01-01T00:00:00+00:00",
        "expires_at":format!("{}-01-01T00:00:00+00:00",2027+sequence),"key_version":key_version});
    let envelope=json!({"scheme":"ed25519-v1","certificate":{"payload":cert,"signature":signed(&root,"product-signing-key-v1",&cert)},
        "payload":payload,"signature":signed(&signer,"machine-license-v1",&payload)});
    (URL_SAFE_NO_PAD.encode(serde_json::to_vec(&envelope).unwrap()),public)
}
#[test] fn valid_and_expired() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let (p,_)=verify(&token,&root,&machine).unwrap();
    assert!(expiration(&p,license::timestamp("2026-06-01T00:00:00Z").unwrap(),0).is_ok());
    assert_eq!(expiration(&p,license::timestamp(&p.expires_at).unwrap(),0),Err("EXPIRED"));
}
#[test] fn wrong_machine_and_product() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    assert_eq!(verify(&token,&root,&"b".repeat(64)).unwrap_err(),"WRONG_MACHINE");
    let (token,root)=fixture(&machine,1,1,"another-product");
    assert_eq!(verify(&token,&root,&machine).unwrap_err(),"WRONG_PRODUCT");
}
#[test] fn tamper_and_fake_root_rejected() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let mut e: Value=serde_json::from_slice(&URL_SAFE_NO_PAD.decode(&token).unwrap()).unwrap();
    e["payload"]["sequence"]=json!(99);
    let changed=URL_SAFE_NO_PAD.encode(serde_json::to_vec(&e).unwrap());
    assert_eq!(verify(&changed,&root,&machine).unwrap_err(),"INVALID");
    assert_eq!(verify(&token,ROOT,&machine).unwrap_err(),"INVALID");
}
#[test] fn duplicate_fields_rejected() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let text=String::from_utf8(URL_SAFE_NO_PAD.decode(token).unwrap()).unwrap().replace("\"sequence\":1", "\"sequence\":1,\"sequence\":1");
    assert_eq!(verify(&URL_SAFE_NO_PAD.encode(text),&root,&machine).unwrap_err(),"INVALID");
}
#[test] fn renewal_and_rotation_keep_root() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let old=adopt(None,&token,false,&root,&machine).unwrap();
    let (next,root2)=fixture(&machine,2,2,PRODUCT);assert_eq!(root,root2);
    let renewed=adopt(Some(&old),&next,true,&root,&machine).unwrap();assert_eq!(renewed.highest_sequence,2);
    assert_eq!(adopt(Some(&renewed),&next,true,&root,&machine).err(),Some("SEQUENCE_REPLAY"));
    let (skip,_)=fixture(&machine,4,2,PRODUCT);
    assert_eq!(adopt(Some(&old),&skip,true,&root,&machine).err(),Some("SEQUENCE_REPLAY"));
    assert_eq!(adopt(Some(&old),&token,false,&root,&machine).err(),Some("ALREADY_ACTIVATED"));
}
#[test] fn rollback_and_state_mutation_rejected() {
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let mut state=adopt(None,&token,false,&root,&machine).unwrap();
    state.highest_sequence=2;assert_eq!(verified(&state,&root,&machine).unwrap_err(),"INVALID");
    let (p,_)=verify(&token,&root,&machine).unwrap(); assert_eq!(expiration(&p,100,200+CLOCK_SKEW_SECONDS),Err("CLOCK_ROLLBACK"));
    let skew=timestamp(&p.activated_at).unwrap()+1000; assert_eq!(expiration(&p,skew-2,skew),Ok(()));
}
#[test] fn dpapi_restart_and_copied_state() {
    let temp=tempfile::tempdir().unwrap();let path=temp.path().join("state.dpapi");
    let machine="a".repeat(64);let (token,root)=fixture(&machine,1,1,PRODUCT);
    let state=adopt(None,&token,false,&root,&machine).unwrap();
    { let store=windows::Store::open(&path).unwrap();store.write(&state).unwrap(); }
    let raw=std::fs::read(&path).unwrap();assert!(!raw.windows(token.len()).any(|s|s==token.as_bytes()));
    let store=windows::Store::open(&path).unwrap();let saved=store.read().unwrap().unwrap();
    assert_eq!(verified(&saved,&root,&machine).unwrap().sequence,1);
    assert_eq!(verified(&saved,&root,&"b".repeat(64)).unwrap_err(),"WRONG_MACHINE");
}
#[test] fn fingerprint_is_stable() {
    let first=windows::machine_id().unwrap();assert_eq!(first.len(),64);assert_eq!(first,windows::machine_id().unwrap());
}
#[test] fn edition_follows_product_id() {
    assert_eq!(license::tier("audio-translate-basic"),"basic");
    assert_eq!(license::tier("audio-translate-plus"),"plus");
    assert_eq!(license::tier("audio-translate"),"plus");
}
fn sign_manifest(key: &SigningKey, version: &str, entries: &[manifest::Entry]) -> String {
    #[derive(serde::Serialize)] struct S<'a> { version: &'a str, entries: &'a [manifest::Entry] }
    let mut msg = b"payload-manifest-v1".to_vec(); msg.push(0);
    msg.extend(license::canonical(&S { version, entries }).unwrap());
    URL_SAFE_NO_PAD.encode(key.sign(&msg).to_bytes())
}
fn file_sha(p: &std::path::Path) -> String { use sha2::{Digest, Sha256}; hex::encode(Sha256::digest(std::fs::read(p).unwrap())) }

#[test] fn manifest_verify_and_tamper() {
    let key = SigningKey::from_bytes(&[31; 32]);
    let pubk = URL_SAFE_NO_PAD.encode(key.verifying_key().to_bytes());
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("core.exe"), b"BINARY").unwrap();
    std::fs::create_dir_all(dir.path().join("config")).unwrap();
    std::fs::write(dir.path().join("config/a.json"), b"{}").unwrap();
    let entries = vec![
        manifest::Entry { path: "core.exe".into(), sha256: file_sha(&dir.path().join("core.exe")), kind: "binary".into(), version: "1".into(), runtime: true },
        manifest::Entry { path: "config/a.json".into(), sha256: file_sha(&dir.path().join("config/a.json")), kind: "config".into(), version: "1".into(), runtime: false },
    ];
    let signature = sign_manifest(&key, "1.2.0", &entries);
    let m = manifest::Manifest { version: "1.2.0".into(), entries, signature };
    let json = serde_json::to_string(&m).unwrap();
    let parsed = manifest::parse_with(&json, &pubk).unwrap();
    assert!(manifest::verify_tree(dir.path(), &parsed, manifest::Scope::Install).is_ok());
    assert!(manifest::verify_tree(dir.path(), &parsed, manifest::Scope::Runtime).is_ok());
    // A different key must not validate the same manifest bytes.
    let other = URL_SAFE_NO_PAD.encode(SigningKey::from_bytes(&[32; 32]).verifying_key().to_bytes());
    assert_eq!(manifest::parse_with(&json, &other).unwrap_err(), "INTEGRITY_FAILURE");
    // Config altered: runtime scope skips non-runtime entries, install scope catches it.
    std::fs::write(dir.path().join("config/a.json"), b"{\"x\":1}").unwrap();
    assert!(manifest::verify_tree(dir.path(), &parsed, manifest::Scope::Runtime).is_ok());
    assert_eq!(manifest::verify_tree(dir.path(), &parsed, manifest::Scope::Install).unwrap_err(), "INTEGRITY_FAILURE");
    // Binary altered: both scopes fail as UNTRUSTED_BINARY.
    std::fs::write(dir.path().join("core.exe"), b"HACKED!").unwrap();
    assert_eq!(manifest::verify_tree(dir.path(), &parsed, manifest::Scope::Runtime).unwrap_err(), "UNTRUSTED_BINARY");
}

#[test] fn manifest_rejects_traversal() {
    let key = SigningKey::from_bytes(&[31; 32]);
    let pubk = URL_SAFE_NO_PAD.encode(key.verifying_key().to_bytes());
    for bad in ["../evil", "C:/evil", "/evil", "a/../b", ""] {
        let entries = vec![manifest::Entry { path: bad.into(), sha256: "ab".repeat(32), kind: "binary".into(), version: "1".into(), runtime: true }];
        let signature = sign_manifest(&key, "1", &entries);
        let m = manifest::Manifest { version: "1".into(), entries, signature };
        assert_eq!(manifest::parse_with(&serde_json::to_string(&m).unwrap(), &pubk).unwrap_err(), "INTEGRITY_FAILURE", "path {bad:?}");
    }
}

#[test] fn all_admission_commands_protected() {
    for action in ["create","convert","reprocess","resume","preflight","review"] { assert_eq!(command_protected("manage.py",action),Ok(true)); }
    assert_eq!(command_protected("retry.py","retry"),Ok(true));
    assert_eq!(command_protected("manage.py","history"),Ok(false));
    assert_eq!(command_protected("manage.py","unknown"),Err("INVALID_ACTION"));
    assert_eq!(command_protected("anything.py","create"),Err("INVALID_ACTION"));
}

#[test] fn lease_phases_and_grace_bounds() {
    assert_eq!(lease::phase(99, 100, 50), "VALID");
    assert_eq!(lease::phase(100, 100, 50), "GRACE");
    assert_eq!(lease::phase(149, 100, 50), "GRACE");
    assert_eq!(lease::phase(150, 100, 50), "EXPIRED");
    assert_eq!(lease::phase(100, 100, 0), "EXPIRED");
}
