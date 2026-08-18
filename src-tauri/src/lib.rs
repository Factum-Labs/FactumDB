//! FactumDB shell.
//!
//! This is a UI-only build: no domain or backend logic lives here yet. The
//! frontend runs entirely off hardcoded fixtures in `src/data/caseData.ts`.
//!
//! When the Python sidecar and domain services land, the commands the frontend
//! needs are registered here and the fixture module is swapped for real calls.

#[tauri::command]
fn app_info() -> serde_json::Value {
    serde_json::json!({
        "name": "FactumDB",
        "version": env!("CARGO_PKG_VERSION"),
        "mode": "ui-demo",
        "backend": "none — frontend fixtures only"
    })
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![app_info])
        .run(tauri::generate_context!())
        .expect("error while running FactumDB");
}
