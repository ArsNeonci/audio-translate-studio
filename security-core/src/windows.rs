use crate::license::{Result, State};
use fs2::FileExt;
use sha2::{Digest, Sha256};
use std::{fs::{self, File, OpenOptions}, io::Write, path::{Path, PathBuf}};
use windows_sys::Win32::{Security::Cryptography::{CryptProtectData, CryptUnprotectData, CRYPT_INTEGER_BLOB}, Foundation::LocalFree, System::SystemInformation::GetSystemFirmwareTable, Storage::FileSystem::{MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH}};
use winreg::{enums::{HKEY_LOCAL_MACHINE, KEY_READ, KEY_WOW64_64KEY}, RegKey};

fn normalize(s: &str) -> Result<String> {
    let value: String = s.to_ascii_lowercase().chars().filter(|c| c.is_ascii_hexdigit()).collect();
    if value.len() != 32 || value == "0".repeat(32) || value == "f".repeat(32) { return Err("MACHINE_ID_UNAVAILABLE"); }
    Ok(value)
}
pub fn machine_id() -> Result<String> {
    let key = RegKey::predef(HKEY_LOCAL_MACHINE).open_subkey_with_flags("SOFTWARE\\Microsoft\\Cryptography", KEY_READ | KEY_WOW64_64KEY).map_err(|_| "MACHINE_ID_UNAVAILABLE")?;
    let guid: String = key.get_value("MachineGuid").map_err(|_| "MACHINE_ID_UNAVAILABLE")?;
    // RawSMBIOSData (RSMB), type 1 UUID. Match WMI's SMBIOS >=2.6 byte order.
    let provider = u32::from_be_bytes(*b"RSMB");
    let size = unsafe { GetSystemFirmwareTable(provider, 0, std::ptr::null_mut(), 0) };
    if !(8..=1024*1024).contains(&size) { return Err("MACHINE_ID_UNAVAILABLE"); }
    let mut raw = vec![0u8; size as usize];
    if unsafe { GetSystemFirmwareTable(provider, 0, raw.as_mut_ptr().cast(), size) } != size { return Err("MACHINE_ID_UNAVAILABLE"); }
    let mut offset = 8;
    let mut system_uuid = None;
    while offset + 4 <= raw.len() {
        let kind = raw[offset]; let len = raw[offset+1] as usize;
        if len < 4 || offset + len > raw.len() { break; }
        if kind == 1 && len >= 24 {
            let mut uuid = raw[offset+8..offset+24].to_vec();
            if raw[1] > 2 || (raw[1] == 2 && raw[2] >= 6) { uuid[..4].reverse(); uuid[4..6].reverse(); uuid[6..8].reverse(); }
            system_uuid = Some(hex::encode(uuid)); break;
        }
        offset += len;
        while offset+1 < raw.len() && !(raw[offset] == 0 && raw[offset+1] == 0) { offset += 1; }
        offset += 2;
    }
    let guid = normalize(&guid)?; let uuid = normalize(&system_uuid.ok_or("MACHINE_ID_UNAVAILABLE")?)?;
    Ok(hex::encode(Sha256::digest(format!("machine-v1|{guid}|{uuid}").as_bytes())))
}
fn protect(raw: &mut [u8], decrypt: bool) -> Result<Vec<u8>> {
    let mut entropy = b"shared-license-sdk-v1".to_vec();
    let input = CRYPT_INTEGER_BLOB { cbData: raw.len() as u32, pbData: raw.as_mut_ptr() };
    let ent = CRYPT_INTEGER_BLOB { cbData: entropy.len() as u32, pbData: entropy.as_mut_ptr() };
    let mut output = CRYPT_INTEGER_BLOB { cbData: 0, pbData: std::ptr::null_mut() };
    let ok = unsafe {
        if decrypt { CryptUnprotectData(&input, std::ptr::null_mut(), &ent, std::ptr::null(), std::ptr::null(), 1, &mut output) }
        else { CryptProtectData(&input, std::ptr::null(), &ent, std::ptr::null(), std::ptr::null(), 1 | 4, &mut output) }
    };
    if ok == 0 { return Err("INVALID"); }
    let result = unsafe { std::slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec() };
    unsafe { std::ptr::write_bytes(output.pbData, 0, output.cbData as usize); LocalFree(output.pbData.cast()); }
    raw.fill(0); Ok(result)
}
pub struct Store { pub path: PathBuf, _lock: File }
impl Store {
    pub fn open(path: &Path) -> Result<Self> {
        fs::create_dir_all(path.parent().ok_or("INVALID")?).map_err(|_| "INVALID")?;
        let lock = OpenOptions::new().create(true).truncate(false).read(true).write(true).open(path.with_extension("lock")).map_err(|_| "INVALID")?;
        lock.lock_exclusive().map_err(|_| "INVALID")?;
        Ok(Self { path: path.into(), _lock: lock })
    }
    pub fn read(&self) -> Result<Option<State>> {
        if !self.path.exists() { return Ok(None); }
        if fs::metadata(&self.path).map_err(|_| "INVALID")?.len() > 65536 { return Err("INVALID"); }
        let mut raw = fs::read(&self.path).map_err(|_| "INVALID")?;
        let mut plain = protect(&mut raw, true)?;
        // Legacy Python saved floating point time.time(); migration preserves it.
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
        let raw = protect(&mut plain, false)?;
        let temp = self.path.with_extension(format!("{}.tmp", std::process::id()));
        let result = (|| {
            let mut file = OpenOptions::new().create_new(true).write(true).open(&temp).map_err(|_| "INVALID")?;
            file.write_all(&raw).and_then(|_| file.sync_all()).map_err(|_| "INVALID")?; drop(file);
            fn wide(p: &Path) -> Vec<u16> { use std::os::windows::ffi::OsStrExt; p.as_os_str().encode_wide().chain(Some(0)).collect() }
            if unsafe { MoveFileExW(wide(&temp).as_ptr(), wide(&self.path).as_ptr(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) } == 0 { return Err("INVALID"); }
            Ok(())
        })();
        let _ = fs::remove_file(temp); result
    }
}
